"""Storage interface: the three user tables, conversations (with their messages, handoffs and lifecycle
events), settings, the audit log and the review queue.

Keycloak owns identity — passwords, roles, sessions. The user tables hold what the app needs about each
person (a customer's tier, an agent's capacity) and link to Keycloak through `keycloakId` (the token's
`sub`). Rows are created on a person's first sign-in; seeded demo profiles are claimed by verified email.

Conversations are read straight from storage on every request — no process keeps its own copy — and
every change happens inside `transaction(id)`, which locks that conversation (a row lock in Postgres),
so several API processes can serve the same conversations safely.

Two implementations: PostgresRepository (DATABASE_URL set) and MemoryRepository (tests, quick runs).
"""

import asyncio
import contextlib
import copy
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

Kind = Literal["customer", "agent", "admin"]
PREFIX: dict[Kind, str] = {"customer": "cus", "agent": "agt", "admin": "adm"}
OPEN_STATUSES = ("bot_active", "handoff_pending", "agent_active")


class AlreadyOpen(Exception):
    """The customer already has a live conversation (at most one at a time)."""


@dataclass(frozen=True)
class Identity:
    """What a verified access token says about a person."""

    sub: str
    name: str
    email: str | None
    email_verified: bool


@dataclass(frozen=True)
class ConversationFilter:
    status: str | None = None
    open_only: bool = False
    customer_id: str | None = None
    assignee_id: str | None = None
    visible_to_agent: str | None = None  # open conversations, plus resolved ones this agent handled
    q: str | None = None  # customer name or subject contains
    limit: int = 500


def new_id(kind: Kind) -> str:
    return f"{PREFIX[kind]}_{uuid.uuid4().hex[:10]}"


def new_person(kind: Kind, identity: Identity, person_id: str | None = None) -> dict:
    """Defaults for someone signing in for the first time."""
    base = {"id": person_id or new_id(kind), "keycloakId": identity.sub, "name": identity.name, "email": identity.email}
    if kind == "customer":
        return {**base, "tier": "standard", "location": "", "customerSince": date.today().isoformat(),
                "lifetimeValue": 0.0, "orderCount": 0, "previousConversations": 0}  # fmt: skip
    if kind == "agent":
        return {**base, "capacity": 3, "active": True, "available": True}
    return base


def new_visitor() -> dict:
    row = new_person("customer", Identity(sub="", name="", email=None, email_verified=False))
    return {**row, "keycloakId": None, "name": f"Visitor {row['id'][-4:].upper()}", "isVisitor": True, "externalId": None}


# Conversation fields added after the first release; older stored conversations get them on read.
PRIORITY_RANK = {"urgent": 2, "high": 1, "normal": 0}  # the desk takes higher priority first, then longest waiting

CONVERSATION_DEFAULTS = {
    "closedAt": None, "closedReason": None, "followUpOf": None, "customerSeenAt": None,
    "traceIds": [], "reviewedAt": None, "anonymizedAt": None, "botTurn": None, "contact": None,
}  # fmt: skip


def with_defaults(conversation: dict) -> dict:
    for key, value in CONVERSATION_DEFAULTS.items():
        conversation.setdefault(key, copy.copy(value))
    if conversation["status"] == "resolved" and not conversation["closedReason"]:
        conversation["closedReason"] = "resolved"
    return conversation


def head(conversation: dict, *, with_handoffs: bool) -> dict:
    """A conversation without its transcript: what lists, the timeline and the sweeper need."""
    out = {k: v for k, v in conversation.items() if k != "messages"}
    if not with_handoffs:
        out["handoffHistory"] = []
    last = next((m for m in reversed(conversation["messages"]) if m["sender"] != "system"), None)
    out["lastMessage"] = {"sender": last["sender"], "text": last["text"], "createdAt": last["createdAt"]} if last else None
    out["lastCustomerMessageAt"] = max((m["createdAt"] for m in conversation["messages"] if m["sender"] == "customer"), default=None)
    return out


def matches(conversation: dict, f: ConversationFilter) -> bool:
    assignee = (conversation["assignee"] or {}).get("id")
    term = (f.q or "").strip().lower()
    return (
        (f.status is None or conversation["status"] == f.status)
        and (not f.open_only or conversation["status"] in OPEN_STATUSES)
        and (f.customer_id is None or conversation["customer"]["id"] == f.customer_id)
        and (f.assignee_id is None or assignee == f.assignee_id)
        and (f.visible_to_agent is None or conversation["status"] in OPEN_STATUSES or assignee == f.visible_to_agent)
        and (not term or term in conversation["customer"]["name"].lower() or term in (conversation["subject"] or "").lower())
    )


class Repository(ABC):
    async def start(self) -> None:  # noqa: B027 — optional hook
        """Open connections and bring the schema up to date."""

    async def close(self) -> None:  # noqa: B027 — optional hook
        """Release connections."""

    # ── People ──
    @abstractmethod
    async def upsert_person(self, kind: Kind, identity: Identity) -> dict:
        """The person's row, created on first sign-in. Refreshes name, email and last seen."""

    @abstractmethod
    async def seed_person(self, kind: Kind, profile: dict) -> None:
        """Insert a profile (no Keycloak link yet) unless one with that id or email exists."""

    @abstractmethod
    async def get_person(self, kind: Kind, person_id: str) -> dict | None: ...

    @abstractmethod
    async def list_people(self, kind: Kind) -> list[dict]: ...

    @abstractmethod
    async def update_agent(
        self, agent_id: str, *, capacity: int | None = None, active: bool | None = None, available: bool | None = None
    ) -> dict | None: ...

    @abstractmethod
    async def available_agents(self, seen_within_s: int) -> list[dict]:
        """Agents who can take a chat now: active, set to Online, and seen (desk open) recently."""

    @abstractmethod
    async def handoffs_ahead(self, conversation_id: str) -> int:
        """Waiting handoffs the desk would take before this one (higher priority, then waiting longer)."""

    @abstractmethod
    async def typical_handoff_wait_ms(self, since: int) -> float | None:
        """Median time to an agent accepting, over handoffs requested since then (None with too few)."""

    @abstractmethod
    async def create_visitor(self) -> dict:
        """A new anonymous customer (someone who opened the widget without being signed in to your site)."""

    @abstractmethod
    async def upsert_external_customer(self, external_id: str, name: str | None, email: str | None) -> dict:
        """The customer your website vouches for (its user id): found by that id, else a seeded profile
        claimed by email the first time, else created."""

    @abstractmethod
    async def delete_customer(self, customer_id: str) -> dict:
        """Delete the customer row and everything hanging off it (conversations, messages, handoffs,
        events). Returns {"conversations": n, "conversationIds": [...], "traceIds": [...]}."""

    # ── Conversations ──
    @abstractmethod
    async def create_conversation(self, conversation: dict) -> None:
        """Raises AlreadyOpen if the customer already has a live conversation."""

    @abstractmethod
    def transaction(self, conversation_id: str, *, agent: str | None = None):
        """`async with repo.transaction(id) as conversation:` — the full conversation, locked against
        concurrent changes (in any process) until the block ends, then saved. Yields None if missing.

        With `agent`, that agent is locked too (before the conversation, always in that order), and
        conversation["_agentLoad"] holds their active chats counted under the lock — so two accepts
        can't both see a free slot. The key is dropped before saving."""

    @abstractmethod
    async def get_conversation(self, conversation_id: str) -> dict | None: ...

    @abstractmethod
    async def list_conversations(self, f: ConversationFilter, *, with_handoffs: bool = False) -> list[dict]:
        """Conversation heads (no transcript), most recently updated first."""

    @abstractmethod
    async def mark_customer_seen(self, conversation_id: str, now: int) -> None: ...

    @abstractmethod
    async def count_active(self, agent_id: str) -> int: ...

    @abstractmethod
    def desk_stats(self, now: int, breach_ms: float) -> dict:
        """Synchronous (called from the Prometheus scrape): conversations by status, oldest wait, SLA breaches."""

    @abstractmethod
    async def conversations_to_review(self, limit: int) -> list[dict]:
        """Closed, not yet reviewed, not anonymised — full conversations."""

    @abstractmethod
    async def expired_conversation_ids(self, closed_before: int, limit: int) -> list[str]:
        """Closed before the cutoff and not yet anonymised."""

    # ── Settings ──
    @abstractmethod
    async def get_setting(self, key: str) -> dict | None:
        """{"value", "updatedAt", "updatedBy"} or None."""

    @abstractmethod
    async def set_setting(self, key: str, value: dict, updated_by: str) -> dict: ...

    # ── Audit log ──
    @abstractmethod
    async def add_audit(self, entry: dict) -> None: ...

    @abstractmethod
    async def list_audit(self, *, actor_id: str | None = None, conversation_id: str | None = None, action: str | None = None, limit: int = 200) -> list[dict]: ...

    # ── Review queue ──
    @abstractmethod
    async def list_review_items(self, kind: str | None = None, status: str | None = None) -> list[dict]: ...

    @abstractmethod
    async def get_review_item(self, item_id: str) -> dict | None: ...

    @abstractmethod
    async def save_review_item(self, item: dict) -> dict: ...

    @abstractmethod
    async def forget_conversations_in_review(self, conversation_ids: list[str]) -> None:
        """Erasure: drop links from review items to these conversations (the items hold redacted text)."""

    # ── Coordination ──
    @abstractmethod
    def exclusive(self, name: str):
        """`async with repo.exclusive("review") as acquired:` — one runner at a time across processes."""


class MemoryRepository(Repository):
    """Everything in dictionaries; lost when the process exits. Same rules as Postgres, one process."""

    def __init__(self) -> None:
        self.people: dict[Kind, dict[str, dict]] = {"customer": {}, "agent": {}, "admin": {}}
        self.conversations: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.review: dict[str, dict] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ── People ──

    async def upsert_person(self, kind: Kind, identity: Identity) -> dict:
        table = self.people[kind]
        now = datetime.now(UTC).isoformat()
        row = next((p for p in table.values() if p.get("keycloakId") == identity.sub), None)
        if row is None and identity.email and identity.email_verified:
            row = next((p for p in table.values() if not p.get("keycloakId") and p.get("email") == identity.email), None)
        if row is None:
            row = new_person(kind, identity)
            table[row["id"]] = row
        row.update(keycloakId=identity.sub, name=identity.name or row["name"], email=identity.email or row.get("email"), lastSeenAt=now)
        return dict(row)

    async def seed_person(self, kind: Kind, profile: dict) -> None:
        table = self.people[kind]
        if profile["id"] in table or any(p.get("email") == profile.get("email") for p in table.values()):
            return
        table[profile["id"]] = {"keycloakId": None, "lastSeenAt": None, **profile}

    async def get_person(self, kind: Kind, person_id: str) -> dict | None:
        row = self.people[kind].get(person_id)
        return dict(row) if row else None

    async def list_people(self, kind: Kind) -> list[dict]:
        return [dict(p) for p in sorted(self.people[kind].values(), key=lambda p: p["name"])]

    async def update_agent(
        self, agent_id: str, *, capacity: int | None = None, active: bool | None = None, available: bool | None = None
    ) -> dict | None:
        row = self.people["agent"].get(agent_id)
        if row is None:
            return None
        for field, value in (("capacity", capacity), ("active", active), ("available", available)):
            if value is not None:
                row[field] = value
        return dict(row)

    async def available_agents(self, seen_within_s: int) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(seconds=seen_within_s)
        return [
            dict(a) for a in self.people["agent"].values()
            if a.get("active") and a.get("available", True) and a.get("lastSeenAt") and datetime.fromisoformat(a["lastSeenAt"]) >= cutoff
        ]  # fmt: skip

    async def handoffs_ahead(self, conversation_id: str) -> int:
        mine = self.conversations.get(conversation_id)
        if not mine or mine["status"] != "handoff_pending" or not mine["handoff"]:
            return 0
        key = lambda c: (-PRIORITY_RANK.get(c["handoff"]["priority"], 0), c["handoff"]["requestedAt"])  # noqa: E731
        waiting = [c for c in self.conversations.values() if c["status"] == "handoff_pending" and c["handoff"]]
        return sum(1 for c in waiting if key(c) < key(mine))

    async def typical_handoff_wait_ms(self, since: int) -> float | None:
        waits = sorted(
            p["acceptedAt"] - p["requestedAt"]
            for c in self.conversations.values()
            for p in [*c["handoffHistory"], *([c["handoff"]] if c["handoff"] else [])]
            if p.get("acceptedAt") and p["requestedAt"] >= since
        )
        return float(waits[len(waits) // 2]) if len(waits) >= 3 else None

    async def create_visitor(self) -> dict:
        row = new_visitor()
        self.people["customer"][row["id"]] = row
        return dict(row)

    async def upsert_external_customer(self, external_id: str, name: str | None, email: str | None) -> dict:
        table = self.people["customer"]
        row = next((p for p in table.values() if p.get("externalId") == external_id), None)
        if row is None and email:
            row = next((p for p in table.values() if p.get("email") == email and not p.get("externalId") and not p.get("isVisitor")), None)
        if row is None:
            row = {**new_person("customer", Identity(sub="", name=name or "Customer", email=email, email_verified=True)), "keycloakId": None}
            table[row["id"]] = row
        row.update(externalId=external_id, isVisitor=False, name=name or row["name"], email=email or row.get("email"),
                   lastSeenAt=datetime.now(UTC).isoformat())  # fmt: skip
        return dict(row)

    async def delete_customer(self, customer_id: str) -> dict:
        mine = [c for c in self.conversations.values() if c["customer"]["id"] == customer_id]
        for c in mine:
            del self.conversations[c["id"]]
        self.people["customer"].pop(customer_id, None)
        return {"conversations": len(mine), "conversationIds": [c["id"] for c in mine],
                "traceIds": sorted({t for c in mine for t in c.get("traceIds", [])})}  # fmt: skip

    # ── Conversations ──

    async def create_conversation(self, conversation: dict) -> None:
        customer_id = conversation["customer"]["id"]
        if any(c["customer"]["id"] == customer_id and c["status"] in OPEN_STATUSES for c in self.conversations.values()):
            raise AlreadyOpen(customer_id)
        self.conversations[conversation["id"]] = copy.deepcopy(with_defaults(conversation))

    @asynccontextmanager
    async def transaction(self, conversation_id: str, *, agent: str | None = None):
        agent_lock = self._locks[f"agent:{agent}"] if agent else contextlib.nullcontext()
        async with agent_lock, self._locks[conversation_id]:
            stored = self.conversations.get(conversation_id)
            if stored is None:
                yield None
                return
            working = copy.deepcopy(stored)
            if agent:
                working["_agentLoad"] = await self.count_active(agent)
            yield working  # an exception discards the changes, like a rollback
            working.pop("_rewriteMessages", None)
            working.pop("_agentLoad", None)
            if conversation_id in self.conversations:
                self.conversations[conversation_id] = working

    async def get_conversation(self, conversation_id: str) -> dict | None:
        stored = self.conversations.get(conversation_id)
        return copy.deepcopy(stored) if stored else None

    async def list_conversations(self, f: ConversationFilter, *, with_handoffs: bool = False) -> list[dict]:
        rows = [head(copy.deepcopy(c), with_handoffs=with_handoffs) for c in self.conversations.values() if matches(c, f)]
        return sorted(rows, key=lambda c: c["updatedAt"], reverse=True)[: f.limit]

    async def mark_customer_seen(self, conversation_id: str, now: int) -> None:
        stored = self.conversations.get(conversation_id)
        if stored and stored["status"] in OPEN_STATUSES:
            stored["customerSeenAt"] = now

    async def count_active(self, agent_id: str) -> int:
        return sum(1 for c in self.conversations.values() if c["status"] == "agent_active" and (c["assignee"] or {}).get("id") == agent_id)

    def desk_stats(self, now: int, breach_ms: float) -> dict:
        by_status = {s: 0 for s in (*OPEN_STATUSES, "resolved")}
        oldest, breaches = 0.0, 0
        for c in self.conversations.values():
            by_status[c["status"]] += 1
            if c["status"] == "handoff_pending" and c["handoff"]:
                waited = now - c["handoff"]["requestedAt"]
                oldest = max(oldest, waited / 1000)
                breaches += waited >= breach_ms
        return {"byStatus": by_status, "oldestHandoffWaitSeconds": oldest, "slaBreaches": breaches}

    async def conversations_to_review(self, limit: int) -> list[dict]:
        rows = [c for c in self.conversations.values() if c["status"] == "resolved" and not c.get("reviewedAt") and not c.get("anonymizedAt")]
        return [copy.deepcopy(c) for c in sorted(rows, key=lambda c: c["closedAt"] or 0)[:limit]]

    async def expired_conversation_ids(self, closed_before: int, limit: int) -> list[str]:
        rows = [c for c in self.conversations.values() if c["status"] == "resolved" and not c.get("anonymizedAt") and (c["closedAt"] or c["updatedAt"]) < closed_before]
        return [c["id"] for c in rows][:limit]

    # ── Settings ──

    async def get_setting(self, key: str) -> dict | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: dict, updated_by: str) -> dict:
        self.settings[key] = {"value": value, "updatedAt": datetime.now(UTC).isoformat(), "updatedBy": updated_by}
        return self.settings[key]

    # ── Audit log ──

    async def add_audit(self, entry: dict) -> None:
        self.audit.append({"id": len(self.audit) + 1, "at": datetime.now(UTC).isoformat(), **entry})

    async def list_audit(self, *, actor_id=None, conversation_id=None, action=None, limit=200) -> list[dict]:
        rows = [
            e for e in reversed(self.audit)
            if (actor_id is None or e.get("actorId") == actor_id)
            and (conversation_id is None or e.get("conversationId") == conversation_id)
            and (action is None or e["action"] == action)
        ]  # fmt: skip
        return rows[:limit]

    # ── Review queue ──

    async def list_review_items(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        rows = [i for i in self.review.values() if (kind is None or i["kind"] == kind) and (status is None or i["status"] == status)]
        return [copy.deepcopy(i) for i in sorted(rows, key=lambda i: (-i["count"], i["createdAt"]))]

    async def get_review_item(self, item_id: str) -> dict | None:
        item = self.review.get(item_id)
        return copy.deepcopy(item) if item else None

    async def save_review_item(self, item: dict) -> dict:
        self.review[item["id"]] = copy.deepcopy(item)
        return copy.deepcopy(item)

    async def forget_conversations_in_review(self, conversation_ids: list[str]) -> None:
        gone = set(conversation_ids)
        for item in self.review.values():
            item["conversationIds"] = [c for c in item["conversationIds"] if c not in gone]

    # ── Coordination ──

    @asynccontextmanager
    async def exclusive(self, name: str):
        lock = self._locks[f"job:{name}"]
        if lock.locked():
            yield False
            return
        async with lock:
            yield True
