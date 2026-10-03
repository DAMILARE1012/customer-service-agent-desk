"""Plain-text email over SMTP, sent from a worker thread so a slow mail server never holds up a request."""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.observability.metrics import label, notifications

log = logging.getLogger(__name__)


def _send(to: list[str], subject: str, body: str, reply_to: str | None) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


async def send(to: list[str] | str, subject: str, body: str, *, kind: str, reply_to: str | None = None) -> bool:
    """Send one email; never raises. `kind` labels the metric (customer_reply, agent_alert…)."""
    recipients = [to] if isinstance(to, str) else [r for r in to if r]
    if not recipients:
        return False
    if not settings.smtp_host:
        log.info("email not sent (SMTP_HOST is empty) — %s to %s: %s", kind, recipients, subject)
        notifications.labels(**label(channel="email", kind=kind, outcome="disabled")).inc()
        return False
    try:
        await asyncio.to_thread(_send, recipients, subject, body, reply_to)
    except (OSError, smtplib.SMTPException) as error:
        log.warning("email %s to %s failed: %s", kind, recipients, error)
        notifications.labels(**label(channel="email", kind=kind, outcome="failed")).inc()
        return False
    notifications.labels(**label(channel="email", kind=kind, outcome="sent")).inc()
    return True
