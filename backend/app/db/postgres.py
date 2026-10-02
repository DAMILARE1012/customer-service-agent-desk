"""PostgreSQL storage. Queries run on a small psycopg connection pool in worker threads (psycopg's
async mode needs a selector event loop, which uvicorn on Windows doesn't use); each is a few
milliseconds, so this costs nothing noticeable.
"""

import asyncio
from datetime import date

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.db.repository import Identity, Kind, Repository, new_person

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id                      text PRIMARY KEY,
    keycloak_id             text UNIQUE,
    email                   text UNIQUE,
    name                    text NOT NULL,
    tier                    text NOT NULL DEFAULT 'standard' CHECK (tier IN ('standard', 'plus', 'enterprise')),
    location                text NOT NULL DEFAULT '',
    customer_since          date NOT NULL DEFAULT current_date,
    lifetime_value          numeric(12, 2) NOT NULL DEFAULT 0,
    order_count             integer NOT NULL DEFAULT 0,
    previous_conversations  integer NOT NULL DEFAULT 0,
    created_at              timestamptz NOT NULL DEFAULT now(),
    last_seen_at            timestamptz
);

CREATE TABLE IF NOT EXISTS agents (
    id            text PRIMARY KEY,
    keycloak_id   text UNIQUE,
    email         text UNIQUE,
    name          text NOT NULL,
    capacity      integer NOT NULL DEFAULT 3 CHECK (capacity BETWEEN 1 AND 20),
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz
);

CREATE TABLE IF NOT EXISTS admins (
    id            text PRIMARY KEY,
    keycloak_id   text UNIQUE,
    email         text UNIQUE,
    name          text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz
);

CREATE TABLE IF NOT EXISTS conversations (
    id           text PRIMARY KEY,
    customer_id  text NOT NULL REFERENCES customers (id),
    status       text NOT NULL,
    assignee_id  text,
    created_at   bigint NOT NULL,
    updated_at   bigint NOT NULL,
    doc          jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_customer_idx ON conversations (customer_id);
CREATE INDEX IF NOT EXISTS conversations_status_idx ON conversations (status);

CREATE TABLE IF NOT EXISTS settings (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text
);
"""

TABLE: dict[Kind, str] = {"customer": "customers", "agent": "agents", "admin": "admins"}
# Wire (camelCase) ↔ column (snake_case), per table.
COLUMNS: dict[Kind, dict[str, str]] = {
    "customer": {"id": "id", "keycloakId": "keycloak_id", "email": "email", "name": "name", "tier": "tier", "location": "location",
                 "customerSince": "customer_since", "lifetimeValue": "lifetime_value", "orderCount": "order_count",
                 "previousConversations": "previous_conversations", "lastSeenAt": "last_seen_at"},
    "agent": {"id": "id", "keycloakId": "keycloak_id", "email": "email", "name": "name", "capacity": "capacity", "active": "active",
              "lastSeenAt": "last_seen_at"},
    "admin": {"id": "id", "keycloakId": "keycloak_id", "email": "email", "name": "name", "lastSeenAt": "last_seen_at"},
}  # fmt: skip


def _to_db(profile: dict) -> list:
    """Column values for a wire-format profile (ISO date strings become dates)."""
    return [date.fromisoformat(v) if k == "customerSince" and isinstance(v, str) else v for k, v in profile.items()]


def _to_wire(kind: Kind, row: dict | None) -> dict | None:
    if row is None:
        return None
    out = {wire: row[column] for wire, column in COLUMNS[kind].items()}
    for key, value in out.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    if kind == "customer":
        out["lifetimeValue"] = float(out["lifetimeValue"])
    return out


class PostgresRepository(Repository):
    def __init__(self, url: str) -> None:
        self.pool = ConnectionPool(
            url, min_size=1, max_size=8, open=False, kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 5}
        )

    async def _run(self, fn):
        def work():
            with self.pool.connection() as conn:
                return fn(conn)

        return await asyncio.to_thread(work)

    async def start(self) -> None:
        await asyncio.to_thread(self.pool.open, wait=True, timeout=15)
        await self._run(lambda conn: conn.execute(SCHEMA))

    async def close(self) -> None:
        await asyncio.to_thread(self.pool.close)

    # ── People ──

    async def upsert_person(self, kind: Kind, identity: Identity) -> dict:
        table, cols = TABLE[kind], COLUMNS[kind]

        def work(conn):
            with conn.transaction():
                row = conn.execute(f"SELECT * FROM {table} WHERE keycloak_id = %s FOR UPDATE", (identity.sub,)).fetchone()
                if row is None and identity.email and identity.email_verified:
                    # A seeded profile (e.g. imported from a CRM) is claimed by its verified email.
                    row = conn.execute(f"SELECT * FROM {table} WHERE email = %s AND keycloak_id IS NULL FOR UPDATE", (identity.email,)).fetchone()
                if row is None:
                    fresh = new_person(kind, identity)
                    names = [cols[k] for k in fresh]
                    conn.execute(
                        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})",
                        _to_db(fresh),
                    )
                    row_id = fresh["id"]
                else:
                    row_id = row["id"]
                return conn.execute(
                    f"""UPDATE {table} SET keycloak_id = %s, name = COALESCE(NULLIF(%s, ''), name),
                        email = COALESCE(%s, email), last_seen_at = now() WHERE id = %s RETURNING *""",
                    (identity.sub, identity.name, identity.email, row_id),
                ).fetchone()

        try:
            return _to_wire(kind, await self._run(work))
        except UniqueViolation:
            # Another process created or claimed the row between our reads; it exists now — read it.
            return _to_wire(kind, await self._run(work))

    async def seed_person(self, kind: Kind, profile: dict) -> None:
        cols = COLUMNS[kind]
        names = [cols[k] for k in profile]
        sql = (
            f"INSERT INTO {TABLE[kind]} ({', '.join(names)}) SELECT {', '.join(['%s'] * len(names))} "
            f"WHERE NOT EXISTS (SELECT 1 FROM {TABLE[kind]} WHERE id = %s OR email = %s)"
        )
        await self._run(lambda conn: conn.execute(sql, [*_to_db(profile), profile["id"], profile.get("email")]))

    async def get_person(self, kind: Kind, person_id: str) -> dict | None:
        row = await self._run(lambda conn: conn.execute(f"SELECT * FROM {TABLE[kind]} WHERE id = %s", (person_id,)).fetchone())
        return _to_wire(kind, row)

    async def list_people(self, kind: Kind) -> list[dict]:
        rows = await self._run(lambda conn: conn.execute(f"SELECT * FROM {TABLE[kind]} ORDER BY name").fetchall())
        return [_to_wire(kind, r) for r in rows]

    async def update_agent(self, agent_id: str, *, capacity: int | None = None, active: bool | None = None) -> dict | None:
        row = await self._run(
            lambda conn: conn.execute(
                "UPDATE agents SET capacity = COALESCE(%s, capacity), active = COALESCE(%s, active) WHERE id = %s RETURNING *",
                (capacity, active, agent_id),
            ).fetchone()
        )
        return _to_wire("agent", row)

    # ── Conversations ──

    async def load_conversations(self) -> list[dict]:
        rows = await self._run(lambda conn: conn.execute("SELECT doc FROM conversations ORDER BY created_at").fetchall())
        return [r["doc"] for r in rows]

    async def save_conversation(self, conversation: dict) -> None:
        c = conversation
        await self._run(
            lambda conn: conn.execute(
                """INSERT INTO conversations (id, customer_id, status, assignee_id, created_at, updated_at, doc)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, assignee_id = EXCLUDED.assignee_id,
                       updated_at = EXCLUDED.updated_at, doc = EXCLUDED.doc""",
                (c["id"], c["customer"]["id"], str(c["status"]), (c["assignee"] or {}).get("id"), c["createdAt"], c["updatedAt"], Jsonb(c)),
            )
        )

    # ── Settings ──

    async def get_setting(self, key: str) -> dict | None:
        row = await self._run(lambda conn: conn.execute("SELECT * FROM settings WHERE key = %s", (key,)).fetchone())
        return {"value": row["value"], "updatedAt": row["updated_at"].isoformat(), "updatedBy": row["updated_by"]} if row else None

    async def set_setting(self, key: str, value: dict, updated_by: str) -> dict:
        row = await self._run(
            lambda conn: conn.execute(
                """INSERT INTO settings (key, value, updated_at, updated_by) VALUES (%s, %s, now(), %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by
                   RETURNING *""",
                (key, Jsonb(value), updated_by),
            ).fetchone()
        )
        return {"value": row["value"], "updatedAt": row["updated_at"].isoformat(), "updatedBy": row["updated_by"]}
