"""What a customer may see of their own conversation.

The desk's conversation carries the handoff brief, sentiment, entities, retrieval scores and the
copilot draft — all internal. Customers get the transcript, the help articles the bot cited, and
plain-language lifecycle notes ("Alex joined the chat"), never why the bot stepped aside.
"""

from app.conversation.constants import BotReplyKind, Sender, SystemEvent


def _event_text(message: dict) -> str | None:
    event = message.get("event") or {}
    match event.get("type"):
        case SystemEvent.HANDOFF_REQUESTED:
            return "Connecting you with a member of our team…"
        case SystemEvent.AGENT_JOINED:
            return f"{(event.get('agentName') or 'A support agent').split()[0]} joined the chat"
        case SystemEvent.RETURNED_TO_BOT:
            return "You’re chatting with the Baton assistant again"
        case SystemEvent.RESOLVED:
            return "Conversation closed — reply any time to reopen it"
        case SystemEvent.REOPENED:
            return "Conversation reopened"
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


def customer_view(conversation: dict) -> dict:
    assignee = conversation["assignee"]
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "subject": conversation["subject"],
        "createdAt": conversation["createdAt"],
        "updatedAt": conversation["updatedAt"],
        "agent": {"name": assignee["name"].split()[0]} if assignee else None,
        "messages": [m for m in map(_customer_message, conversation["messages"]) if m],
    }


def customer_summary(conversation: dict) -> dict:
    last = next((m for m in reversed(conversation["messages"]) if m["sender"] != Sender.SYSTEM), None)
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "subject": conversation["subject"],
        "createdAt": conversation["createdAt"],
        "updatedAt": conversation["updatedAt"],
        "lastMessage": {"sender": last["sender"], "text": last["text"], "createdAt": last["createdAt"]} if last else None,
    }
