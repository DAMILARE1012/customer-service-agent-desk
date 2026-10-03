"""Conversation operations for the API. Each one is a Langfuse trace, grouped by conversation (session)
and customer (user); state transitions come from lifecycle.py, bot turns from bot.py.

No database connection is held while the LLM works. Operations that need it run in three steps:

    1. locked     apply the change and, for a bot turn, claim it (conversation["botTurn"])
    2. unlocked   the LLM work (bot turn, copilot draft) on a copy of the conversation
    3. locked     save the result only if it still applies — an agent may have taken over, or the
                  customer ended the chat, while the LLM was working; then the result is dropped

A customer message that arrives while a bot turn is in progress waits for it, holding nothing, so turns
stay in order. A claim left behind by a crashed process expires after BOT_TURN_STALE_MS.
"""

import asyncio
import copy
import logging
import re

from app import team
from app.config import settings
from app.conversation import lifecycle, store
from app.conversation.bot import bot_turn, draft_copilot
from app.conversation.constants import ClosedReason, HandoffReason, Sender, Status
from app.conversation.lifecycle import ApiError
from app.conversation.util import now_ms, truncate
from app.observability.metrics import conversations_closed, copilot_drafts, handoff_wait, handoffs, label
from app.observability.tracing import current_trace_id, observe, trace_attributes

log = logging.getLogger(__name__)
create_conversation = lifecycle.create_conversation
return_to_bot = lifecycle.return_to_bot
leave_contact = lifecycle.leave_contact


def close_conversation(conversation: dict, reason: ClosedReason, now: int, actor: dict | None = None) -> dict:
    with _traced(conversation, f"close:{reason}"), observe("close-conversation", input={"reason": reason}):
        _remember_trace(conversation)
        lifecycle.close_conversation(conversation, reason, now, actor)
        conversations_closed.labels(**label(reason=reason)).inc()
        return conversation


def resolve_conversation(conversation: dict, actor: dict | None, now: int) -> dict:
    with _traced(conversation, "resolve"), observe("resolve"):
        _remember_trace(conversation)
        lifecycle.resolve_conversation(conversation, actor, now)
        conversations_closed.labels(**label(reason=ClosedReason.RESOLVED)).inc()
        return conversation


def _remember_trace(conversation: dict) -> None:
    """Keep the conversation's Langfuse trace ids, so erasing a customer can delete their traces too."""
    trace_id = current_trace_id()
    traces = conversation.setdefault("traceIds", [])
    if trace_id and trace_id not in traces:
        traces.append(trace_id)


def _traced(conversation: dict, name: str):
    customer = conversation["customer"]
    return trace_attributes(
        session_id=conversation["id"],
        user_id=customer["id"],
        trace_name=name,
        tags=["baton", f"tier:{customer['tier']}", *(["follow-up"] if conversation.get("followUpOf") else [])],
        metadata={"customerTier": customer["tier"]},
    )


def bot_turn_stale_ms() -> int:
    """Longer than any bot turn can take: every LLM attempt timing out, plus a JSON retry and retrieval."""
    return settings.llm_timeout_ms * (settings.llm_max_retries + 1) * 2 + 30_000


TURN_WAIT_S = 0.25  # how often a message queued behind a bot turn checks whether it's done


def _turn_in_progress(conversation: dict, now: int) -> bool:
    turn = conversation.get("botTurn")
    return bool(turn) and conversation["status"] == Status.BOT_ACTIVE and now - turn["startedAt"] < bot_turn_stale_ms()


def accept_customer_message(conversation: dict, text: str, now: int) -> dict | None:
    """Step 1 of a customer message (locked, no LLM): record it and say what LLM work it needs, if any."""
    if conversation["status"] == Status.RESOLVED:
        # Sessions don't reopen: a returning customer starts fresh (optionally as a linked follow-up).
        raise ApiError(409, "This conversation has ended. Start a new one — you can link it to this one as a follow-up.")
    conversation["customerSeenAt"] = now
    message = lifecycle.add_message(conversation, {"sender": Sender.CUSTOMER, "text": text, "createdAt": now})
    conversation["subject"] = conversation["subject"] or truncate(text, 70)
    sentiment = lifecycle.track_signals(conversation, message)
    match conversation["status"]:
        case Status.BOT_ACTIVE:
            conversation["botTurn"] = {"messageId": message["id"], "startedAt": now}
            return {"kind": "bot", "message": message, "sentiment": sentiment}
        case Status.AGENT_ACTIVE:
            return {"kind": "copilot", "message": message}
        case Status.HANDOFF_PENDING:
            lifecycle.note_while_waiting(conversation, message, sentiment, now)
    return None


async def receive_customer_message(conversation_id: str, customer: dict, text: str) -> dict:
    """A customer message: record it, then let the bot answer (or draft for the agent) without holding the
    conversation locked during the LLM call. Returns the conversation as saved."""
    while True:
        head = await store.get_own(conversation_id, customer)
        if not _turn_in_progress(head, now_ms()):
            break
        await asyncio.sleep(TURN_WAIT_S)  # the bot is still answering this customer's previous message

    with _traced(head, "customer-message"), observe("customer-message", input=text) as span:
        work = None
        while work is None:
            async with store.own_transaction(conversation_id, customer) as conversation:
                now = now_ms()
                if _turn_in_progress(conversation, now):
                    work = "wait"  # another message claimed the turn between our check and the lock
                else:
                    _remember_trace(conversation)
                    work = accept_customer_message(conversation, text, now) or {"kind": "none"}
            if work == "wait":
                work = None
                await asyncio.sleep(TURN_WAIT_S)

        if work["kind"] == "bot":
            work["team"] = await team.status(now)  # if the bot hands off, is anyone there?
            conversation = await _bot_turn_unlocked(conversation_id, customer, conversation, work, now)
        elif work["kind"] == "copilot":
            draft = await draft_copilot(copy.deepcopy(conversation), text)
            conversation = await _save_copilot(conversation_id, conversation, draft, for_message=work["message"]["id"]) or conversation

        last = next((m for m in reversed(conversation["messages"]) if m["sender"] != Sender.CUSTOMER), None)
        span.update(output=last["text"] if last else None, metadata={"status": conversation["status"]})
        return conversation


async def _bot_turn_unlocked(conversation_id: str, customer: dict, claimed: dict, work: dict, now: int) -> dict:
    """Steps 2 and 3 of a bot turn: run it on a copy, then save it if the turn is still ours."""
    snapshot = copy.deepcopy(claimed)
    snapshot["_team"] = work.get("team")
    message_id = work["message"]["id"]
    finished = False
    try:
        await bot_turn(snapshot, work["message"], work["sentiment"], now)
        finished = True
    finally:
        async with store.own_transaction(conversation_id, customer) as fresh:
            ours = (fresh.get("botTurn") or {}).get("messageId") == message_id
            unchanged = ours and fresh["status"] == Status.BOT_ACTIVE and len(fresh["messages"]) == len(claimed["messages"])
            if unchanged and finished:  # the turn finished on the copy: it becomes the saved state
                seen = max(fresh["customerSeenAt"] or 0, snapshot["customerSeenAt"] or 0)
                snapshot.pop("_team", None)
                fresh.clear()
                fresh.update(snapshot, botTurn=None, customerSeenAt=seen)
            elif ours:
                if fresh["status"] == Status.BOT_ACTIVE:
                    log.warning("bot turn for %s could not be applied; releasing it", conversation_id)
                fresh["botTurn"] = None  # an agent took over or the chat closed meanwhile: the bot's reply is dropped
    return fresh


async def _save_copilot(conversation_id: str, conversation: dict, draft: dict | None, *, for_message: str | None = None) -> dict | None:
    """Step 3 of a copilot draft: attach it if the agent is still on the conversation and nothing newer was asked."""
    if not draft:
        return None
    async with store.transaction(conversation_id) as fresh:
        last_question = next((m["id"] for m in reversed(fresh["messages"]) if m["sender"] == Sender.CUSTOMER), None)
        expected = for_message or next((m["id"] for m in reversed(conversation["messages"]) if m["sender"] == Sender.CUSTOMER), None)
        same_agent = (fresh["assignee"] or {}).get("id") == (conversation["assignee"] or {}).get("id")
        if fresh["status"] == Status.AGENT_ACTIVE and same_agent and last_question == expected:
            fresh["copilot"] = draft
            _remember_trace(fresh)
    return fresh


async def _with_first_draft(conversation_id: str, conversation: dict) -> dict:
    """After an agent joins: draft a reply to the open question, outside the lock."""
    with _traced(conversation, "copilot-draft"):
        draft = await draft_copilot(copy.deepcopy(conversation), lifecycle.last_open_question(conversation))
        return await _save_copilot(conversation_id, conversation, draft) or conversation


def _check_capacity(conversation: dict, agent: dict) -> None:
    """Counted under the agent's lock (store.transaction(agent=…)), so simultaneous accepts can't overshoot."""
    if conversation.pop("_agentLoad", 0) >= agent["capacity"]:
        raise ApiError(409, f"You’re at capacity ({agent['capacity']} active chats). Resolve or return one first.")


async def accept_handoff(conversation_id: str, agent: dict) -> dict:
    async with store.transaction(conversation_id, agent=agent["id"]) as conversation:
        _check_capacity(conversation, agent)
        with _traced(conversation, "accept-handoff"), observe("accept-handoff"):
            _remember_trace(conversation)
            now = now_ms()
            lifecycle.accept_handoff(conversation, agent, now)
            handoff = conversation["handoff"]
            handoff_wait.labels(**label(priority=handoff["priority"])).observe((now - handoff["requestedAt"]) / 1000)
    return await _with_first_draft(conversation_id, conversation)


async def take_over(conversation_id: str, agent: dict) -> dict:
    async with store.transaction(conversation_id, agent=agent["id"]) as conversation:
        _check_capacity(conversation, agent)
        with _traced(conversation, "take-over"), observe("take-over"):
            _remember_trace(conversation)
            lifecycle.take_over(conversation, agent, now_ms())
            handoffs.labels(**label(reason=HandoffReason.AGENT_INITIATED, priority=conversation["handoff"]["priority"])).inc()
    return await _with_first_draft(conversation_id, conversation)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def classify_draft_use(draft: str, sent: str) -> str:
    """What the agent did with the copilot draft: sent as-is, edited, or wrote their own."""
    if draft.strip() == sent.strip():
        return "used"
    a, b = _words(draft), _words(sent)
    return "edited" if len(a & b) / max(1, len(a | b)) >= 0.5 else "ignored"


def post_agent_message(conversation: dict, agent: dict, text: str, now: int) -> dict:
    draft = (conversation.get("copilot") or {}).get("text")
    if draft and (conversation["assignee"] or {}).get("id") == agent["id"]:
        copilot_drafts.labels(**label(action=classify_draft_use(draft, text))).inc()
    lifecycle.post_agent_message(conversation, agent, text, now)
    return conversation
