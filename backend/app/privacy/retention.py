"""Retention: closed conversations older than RETENTION_DAYS lose their text.

What goes: every message's text, the subject, the handoff brief's free text (summary, quotes, open
questions, extracted entities), the copilot draft, the customer snapshot's personal fields, and the
Langfuse traces (which hold the same text). What stays: the shape of the session — when it happened,
how it ended, why it was handed off, what the bot's attempts scored — so reporting keeps working.

Anything worth learning from was extracted by the review pipeline (redacted) long before this runs.
"""

import logging

from app.config import settings
from app.conversation import store
from app.conversation.util import now_ms
from app.db import repository
from app.privacy.langfuse_erasure import delete_traces

log = logging.getLogger(__name__)
REMOVED = "[removed]"
DAY_MS = 86_400_000


def anonymize(conversation: dict, now: int) -> list[str]:
    """Wipe the conversation's text in place; returns its trace ids (to delete from Langfuse)."""
    for message in conversation["messages"]:
        if message["sender"] != "system":
            message["text"] = REMOVED
        if message.get("meta") and message["meta"].get("traceId"):
            message["meta"]["traceId"] = None
    conversation["subject"] = None
    conversation["copilot"] = None
    conversation["contact"] = None
    customer = conversation["customer"]
    conversation["customer"] = {**customer, "name": "Former conversation", "email": "", "location": ""}
    insights = conversation["insights"]
    insights["entities"] = []
    for attempt in insights["attempts"]:
        attempt["question"] = REMOVED
    for packet in [*conversation["handoffHistory"], *([conversation["handoff"]] if conversation["handoff"] else [])]:
        packet.update(summary=REMOVED, entities=[], openQuestions=[], triggerMessage=None)
        for attempt in packet.get("botAttempts") or []:
            attempt["question"] = REMOVED
    if conversation.get("followUpOf"):
        conversation["followUpOf"]["summary"] = REMOVED
        conversation["followUpOf"]["subject"] = None
    traces, conversation["traceIds"] = conversation.get("traceIds") or [], []
    conversation["anonymizedAt"] = now
    conversation["_rewriteMessages"] = True  # tells Postgres to rewrite the stored messages
    return traces


async def apply_retention(now: int | None = None, batch: int = 200) -> dict:
    """Anonymise every conversation past the retention period (in batches)."""
    if settings.retention_days <= 0:
        return {"anonymized": 0, "tracesDeleted": 0}
    now = now or now_ms()
    ids = await repository().expired_conversation_ids(now - settings.retention_days * DAY_MS, batch)
    traces: list[str] = []
    for conversation_id in ids:
        async with store.transaction(conversation_id) as conversation:
            if conversation.get("anonymizedAt"):
                continue
            traces += anonymize(conversation, now)
    deleted = await delete_traces(traces)
    if ids:
        log.info("retention: anonymised %s conversation(s), deleted %s trace(s)", len(ids), deleted.get("deleted", 0))
    return {"anonymized": len(ids), "tracesDeleted": deleted.get("deleted", 0), "traceError": deleted.get("error")}
