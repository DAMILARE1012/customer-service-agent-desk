"""How a support session ends — one set of rules, applied by a background sweep.

The customer's widget says "here" every 15 s while the page is open (chat panel open or minimised) and
"left" when the page closes. From those signals:

    the customer…                 bot handling            waiting for an agent                with an agent
    ends the chat (button)        ended_by_customer       ended_by_customer                   ended_by_customer
    leaves (page closed)          left, after the grace   abandoned, after the grace —        stays open; the agent sees
                                                          or stays queued if we can reply     "Customer left", replies
                                                          by email (OFFLINE_FOLLOWUP_DAYS)    also go by email
    disappears (no sign of life   left                    abandoned after                     (the desk shows them as
      for CUSTOMER_GONE_SECONDS)                          SESSION_ABANDON_MINUTES — same      gone)
                                                          email rule
    comes back in the grace       nothing changes         nothing changes                     the agent sees "Customer is back"
    is here but quiet             "still there?" once,    stays queued                        inactive after
                                  inactive after                                              SESSION_IDLE_MINUTES with no
                                  SESSION_IDLE_MINUTES                                        message from anyone

The grace (CUSTOMER_LEFT_GRACE_SECONDS) covers moving to another page of the site or a reload: the widget
there resumes the same session and says "here" again. Right after the API starts nobody has sent a heartbeat
yet, so presence is counted from startup.

Candidates come from one query; each is re-checked inside its locked transaction, so two processes
sweeping at the same time can't act on a session twice.
"""

import logging

from app.config import settings
from app.conversation import engine, lifecycle, store
from app.conversation.constants import ClosedReason, Sender, Status
from app.conversation.offline import reply_email
from app.conversation.util import now_ms

log = logging.getLogger(__name__)
_STARTED_AT = now_ms()


def _last_customer_message(conversation: dict) -> int:
    if "messages" not in conversation:  # a head from a list query
        return conversation.get("lastCustomerMessageAt") or conversation["createdAt"]
    return max((m["createdAt"] for m in conversation["messages"] if m["sender"] == Sender.CUSTOMER), default=conversation["createdAt"])


def _last_sign_of_life(conversation: dict, started_at: int) -> int:
    return max(conversation.get("customerSeenAt") or 0, _last_customer_message(conversation), started_at)


def _left_for(conversation: dict, now: int) -> float | None:
    """Milliseconds since the widget said the page closed, or None if it didn't (or they came back)."""
    left = conversation.get("customerLeftAt")
    return now - left if left else None


def due_for_closing(conversation: dict, now: int, started_at: int = _STARTED_AT) -> ClosedReason | None:
    grace_ms = settings.customer_left_grace_seconds * 1000
    silent_ms = now - _last_sign_of_life(conversation, started_at)
    left_ms = _left_for(conversation, now)
    left = left_ms is not None and left_ms >= grace_ms
    match conversation["status"]:
        case Status.BOT_ACTIVE:
            if left or silent_ms >= settings.customer_gone_seconds * 1000:
                return ClosedReason.LEFT
            if now - _last_customer_message(conversation) >= settings.session_idle_minutes * 60_000:
                return ClosedReason.INACTIVE
        case Status.HANDOFF_PENDING:
            if reply_email(conversation):  # we can answer by email: keep it queued for the team, up to a limit
                return ClosedReason.ABANDONED if silent_ms >= settings.offline_followup_days * 86_400_000 else None
            if left or silent_ms >= settings.session_abandon_minutes * 60_000:
                return ClosedReason.ABANDONED
        case Status.AGENT_ACTIVE:
            if now - conversation["updatedAt"] >= settings.session_idle_minutes * 60_000:
                return ClosedReason.INACTIVE
    return None


def due_for_nudge(conversation: dict, now: int, started_at: int = _STARTED_AT) -> bool:
    """A quiet customer still on the page gets one "still there?" before the bot closes the chat."""
    if conversation["status"] != Status.BOT_ACTIVE or settings.session_nudge_minutes <= 0:
        return False
    if (conversation.get("insights") or {}).get("idleNudgeAt"):
        return False
    quiet_ms = now - _last_customer_message(conversation)
    return quiet_ms >= (settings.session_idle_minutes - settings.session_nudge_minutes) * 60_000


async def sweep(now: int | None = None, started_at: int = _STARTED_AT) -> list[dict]:
    """Close every session that's due and nudge the quiet ones; returns the ones closed."""
    now = now or now_ms()
    closed, nudged = [], 0
    for candidate in await store.heads(open_only=True, limit=10_000):
        if due_for_closing(candidate, now, started_at) is None and not due_for_nudge(candidate, now, started_at):
            continue
        async with store.transaction(candidate["id"]) as conversation:  # it may have moved on meanwhile
            reason = due_for_closing(conversation, now, started_at)
            if reason is not None:
                engine.close_conversation(conversation, reason, now)
                closed.append(conversation)
            elif due_for_nudge(conversation, now, started_at):
                lifecycle.idle_nudge(conversation, now)
                nudged += 1
    if closed:
        log.info("closed %s session(s): %s", len(closed), ", ".join(f"{c['id']} ({c['closedReason']})" for c in closed))
    if nudged:
        log.info("asked %s quiet customer(s) whether they're still there", nudged)
    return closed
