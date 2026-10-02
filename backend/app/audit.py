"""Audit log: who opened which customer's data, and every admin change.

Actions recorded:
    conversation.view          a staff member opened a transcript (desk, admin or the timeline drawer)
    customer.timeline.view     a staff member opened a customer's history
    customer.erase             a customer's data was deleted (counts only — no personal data)
    agent.update · policy.update · policy.reset
    review.publish · review.approve · review.reject · review.run · knowledge.reindex

The desk polls the open conversation every few seconds; a repeated view by the same person is
recorded at most once every VIEW_DEDUPE_MINUTES.
"""

import time

from app.db import repository

VIEW_DEDUPE_MINUTES = 10
_recent_views: dict[tuple[str, str, str], float] = {}


def actor(person: dict, role: str) -> dict:
    """The audit identity of a staff member: their Keycloak id (stable across tables) and name."""
    return {"actorId": person.get("keycloakId") or person.get("sub") or person.get("id"), "actorName": person.get("name"), "actorRole": role}


async def record(who: dict, action: str, *, conversation_id: str | None = None, customer_id: str | None = None, detail: dict | None = None) -> None:
    if action.endswith(".view"):
        key = (str(who.get("actorId")), action, conversation_id or customer_id or "")
        now = time.monotonic()
        if now - _recent_views.get(key, -1e9) < VIEW_DEDUPE_MINUTES * 60:
            return
        _recent_views[key] = now
    await repository().add_audit({**who, "action": action, "conversationId": conversation_id, "customerId": customer_id, "detail": detail or {}})
