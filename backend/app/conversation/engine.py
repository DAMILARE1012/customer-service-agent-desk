"""Conversation operations for the API. Each one is a Langfuse trace, grouped by conversation (session)
and customer (user); state transitions come from lifecycle.py, bot turns from bot.py."""

import re

from app.conversation import lifecycle
from app.conversation.bot import bot_turn, draft_copilot
from app.conversation.constants import HandoffReason, Sender, Status, SystemEvent
from app.conversation.util import truncate
from app.observability.metrics import copilot_drafts, handoff_wait, handoffs, label
from app.observability.tracing import observe, trace_attributes

create_conversation = lifecycle.create_conversation
return_to_bot = lifecycle.return_to_bot
resolve_conversation = lifecycle.resolve_conversation


def _traced(conversation: dict, name: str):
    customer = conversation["customer"]
    return trace_attributes(
        session_id=conversation["id"],
        user_id=customer["id"],
        trace_name=name,
        tags=["baton", f"tier:{customer['tier']}"],
        metadata={"customerTier": customer["tier"]},
    )


async def receive_customer_message(conversation: dict, text: str, now: int) -> dict:
    with _traced(conversation, "customer-message"), observe("customer-message", input=text) as span:
        if conversation["status"] == Status.RESOLVED:
            conversation.update(status=Status.BOT_ACTIVE, assignee=None)
            lifecycle.add_system_event(conversation, SystemEvent.REOPENED, "Customer replied — conversation reopened", now)

        message = lifecycle.add_message(conversation, {"sender": Sender.CUSTOMER, "text": text, "createdAt": now})
        conversation["subject"] = conversation["subject"] or truncate(text, 70)
        sentiment = lifecycle.track_signals(conversation, message)

        outcome = None
        if conversation["status"] == Status.BOT_ACTIVE:
            outcome = await bot_turn(conversation, message, sentiment, now)
        elif conversation["status"] == Status.AGENT_ACTIVE:
            conversation["copilot"] = await draft_copilot(conversation, text)
        # HANDOFF_PENDING: the bot has stepped aside and just listens.

        # What the trace list shows: the bot's reply, or why it stepped aside.
        if outcome and outcome.get("reply"):
            reply = outcome["reply"]
        elif outcome and outcome["kind"] == "handed_off":
            reply = f"[handed off: {outcome['reason']}]"
        else:
            reply = f"[{conversation['status']}: bot not replying]"
        span.update(output=reply, metadata={"status": conversation["status"], "outcome": outcome["kind"] if outcome else "none"})
        return conversation


async def accept_handoff(conversation: dict, agent: dict, now: int) -> dict:
    with _traced(conversation, "accept-handoff"), observe("accept-handoff"):
        lifecycle.accept_handoff(conversation, agent, now)
        handoff = conversation["handoff"]
        handoff_wait.labels(**label(priority=handoff["priority"])).observe((now - handoff["requestedAt"]) / 1000)
        conversation["copilot"] = await draft_copilot(conversation, lifecycle.last_open_question(conversation))
        return conversation


async def take_over(conversation: dict, agent: dict, now: int) -> dict:
    with _traced(conversation, "take-over"), observe("take-over"):
        lifecycle.take_over(conversation, agent, now)
        handoffs.labels(**label(reason=HandoffReason.AGENT_INITIATED, priority=conversation["handoff"]["priority"])).inc()
        conversation["copilot"] = await draft_copilot(conversation, lifecycle.last_open_question(conversation))
        return conversation


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
