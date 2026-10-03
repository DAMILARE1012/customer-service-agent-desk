"""Post an alert to a chat channel. The {"text": …} body works with Slack and Mattermost incoming webhooks,
and with Microsoft Teams workflows that accept a text field."""

import logging

import httpx

from app.config import settings
from app.observability.metrics import label, notifications

log = logging.getLogger(__name__)


async def post(text: str, *, kind: str) -> bool:
    if not settings.alert_webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(settings.alert_webhook_url, json={"text": text})
            response.raise_for_status()
    except httpx.HTTPError as error:
        log.warning("webhook %s failed: %s", kind, error)
        notifications.labels(**label(channel="webhook", kind=kind, outcome="failed")).inc()
        return False
    notifications.labels(**label(channel="webhook", kind=kind, outcome="sent")).inc()
    return True
