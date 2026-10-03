"""What a customer may see of their own conversation.

The desk's conversation carries the handoff brief, sentiment, entities, retrieval scores and the
copilot draft — all internal. Customers get the transcript, the help articles the bot cited, and
plain-language lifecycle notes ("Alex joined the chat"), never why the bot stepped aside.
"""

from app.conversation.constants import REASON_LABEL, BotReplyKind, ClosedReason, Sender, SystemEvent

# What the customer reads when their chat ends.
CLOSED_TEXT = {
    ClosedReason.RESOLVED: "Conversation closed",
    ClosedReason.ENDED_BY_CUSTOMER: "You ended the chat",
    ClosedReason.INACTIVE: "Chat closed after a period of inactivity",
    ClosedReason.ABANDONED: "Chat closed — we missed you. Start a new chat any time",
}


def _event_text(message: dict) -> str | None:
    event = message.get("event") or {}
    match event.get("type"):
        case SystemEvent.HANDOFF_REQUESTED if event.get("offline"):
            return "Your request is with our team — we’ll reply as soon as someone is in"
        case SystemEvent.HANDOFF_REQUESTED:
            return "Connecting you with a member of our team…"
        case SystemEvent.AGENT_JOINED:
            return f"{(event.get('agentName') or 'A support agent').split()[0]} joined the chat"
        case SystemEvent.RETURNED_TO_BOT:
            return "You’re chatting with the Baton assistant again"
        case SystemEvent.RESOLVED:
            return CLOSED_TEXT.get(event.get("closedReason"), "Conversation closed")
    return None  # e.g. "agent took over" — the customer sees the agent join instead


def _customer_message(message: dict) -> dict | None:
    base = {"id": message["id"], "sender": message["sender"], "createdAt": message["createdAt"]}
    if message["sender"] == Sender.SYSTEM:
        text = _event_text(message)
        return {**base, "text": text} if text else None
    if message["sender"] == Sender.AGENT:
        return {**base, "text": message["text"], "author": {"name": (message.get("author") or {}).get("name", "Support")}}
    meta = message.get("meta") or {}
    # One link per article: the bot often cites several chunks of the same page.
    cited = meta.get("sources") or [] if meta.get("kind") == BotReplyKind.ANSWER else []
    sources = list({s["url"]: {"title": s["title"], "url": s["url"]} for s in cited}.values())
    return {**base, "text": message["text"], "sources": sources}


def _follow_up_ref(conversation: dict) -> dict | None:
    ref = conversation.get("followUpOf")
    return {"id": ref["id"], "subject": ref["subject"]} if ref else None


def customer_view(conversation: dict) -> dict:
    assignee = conversation["assignee"]
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "subject": conversation["subject"],
        "createdAt": conversation["createdAt"],
        "updatedAt": conversation["updatedAt"],
        "closedAt": conversation.get("closedAt"),
        "closedReason": conversation.get("closedReason"),
        "followUpOf": _follow_up_ref(conversation),
        "agent": {"name": assignee["name"].split()[0]} if assignee else None,
        "messages": [m for m in map(_customer_message, conversation["messages"]) if m],
    }


def customer_summary(conversation: dict) -> dict:
    """From a conversation head (list query) or a full conversation."""
    last = conversation.get("lastMessage")
    if last is None and conversation.get("messages"):
        last = next((m for m in reversed(conversation["messages"]) if m["sender"] != Sender.SYSTEM), None)
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "subject": conversation["subject"],
        "createdAt": conversation["createdAt"],
        "updatedAt": conversation["updatedAt"],
        "closedReason": conversation.get("closedReason"),
        "lastMessage": {"sender": last["sender"], "text": last["text"], "createdAt": last["createdAt"]} if last else None,
    }


def session_outcome(conversation: dict) -> dict:
    """One past session in a line or two — for the agent's customer timeline and follow-up links.
    Built from what the session already recorded (handoff brief, bot attempts); no LLM call."""
    packets = [*conversation["handoffHistory"], *([conversation["handoff"]] if conversation["handoff"] else [])]
    last = packets[-1] if packets else None
    answered = sum(1 for a in conversation["insights"]["attempts"] if a["outcome"] == "answered")
    if last:
        summary = last["summary"]
    elif answered:
        summary = f"The assistant answered {answered} question{'s' if answered > 1 else ''} without a handoff."
    else:
        summary = "No question was asked." if not conversation["subject"] else "The assistant didn’t reach an answer."
    return {
        "id": conversation["id"],
        "subject": conversation["subject"],
        "status": conversation["status"],
        "createdAt": conversation["createdAt"],
        "closedAt": conversation.get("closedAt"),
        "closedReason": conversation.get("closedReason"),
        "handoffReason": last["reason"] if last else None,
        "handoffLabel": REASON_LABEL[last["reason"]] if last else None,
        "handledBy": (last.get("acceptedBy") or {}).get("name") if last else None,
        "botAnswers": answered,
        "summary": summary,
        "followUpOf": (conversation.get("followUpOf") or {}).get("id"),
    }
