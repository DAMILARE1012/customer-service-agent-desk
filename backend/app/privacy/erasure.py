"""One-step erasure of a customer (the "right to be forgotten").

Deletes, in order:
  1. the customer row and every conversation of theirs, with its messages, handoffs and events;
  2. their conversations' Langfuse traces (and the judge scores attached to them);
  3. a Keycloak account, for customers from before the widget who still have one (customers now chat
     through the widget and never get one) — via the `baton-api-admin` service account;
  4. links from the review queue to those conversations (the items themselves hold redacted text).

The result is a report of what was removed and anything that couldn't be, recorded in the audit log
without personal data.
"""

import httpx

from app.config import settings
from app.conversation.lifecycle import ApiError
from app.db import repository
from app.privacy.langfuse_erasure import delete_traces


async def _delete_keycloak_user(keycloak_id: str | None) -> dict:
    if not keycloak_id:
        return {"deleted": False, "note": "No sign-in account to delete: customers chat through the widget. Their widget session stopped working at once."}
    if not settings.keycloak_admin_client_secret:
        return {"deleted": False, "note": "KEYCLOAK_ADMIN_CLIENT_SECRET isn't set: delete the account in the Keycloak admin console."}
    base = (settings.keycloak_internal_url or settings.keycloak_url).rstrip("/")
    realm = settings.keycloak_realm
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            token = await http.post(
                f"{base}/realms/{realm}/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": settings.keycloak_admin_client_id,
                      "client_secret": settings.keycloak_admin_client_secret},
            )  # fmt: skip
            token.raise_for_status()
            res = await http.delete(f"{base}/admin/realms/{realm}/users/{keycloak_id}", headers={"Authorization": f"Bearer {token.json()['access_token']}"})
            if res.status_code == 404:
                return {"deleted": True, "note": "The Keycloak account was already gone."}
            res.raise_for_status()
            return {"deleted": True}
    except httpx.HTTPError as error:
        return {"deleted": False, "note": f"Keycloak account not deleted: {error}"}


async def erase_customer(customer_id: str) -> dict:
    repo = repository()
    customer = await repo.get_person("customer", customer_id)
    if customer is None:
        raise ApiError(404, f"Customer {customer_id} not found.")
    removed = await repo.delete_customer(customer_id)
    await repo.forget_conversations_in_review(removed.get("conversationIds", []))
    traces = await delete_traces(removed["traceIds"])
    identity = await _delete_keycloak_user(customer.get("keycloakId"))

    from app import auth  # late import: auth depends on the db layer

    auth.forget_profile("customer", customer_id)
    return {
        "customerId": customer_id,
        "conversations": removed["conversations"],
        "traces": traces,
        "identity": identity,
        "complete": bool(identity["deleted"] or not customer.get("keycloakId")) and "error" not in traces,
    }
