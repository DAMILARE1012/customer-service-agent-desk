"""Support sessions end on their own: a background sweep closes conversations nobody is using.

    bot handling     no customer message for SESSION_IDLE_MINUTES          → inactive
    with an agent    no message from anyone for SESSION_IDLE_MINUTES       → inactive
    waiting          customer's chat not open for SESSION_ABANDON_MINUTES   → abandoned
                     (with an email to reply to: OFFLINE_FOLLOWUP_DAYS instead — the team answers by email)

"Customer present" comes from their chat window polling the conversation (customerSeenAt), so a
customer patiently waiting in the queue is never dropped — only one who has left. Right after the
API starts nobody has polled yet, so presence is counted from startup.

Candidates come from one query; each is re-checked inside its locked transaction, so two processes
sweeping at the same time can't close a session twice.
"""

import logging

from app.config import settings
from app.conversation import engine, store
from app.conversation.constants import ClosedReason, Sender, Status
from app.conversation.offline import reply_email
from app.conversation.util import now_ms

log = logging.getLogger(__name__)
_STARTED_AT = now_ms()


def _last_customer_message(conversation: dict) -> int:
    if "messages" not in conversation:  # a head from a list query
        return conversation.get("lastCustomerMessageAt") or conversation["createdAt"]
    return max((m["createdAt"] for m in conversation["messages"] if m["sender"] == Sender.CUSTOMER), default=conversation["createdAt"])


def due_for_closing(conversation: dict, now: int, started_at: int = _STARTED_AT) -> ClosedReason | None:
    idle_ms = settings.session_idle_minutes * 60_000
    match conversation["status"]:
        case Status.BOT_ACTIVE:
            return ClosedReason.INACTIVE if now - _last_customer_message(conversation) >= idle_ms else None
        case Status.AGENT_ACTIVE:
            return ClosedReason.INACTIVE if now - conversation["updatedAt"] >= idle_ms else None
        case Status.HANDOFF_PENDING:
            seen = max(conversation.get("customerSeenAt") or 0, _last_customer_message(conversation), started_at)
            if reply_email(conversation):  # we can answer by email: keep it queued for the team, up to a limit
                return ClosedReason.ABANDONED if now - seen >= settings.offline_followup_days * 86_400_000 else None
            return ClosedReason.ABANDONED if now - seen >= settings.session_abandon_minutes * 60_000 else None
    return None


async def sweep(now: int | None = None, started_at: int = _STARTED_AT) -> list[dict]:
    """Close every session that's due; returns the ones closed."""
    now = now or now_ms()
    closed = []
    for candidate in await store.heads(open_only=True, limit=10_000):
        if due_for_closing(candidate, now, started_at) is None:
            continue
        async with store.transaction(candidate["id"]) as conversation:
            reason = due_for_closing(conversation, now, started_at)  # it may have moved on meanwhile
            if reason is None:
                continue
            engine.close_conversation(conversation, reason, now)
            closed.append(conversation)
    if closed:
        log.info("closed %s idle session(s): %s", len(closed), ", ".join(f"{c['id']} ({c['closedReason']})" for c in closed))
    return closed
