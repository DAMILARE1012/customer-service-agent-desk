"""Conversations: an in-process working set, written through to the repository after every change.

All conversations are loaded at startup and served from memory, so the desk's polling never touches the
database; each operation persists the one conversation it changed. That design assumes a single API
process — run more than one and they'd each hold their own copy.
"""

import asyncio
from collections import defaultdict

from app.config import settings
from app.conversation.constants import Sender, Status
from app.conversation.lifecycle import ApiError
from app.conversation.util import now_ms
from app.db import repository

_conversations: dict[str, dict] = {}
# Bot turns await the LLM, so two messages for one conversation could interleave. Each conversation
# gets a lock: operations on it run one at a time, in arrival order.
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def load() -> int:
    _conversations.clear()
    for conversation in await repository().load_conversations():
        _conversations[conversation["id"]] = conversation
    return len(_conversations)


async def persist(conversation: dict) -> dict:
    _conversations[conversation["id"]] = conversation
    await repository().save_conversation(conversation)
    return conversation


def all_conversations() -> list[dict]:
    return list(_conversations.values())


def conversations_of(customer_id: str) -> list[dict]:
    return sorted((c for c in _conversations.values() if c["customer"]["id"] == customer_id), key=lambda c: c["updatedAt"], reverse=True)


def find_conversation(conversation_id: str) -> dict:
    conversation = _conversations.get(conversation_id)
    if not conversation:
        raise ApiError(404, f"Conversation {conversation_id} not found.")
    return conversation


def find_own_conversation(conversation_id: str, customer: dict) -> dict:
    """A customer's own conversation. Someone else's answers 404, not 403: existence isn't revealed."""
    conversation = _conversations.get(conversation_id)
    if not conversation or conversation["customer"]["id"] != customer["id"]:
        raise ApiError(404, f"Conversation {conversation_id} not found.")
    return conversation


def active_count(agent_id: str) -> int:
    return sum(1 for c in _conversations.values() if c["status"] == Status.AGENT_ACTIVE and (c["assignee"] or {}).get("id") == agent_id)


def lock_for(conversation_id: str) -> asyncio.Lock:
    return _locks[conversation_id]


def to_summary(conversation: dict) -> dict:
    """Lightweight list shape for the queue; the full transcript is only sent for the open conversation."""
    last = next((m for m in reversed(conversation["messages"]) if m["sender"] != Sender.SYSTEM), None)
    handoff = conversation["handoff"]
    customer = conversation["customer"]
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "assignee": conversation["assignee"],
        "subject": conversation["subject"],
        "createdAt": conversation["createdAt"],
        "updatedAt": conversation["updatedAt"],
        "customer": {"id": customer["id"], "name": customer["name"], "tier": customer["tier"]},
        "lastMessage": {"sender": last["sender"], "text": last["text"], "createdAt": last["createdAt"]} if last else None,
        "handoff": {k: handoff[k] for k in ("reason", "priority", "requestedAt", "acceptedAt")} if handoff else None,
        "sentiment": conversation["insights"]["sentiment"]["current"],
        "lastConfidence": conversation["insights"]["lastConfidence"],
    }


def desk_stats() -> dict:
    """Live desk numbers for the Prometheus gauges."""
    now = now_ms()
    by_status = {status.value: 0 for status in Status}
    oldest, breaches = 0.0, 0
    for conversation in _conversations.values():
        by_status[conversation["status"]] += 1
        if conversation["status"] == Status.HANDOFF_PENDING:
            waited = now - conversation["handoff"]["requestedAt"]
            oldest = max(oldest, waited / 1000)
            breaches += waited >= settings.sla_breach_ms
    return {"byStatus": by_status, "oldestHandoffWaitSeconds": oldest, "slaBreaches": breaches}
