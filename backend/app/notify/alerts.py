"""Telling people who aren't looking at the chat.

Agents — the desk already alerts whoever has it open (sound, browser notification, tab title). This
background job is the escalation for everyone else: a handoff that has waited ALERT_AFTER_SECONDS, or
that arrived while nobody was available, is sent once by email to ALERT_EMAILS (default: every active
agent) and to ALERT_WEBHOOK_URL. Emailing every handoff would teach people to ignore the emails.

Customers — when an agent replies and the customer has left the chat, the reply goes to the email they
left (or the one their website vouched for), so leaving never means losing the answer.
"""

import logging

from app import team
from app.config import settings
from app.conversation import store
from app.conversation.constants import REASON_LABEL, Status
from app.conversation.util import now_ms, truncate
from app.db import repository
from app.notify import mail, webhook

log = logging.getLogger(__name__)


async def _recipients() -> list[str]:
    if settings.alert_emails.strip():
        return [e.strip() for e in settings.alert_emails.split(",") if e.strip()]
    return [a["email"] for a in await repository().list_people("agent") if a.get("active") and a.get("email")]


def _alert_text(conversation: dict, waited_s: float, offline: bool) -> tuple[str, str]:
    handoff, customer = conversation["handoff"], conversation["customer"]
    why = REASON_LABEL.get(handoff["reason"], handoff["reason"])
    priority = str(handoff["priority"]).capitalize()
    question = (handoff.get("triggerMessage") or {}).get("text") or conversation.get("subject") or ""
    lead = "New request while the team is away" if offline else f"Waiting {round(waited_s / 60) or 1} min for an agent"
    subject = f"[Baton] {lead}: {customer['name']} ({priority} · {why})"
    body = (
        f"{lead}.\n\n"
        f"Customer: {customer['name']}\nPriority: {priority}\nWhy the bot stepped aside: {why}\n"
        f"They said: “{truncate(question, 300)}”\n"
        + (f"Reply by email to: {team.reply_email(conversation)}\n" if offline and team.reply_email(conversation) else "")
        + f"\nOpen the desk: {settings.baton_web_url.rstrip('/')}/desk\n"
    )
    return subject, body


async def escalate_waiting_handoffs() -> int:
    """Alert once per handoff that has waited too long or arrived while nobody was available."""
    now = now_ms()
    sent = 0
    for head in await store.heads(status=Status.HANDOFF_PENDING, limit=500):
        handoff = head.get("handoff") or {}
        if handoff.get("alertedAt"):
            continue
        waited_s = (now - handoff["requestedAt"]) / 1000
        offline = bool(handoff.get("offline"))
        if not offline and waited_s < settings.alert_after_seconds:
            continue
        async with store.transaction(head["id"]) as conversation:  # claim it, so other processes don't alert too
            current = conversation.get("handoff") or {}
            if conversation["status"] != Status.HANDOFF_PENDING or current.get("alertedAt"):
                continue
            current["alertedAt"] = now
        subject, body = _alert_text(conversation, waited_s, offline)
        await mail.send(await _recipients(), subject, body, kind="agent_alert")
        await webhook.post(f"{subject}\n{settings.baton_web_url.rstrip('/')}/desk", kind="agent_alert")
        sent += 1
    if sent:
        log.info("sent %s handoff alert(s)", sent)
    return sent


async def email_reply_if_away(conversation: dict, agent_name: str, text: str) -> bool:
    """After an agent's reply: if the customer isn't in the chat any more, send the reply by email."""
    present = now_ms() - (conversation.get("customerSeenAt") or 0) < settings.agent_presence_seconds * 1000
    email = team.reply_email(conversation)
    if present or not email:
        return False
    first = agent_name.split()[0]
    subject = f"Re: {conversation.get('subject') or 'your support request'}"
    body = (
        f"Hi {conversation['customer']['name'].split()[0]},\n\n"
        f"{first} from our support team replied to your message:\n\n{text}\n\n"
        "To carry on, open the chat on our website — the whole conversation is there.\n"
    )
    return await mail.send(email, subject, body, kind="customer_reply")
