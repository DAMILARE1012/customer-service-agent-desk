"""Storage interface for the three user tables (customers, agents, admins), conversations and settings.

Keycloak owns identity — passwords, roles, sessions. These tables hold what the app needs about each
person (a customer's tier, an agent's capacity) and link to Keycloak through `keycloakId` (the token's
`sub`). Rows are created on a person's first sign-in; seeded demo profiles are claimed by verified email.

Two implementations: PostgresRepository (DATABASE_URL set) and MemoryRepository (tests, quick runs).
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

Kind = Literal["customer", "agent", "admin"]
PREFIX: dict[Kind, str] = {"customer": "cus", "agent": "agt", "admin": "adm"}


@dataclass(frozen=True)
class Identity:
    """What a verified access token says about a person."""

    sub: str
    name: str
    email: str | None
    email_verified: bool


def new_id(kind: Kind) -> str:
    return f"{PREFIX[kind]}_{uuid.uuid4().hex[:10]}"


def new_person(kind: Kind, identity: Identity, person_id: str | None = None) -> dict:
    """Defaults for someone signing in for the first time."""
    base = {"id": person_id or new_id(kind), "keycloakId": identity.sub, "name": identity.name, "email": identity.email}
    if kind == "customer":
        return {**base, "tier": "standard", "location": "", "customerSince": date.today().isoformat(),
                "lifetimeValue": 0.0, "orderCount": 0, "previousConversations": 0}  # fmt: skip
    if kind == "agent":
        return {**base, "capacity": 3, "active": True}
    return base


class Repository(ABC):
    async def start(self) -> None:  # noqa: B027 — optional hook
        """Open connections and create tables."""

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
    async def update_agent(self, agent_id: str, *, capacity: int | None = None, active: bool | None = None) -> dict | None: ...

    # ── Conversations (one JSON document each; status/assignee/customer columns for queries) ──
    @abstractmethod
    async def load_conversations(self) -> list[dict]: ...

    @abstractmethod
    async def save_conversation(self, conversation: dict) -> None: ...

    # ── Settings (runtime handoff policy) ──
    @abstractmethod
    async def get_setting(self, key: str) -> dict | None:
        """{"value", "updatedAt", "updatedBy"} or None."""

    @abstractmethod
    async def set_setting(self, key: str, value: dict, updated_by: str) -> dict: ...


class MemoryRepository(Repository):
    """Everything in dictionaries; lost when the process exits."""

    def __init__(self) -> None:
        self.people: dict[Kind, dict[str, dict]] = {"customer": {}, "agent": {}, "admin": {}}
        self.conversations: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}

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

    async def update_agent(self, agent_id: str, *, capacity: int | None = None, active: bool | None = None) -> dict | None:
        row = self.people["agent"].get(agent_id)
        if row is None:
            return None
        if capacity is not None:
            row["capacity"] = capacity
        if active is not None:
            row["active"] = active
        return dict(row)

    async def load_conversations(self) -> list[dict]:
        return list(self.conversations.values())

    async def save_conversation(self, conversation: dict) -> None:
        self.conversations[conversation["id"]] = conversation

    async def get_setting(self, key: str) -> dict | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: dict, updated_by: str) -> dict:
        self.settings[key] = {"value": value, "updatedAt": datetime.now(UTC).isoformat(), "updatedBy": updated_by}
        return self.settings[key]
