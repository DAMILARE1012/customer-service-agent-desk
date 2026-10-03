"""Conversations, read straight from storage on every request (no per-process copy), so any number of
API processes can serve them. Every change goes through `transaction(id)`, which locks the
conversation until the change is saved. LLM calls happen between transactions, never inside one
(see engine.py).
"""

from contextlib import asynccontextmanager

from app.config import settings
from app.conversation.lifecycle import ApiError
from app.conversation.offline import reply_email
from app.conversation.util import now_ms
from app.db import repository
from app.db.repository import AlreadyOpen, ConversationFilter

__all__ = ["AlreadyOpen", "ConversationFilter", "create", "transaction", "own_transaction", "get", "get_own", "heads",
           "open_conversation_of", "active_count", "mark_seen", "to_summary", "desk_stats"]  # fmt: skip


def _missing(conversation_id: str) -> ApiError:
    return ApiError(404, f"Conversation {conversation_id} not found.")


async def create(conversation: dict) -> dict:
    """Raises AlreadyOpen if the customer already has a live session."""
    await repository().create_conversation(conversation)
    return conversation


@asynccontextmanager
async def transaction(conversation_id: str, *, agent: str | None = None):
    """The conversation, locked for this operation and saved when the block ends (rolled back on error).
    With `agent`, that agent is locked too and conversation["_agentLoad"] is their active-chat count."""
    async with repository().transaction(conversation_id, agent=agent) as conversation:
        if conversation is None:
            raise _missing(conversation_id)
        yield conversation


@asynccontextmanager
async def own_transaction(conversation_id: str, customer: dict):
    """A customer's own conversation. Someone else's answers 404, not 403: existence isn't revealed."""
    async with transaction(conversation_id) as conversation:
        if conversation["customer"]["id"] != customer["id"]:
            raise _missing(conversation_id)
        yield conversation


async def get(conversation_id: str) -> dict:
    conversation = await repository().get_conversation(conversation_id)
    if conversation is None:
        raise _missing(conversation_id)
    return conversation


async def get_own(conversation_id: str, customer: dict) -> dict:
    conversation = await repository().get_conversation(conversation_id)
    if conversation is None or conversation["customer"]["id"] != customer["id"]:
        raise _missing(conversation_id)
    return conversation


async def heads(*, with_handoffs: bool = False, **filters) -> list[dict]:
    """Conversations without transcripts, newest activity first (see ConversationFilter)."""
    return await repository().list_conversations(ConversationFilter(**filters), with_handoffs=with_handoffs)


async def open_conversation_of(customer_id: str) -> dict | None:
    """The customer's live session, if any — a customer has at most one at a time."""
    found = await heads(customer_id=customer_id, open_only=True, limit=1)
    return found[0] if found else None


async def active_count(agent_id: str) -> int:
    return await repository().count_active(agent_id)


async def mark_seen(conversation_id: str) -> None:
    """Presence: the customer's chat window is open (throttled writes)."""
    await repository().mark_customer_seen(conversation_id, now_ms())


def to_summary(conversation: dict) -> dict:
    """Lightweight list shape for the queue; the full transcript is only sent for the open conversation."""
    handoff = conversation["handoff"]
    customer = conversation["customer"]
    last = conversation.get("lastMessage")
    if last is None and conversation.get("messages"):
        message = next((m for m in reversed(conversation["messages"]) if m["sender"] != "system"), None)
        last = {"sender": message["sender"], "text": message["text"], "createdAt": message["createdAt"]} if message else None
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "assignee": conversation["assignee"],
        "subject": conversation["subject"],
        "createdAt": conversation["createdAt"],
        "updatedAt": conversation["updatedAt"],
        "customer": {"id": customer["id"], "name": customer["name"], "tier": customer["tier"]},
        "lastMessage": last,
        "handoff": {
            **{k: handoff[k] for k in ("reason", "priority", "requestedAt", "acceptedAt")},
            "addedWhileWaiting": len(handoff.get("addedWhileWaiting") or []),
            "offline": bool(handoff.get("offline")),
            "replyByEmail": bool(reply_email(conversation)),
        }
        if handoff
        else None,
        "sentiment": conversation["insights"]["sentiment"]["current"],
        "lastConfidence": conversation["insights"]["lastConfidence"],
        "closedReason": conversation.get("closedReason"),
        "followUpOf": (conversation.get("followUpOf") or {}).get("id"),
        "customerSeenAt": conversation.get("customerSeenAt"),
        "customerLeftAt": conversation.get("customerLeftAt"),
    }


def desk_stats() -> dict:
    """Live desk numbers for the Prometheus gauges (synchronous: called during the scrape)."""
    try:
        return repository().desk_stats(now_ms(), settings.sla_breach_ms)
    except RuntimeError:  # storage not started yet
        return {"byStatus": {}, "oldestHandoffWaitSeconds": 0.0, "slaBreaches": 0}
