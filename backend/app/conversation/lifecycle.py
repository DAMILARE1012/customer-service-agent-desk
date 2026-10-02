"""Synchronous state transitions shared by every bot implementation.

Pure functions over the conversation dict (wire format), so they're trivial to test. The async,
LLM-backed parts (bot turns, copilot drafts) live in engine.py and bot.py.
"""

from app.conversation.constants import (
    HANDOFF_NOTICE,
    REASON_LABEL,
    BotReplyKind,
    HandoffReason,
    HandoffStatus,
    Sender,
    Status,
    SystemEvent,
)
from app.conversation.packet import build_handoff_packet
from app.conversation.signals import extract_entities, merge_entities, score_sentiment
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


def create_conversation(customer: dict, now: int) -> dict:
    return {
        "id": next_id("conv"),
        "customer": customer,
        "status": Status.BOT_ACTIVE,
        "assignee": None,
        "subject": None,
        "createdAt": now,
        "updatedAt": now,
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
    reason = decision["primary"]["reason"]
    add_bot_message(conversation, HANDOFF_NOTICE[reason], now, {"kind": BotReplyKind.HANDOFF_NOTICE, "confidence": None, "sources": []})
    add_system_event(conversation, SystemEvent.HANDOFF_REQUESTED, f"Bot stepped aside — {REASON_LABEL[reason]}", now, reason=reason)
    conversation["handoff"] = build_handoff_packet(conversation, decision, trigger_message=trigger_message, now=now, packet_id=next_id("hof"))
    conversation["status"] = Status.HANDOFF_PENDING


def last_open_question(conversation: dict) -> str | None:
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
    conversation["status"] = Status.HANDOFF_PENDING
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


def resolve_conversation(conversation: dict, actor: dict | None, now: int) -> None:
    assert_status(conversation, (Status.BOT_ACTIVE, Status.AGENT_ACTIVE), "resolve")
    conversation.update(status=Status.RESOLVED, copilot=None)
    add_system_event(conversation, SystemEvent.RESOLVED, f"Resolved by {actor['name'] if actor else 'the bot'}", now)
