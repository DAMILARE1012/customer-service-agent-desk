"""Synchronous state transitions shared by every bot implementation.

Pure functions over the conversation dict (wire format), so they're trivial to test. The async,
LLM-backed parts (bot turns, copilot drafts) live in engine.py and bot.py.
"""

from app.config import settings
from app.conversation.constants import (
    CLOSED_NOTE,
    HANDOFF_NOTICE,
    REASON_LABEL,
    BotReplyKind,
    ClosedReason,
    HandoffReason,
    HandoffStatus,
    Priority,
    Sender,
    Status,
    SystemEvent,
)
from app.conversation.offline import offline_notice
from app.conversation.packet import build_handoff_packet
from app.conversation.policy import compute_priority, conversation_signals
from app.conversation.signals import extract_entities, merge_entities, score_sentiment, sentiment_label
from app.conversation.util import next_id, round2


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def assert_status(conversation: dict, allowed: tuple[Status, ...], action: str) -> None:
    if conversation["status"] not in allowed:
        raise ApiError(409, f"Cannot {action} while conversation is {conversation['status']}.")


def add_message(conversation: dict, message: dict) -> dict:
    full = {"id": next_id("msg"), "meta": None, "event": None, "author": None, **message}
    conversation["messages"].append(full)
    conversation["updatedAt"] = full["createdAt"]
    return full


def add_system_event(conversation: dict, event_type: SystemEvent, text: str, now: int, **extra) -> dict:
    return add_message(conversation, {"sender": Sender.SYSTEM, "text": text, "createdAt": now, "event": {"type": event_type, **extra}})


def add_bot_message(conversation: dict, text: str, now: int, meta: dict) -> dict:
    return add_message(conversation, {"sender": Sender.BOT, "text": text, "createdAt": now, "meta": meta})


def create_conversation(customer: dict, now: int, follow_up_of: dict | None = None) -> dict:
    """A new support session. `follow_up_of` is a snapshot of the closed conversation it continues
    (see views.session_outcome) — shown to agents, never replayed to the bot."""
    return {
        "id": next_id("conv"),
        "customer": customer,
        "status": Status.BOT_ACTIVE,
        "assignee": None,
        "subject": None,
        "createdAt": now,
        "updatedAt": now,
        "closedAt": None,
        "closedReason": None,
        "followUpOf": follow_up_of,
        "customerSeenAt": now,
        "messages": [],
        "insights": {
            "intent": None,
            "lastConfidence": None,
            "sentiment": {"current": 0, "trend": []},
            "entities": [],
            "attempts": [],
            "failedAttempts": 0,
        },
        "handoff": None,
        "handoffHistory": [],
        "copilot": None,
        "botTurn": None,  # {messageId, startedAt} while the bot answers — see engine.py
        "contact": None,  # {email, at}: where to send the reply if the customer has left (see team.py)
    }


def track_signals(conversation: dict, message: dict) -> float:
    """Update sentiment (smoothed) and entities from a customer message; returns current sentiment."""
    insights = conversation["insights"]
    sentiment = score_sentiment(message["text"])
    trend = insights["sentiment"]["trend"]
    # Smoothed so one sharp message registers but a single "thanks" doesn't erase frustration.
    current = sentiment if not trend else round2(sentiment * 0.7 + trend[-1] * 0.3)
    insights["sentiment"] = {"current": current, "trend": [*trend, current]}
    insights["entities"] = merge_entities(insights["entities"], extract_entities(message["text"], message["id"]))
    return current


def record_attempt(insights: dict, question: dict, reply: dict | None, outcome: str, confidence: float, top: dict | None, now: int) -> None:
    insights["attempts"].append({
        "questionMessageId": question["id"],
        "replyMessageId": reply["id"] if reply else None,
        "question": question["text"],
        "outcome": outcome,
        "confidence": confidence,
        "sourceId": top["id"] if top else None,
        "sourceTitle": top["title"] if top else None,
        "at": now,
    })


def request_handoff(conversation: dict, decision: dict, trigger_message: dict | None, now: int) -> None:
    """Step aside for a person. conversation["_team"] (set by engine.py before the turn) says whether anyone
    is available; if not, the customer is told honestly when the team is back and how they'll get the reply."""
    reason = decision["primary"]["reason"]
    team = conversation.get("_team")
    offline = team is not None and not team["available"]
    notice = offline_notice(team, conversation) if offline else HANDOFF_NOTICE[reason]
    add_bot_message(conversation, notice, now, {"kind": BotReplyKind.HANDOFF_NOTICE, "confidence": None, "sources": []})
    extra = {"offline": True} if offline else {}
    add_system_event(conversation, SystemEvent.HANDOFF_REQUESTED, f"Bot stepped aside — {REASON_LABEL[reason]}", now, reason=reason, **extra)
    conversation["handoff"] = build_handoff_packet(conversation, decision, trigger_message=trigger_message, now=now, packet_id=next_id("hof"))
    if offline:
        conversation["handoff"]["offline"] = {"backAt": team.get("backAt"), "agentsOnline": team.get("agentsOnline", 0)}
    conversation["status"] = Status.HANDOFF_PENDING


def leave_contact(conversation: dict, email: str, now: int) -> None:
    """The customer's email for the reply, in case they've left the chat when an agent answers."""
    assert_status(conversation, (Status.HANDOFF_PENDING, Status.AGENT_ACTIVE), "leave an email")
    conversation["contact"] = {"email": email, "at": now}
    add_system_event(conversation, SystemEvent.CONTACT_LEFT, f"Customer left an email for the reply: {email}", now)


PRIORITY_RANK = {Priority.NORMAL: 0, Priority.HIGH: 1, Priority.URGENT: 2}
WAITING_ACK = "Thanks — I’ve added that to your request, so the team will see it as soon as they join. Add anything else that might help."


def note_while_waiting(conversation: dict, message: dict, sentiment: float, now: int) -> None:
    """A customer message while the handoff waits. The bot stays quiet — they asked for a person — but the
    brief the agent will read stays current, and new urgency moves the case up the queue (never down).
    The customer is told once that their messages reach the team, not after every message."""
    handoff, insights = conversation["handoff"], conversation["insights"]
    added = [*handoff.get("addedWhileWaiting", []), {"id": message["id"], "text": message["text"], "at": now}]
    handoff.update(
        addedWhileWaiting=added,
        entities=insights["entities"],
        sentiment={"current": sentiment, "label": sentiment_label(sentiment), "trend": insights["sentiment"]["trend"]},
    )
    sensitive = next((s for s in conversation_signals(message["text"], sentiment) if s["reason"] == HandoffReason.SENSITIVE_TOPIC), None)
    priority = compute_priority(HandoffReason.SENSITIVE_TOPIC if sensitive else handoff["reason"], sentiment, conversation["customer"]["tier"])
    if PRIORITY_RANK[priority] > PRIORITY_RANK[handoff["priority"]]:
        why = sensitive["detail"] if sensitive else f"Sentiment fell to {sentiment:.2f} while waiting."
        handoff.update(priority=priority, escalated={"from": handoff["priority"], "to": priority, "why": why, "at": now})
        add_system_event(conversation, SystemEvent.PRIORITY_RAISED, f"Priority raised to {priority} — {why}", now, priority=str(priority))
    if len(added) == 1:
        add_bot_message(conversation, WAITING_ACK, now, {"kind": BotReplyKind.SMALL_TALK, "confidence": None, "sources": []})


def last_open_question(conversation: dict) -> str | None:
    added = (conversation.get("handoff") or {}).get("addedWhileWaiting") or []
    if added:  # what the customer said most recently, while waiting, is what the agent should answer first
        return added[-1]["text"]
    open_questions = (conversation.get("handoff") or {}).get("openQuestions") or []
    if open_questions:
        return open_questions[-1]
    return next((m["text"] for m in reversed(conversation["messages"]) if m["sender"] == Sender.CUSTOMER), None)


def accept_handoff(conversation: dict, agent: dict, now: int) -> None:
    assert_status(conversation, (Status.HANDOFF_PENDING,), "accept a handoff")
    conversation["status"] = Status.AGENT_ACTIVE
    conversation["assignee"] = {"id": agent["id"], "name": agent["name"]}
    conversation["handoff"].update(status=HandoffStatus.ACCEPTED, acceptedAt=now, acceptedBy=conversation["assignee"])
    add_system_event(
        conversation, SystemEvent.AGENT_JOINED, f"{agent['name']} joined with the bot’s handoff context", now, agentId=agent["id"], agentName=agent["name"]
    )


def take_over(conversation: dict, agent: dict, now: int) -> None:
    assert_status(conversation, (Status.BOT_ACTIVE,), "take over")
    primary = {"reason": HandoffReason.AGENT_INITIATED, "detail": f"{agent['name']} took over from the live bot queue."}
    decision = {"primary": primary, "signals": [primary]}
    conversation["handoff"] = build_handoff_packet(conversation, decision, trigger_message=None, now=now, packet_id=next_id("hof"))
    conversation.update(status=Status.HANDOFF_PENDING, botTurn=None)  # a bot reply still being written is dropped
    add_system_event(conversation, SystemEvent.AGENT_TOOK_OVER, f"{agent['name']} took over from the bot", now, agentId=agent["id"])
    accept_handoff(conversation, agent, now)


def return_to_bot(conversation: dict, agent: dict, now: int) -> None:
    assert_status(conversation, (Status.AGENT_ACTIVE,), "return to the bot")
    conversation["handoffHistory"].append({**conversation["handoff"], "status": HandoffStatus.RETURNED, "returnedAt": now})
    conversation.update(handoff=None, assignee=None, copilot=None, status=Status.BOT_ACTIVE)
    conversation["insights"]["failedAttempts"] = 0
    add_system_event(conversation, SystemEvent.RETURNED_TO_BOT, f"{agent['name']} handed the conversation back to the bot", now)
    add_bot_message(
        conversation,
        "Thanks for your patience! I’m here if there’s anything else you need.",
        now,
        {"kind": BotReplyKind.SMALL_TALK, "confidence": None, "sources": []},
    )


def post_agent_message(conversation: dict, agent: dict, text: str, now: int) -> None:
    assert_status(conversation, (Status.AGENT_ACTIVE,), "send an agent reply")
    if (conversation["assignee"] or {}).get("id") != agent["id"]:
        raise ApiError(403, "This conversation is assigned to another agent.")
    add_message(conversation, {"sender": Sender.AGENT, "text": text, "createdAt": now, "author": {"id": agent["id"], "name": agent["name"]}})
    conversation["copilot"] = None


OPEN = (Status.BOT_ACTIVE, Status.HANDOFF_PENDING, Status.AGENT_ACTIVE)


def close_conversation(conversation: dict, reason: ClosedReason, now: int, actor: dict | None = None) -> None:
    """End the session for good. A handoff still waiting is marked abandoned, not left in the queue."""
    assert_status(conversation, OPEN, "close the conversation")
    if conversation["status"] == Status.HANDOFF_PENDING and conversation["handoff"]:
        conversation["handoff"]["status"] = HandoffStatus.ABANDONED
    conversation.update(status=Status.RESOLVED, copilot=None, botTurn=None, closedReason=reason, closedAt=now)
    note = CLOSED_NOTE[reason].format(actor=actor["name"] if actor else "the bot", minutes=round(settings.session_idle_minutes))
    add_system_event(conversation, SystemEvent.RESOLVED, note, now, closedReason=reason)


def resolve_conversation(conversation: dict, actor: dict | None, now: int) -> None:
    assert_status(conversation, (Status.BOT_ACTIVE, Status.AGENT_ACTIVE), "resolve")
    close_conversation(conversation, ClosedReason.RESOLVED, now, actor)
