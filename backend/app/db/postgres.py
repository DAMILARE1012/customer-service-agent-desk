"""PostgreSQL storage.

Queries run on a psycopg connection pool in worker threads (psycopg's async mode needs a selector event
loop, which uvicorn on Windows doesn't use). A conversation transaction holds one connection with
`SELECT … FOR UPDATE` on the conversation's row for the whole operation — including the LLM call of a bot
turn — so two processes can never interleave changes to the same conversation.

The schema is versioned (schema_version table); migrations run at startup under an advisory lock, so
several processes starting together migrate once.
"""

import asyncio
import functools
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.db.repository import (
    OPEN_STATUSES,
    AlreadyOpen,
    ConversationFilter,
    Identity,
    Kind,
    Repository,
    new_person,
    new_visitor,
    with_defaults,
)

# ── Schema ───────────────────────────────────────────────────────────────────

V1_USERS_AND_DOCUMENTS = """
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

# v2: one row per conversation, message, handoff and lifecycle event (was one JSON document each).
V2_NORMALISED = """
ALTER TABLE conversations RENAME TO conversations_v1;
ALTER TABLE conversations_v1 RENAME CONSTRAINT conversations_pkey TO conversations_v1_pkey;
ALTER INDEX conversations_customer_idx RENAME TO conversations_v1_customer_idx;
ALTER INDEX conversations_status_idx RENAME TO conversations_v1_status_idx;

CREATE TABLE conversations (
    id                text PRIMARY KEY,
    customer_id       text NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    status            text NOT NULL CHECK (status IN ('bot_active', 'handoff_pending', 'agent_active', 'resolved')),
    assignee_id       text,
    assignee          jsonb,
    subject           text,
    customer          jsonb NOT NULL,          -- profile snapshot when the session started
    insights          jsonb NOT NULL,          -- intent, sentiment trend, entities, bot attempts
    copilot           jsonb,
    follow_up_of_id   text,
    follow_up         jsonb,                   -- outcome snapshot of the session this one follows up
    created_at        bigint NOT NULL,
    updated_at        bigint NOT NULL,
    closed_at         bigint,
    closed_reason     text,
    customer_seen_at  bigint,
    trace_ids         text[] NOT NULL DEFAULT '{}',
    reviewed_at       bigint,
    anonymized_at     bigint
);
CREATE INDEX conversations_customer_idx ON conversations (customer_id, updated_at DESC);
CREATE INDEX conversations_status_idx ON conversations (status, updated_at DESC);
CREATE INDEX conversations_assignee_idx ON conversations (assignee_id) WHERE assignee_id IS NOT NULL;
CREATE INDEX conversations_closed_idx ON conversations (closed_at) WHERE status = 'resolved';
-- At most one live session per customer, even with several API processes.
CREATE UNIQUE INDEX conversations_one_open_per_customer ON conversations (customer_id) WHERE status <> 'resolved';

CREATE TABLE messages (
    id               text PRIMARY KEY,
    conversation_id  text NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    seq              integer NOT NULL,
    sender           text NOT NULL CHECK (sender IN ('customer', 'bot', 'agent', 'system')),
    text             text NOT NULL,
    created_at       bigint NOT NULL,
    meta             jsonb,                    -- bot replies: kind, confidence, cited sources, trace id
    event            jsonb,                    -- system messages: the lifecycle event
    author           jsonb,                    -- agent replies: who wrote it
    UNIQUE (conversation_id, seq)
);

CREATE TABLE handoffs (
    id               text PRIMARY KEY,
    conversation_id  text NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    seq              integer NOT NULL,
    current          boolean NOT NULL,
    status           text NOT NULL,
    reason           text NOT NULL,
    priority         text NOT NULL,
    requested_at     bigint NOT NULL,
    accepted_at      bigint,
    accepted_by_id   text,
    packet           jsonb NOT NULL            -- the full handoff brief
);
CREATE INDEX handoffs_conversation_idx ON handoffs (conversation_id, seq);
CREATE INDEX handoffs_reason_idx ON handoffs (reason, requested_at);

CREATE TABLE conversation_events (
    id               bigserial PRIMARY KEY,
    conversation_id  text NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    type             text NOT NULL,
    at               bigint NOT NULL,
    actor_id         text,
    data             jsonb NOT NULL
);
CREATE INDEX conversation_events_conversation_idx ON conversation_events (conversation_id, at);
CREATE INDEX conversation_events_type_idx ON conversation_events (type, at);
"""

# v3: who opened what, and the review queue (knowledge gaps, test questions).
V3_AUDIT_AND_REVIEW = """
CREATE TABLE access_log (
    id               bigserial PRIMARY KEY,
    at               timestamptz NOT NULL DEFAULT now(),
    actor_id         text,
    actor_name       text,
    actor_role       text,
    action           text NOT NULL,
    conversation_id  text,
    customer_id      text,
    detail           jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX access_log_at_idx ON access_log (at DESC);
CREATE INDEX access_log_actor_idx ON access_log (actor_id, at DESC);
CREATE INDEX access_log_conversation_idx ON access_log (conversation_id, at DESC);

CREATE TABLE review_items (
    id                text PRIMARY KEY,
    kind              text NOT NULL CHECK (kind IN ('knowledge_gap', 'test_question')),
    status            text NOT NULL CHECK (status IN ('pending', 'approved', 'published', 'rejected')),
    question          text NOT NULL,           -- redacted
    answer            text NOT NULL DEFAULT '',-- redacted agent answer, or the article body being drafted
    title             text NOT NULL DEFAULT '',
    examples          jsonb NOT NULL DEFAULT '[]',
    agent_answers     jsonb NOT NULL DEFAULT '[]',
    conversation_ids  text[] NOT NULL DEFAULT '{}',
    count             integer NOT NULL DEFAULT 1,
    embedding         real[],
    published_path    text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    reviewed_by       text,
    reviewed_at       timestamptz
);
CREATE INDEX review_items_kind_status_idx ON review_items (kind, status);
"""

# v4: customers come from the chat widget — anonymous visitors, or people your website vouches for.
V4_WIDGET_CUSTOMERS = """
ALTER TABLE customers ADD COLUMN external_id text UNIQUE;          -- your website's user id
ALTER TABLE customers ADD COLUMN is_visitor boolean NOT NULL DEFAULT false;
"""

# v5: a bot turn in progress, so the LLM call runs without holding the conversation locked.
V5_BOT_TURN = """
ALTER TABLE conversations ADD COLUMN bot_turn jsonb;               -- {messageId, startedAt} while the bot answers
"""

# v6: agent availability (the desk's Online/Away switch) and an email the customer left for the reply.
V6_AVAILABILITY = """
ALTER TABLE agents ADD COLUMN available boolean NOT NULL DEFAULT true;
ALTER TABLE conversations ADD COLUMN contact jsonb;                -- {email, at}
"""

# v7: when the widget reported the customer leaving (closed the page), so the chat can end on time.
V7_PRESENCE = """
ALTER TABLE conversations ADD COLUMN customer_left_at bigint;
"""

TABLE: dict[Kind, str] = {"customer": "customers", "agent": "agents", "admin": "admins"}
COLUMNS: dict[Kind, dict[str, str]] = {
    "customer": {"id": "id", "keycloakId": "keycloak_id", "email": "email", "name": "name", "tier": "tier", "location": "location",
                 "customerSince": "customer_since", "lifetimeValue": "lifetime_value", "orderCount": "order_count",
                 "previousConversations": "previous_conversations", "lastSeenAt": "last_seen_at",
                 "externalId": "external_id", "isVisitor": "is_visitor"},
    "agent": {"id": "id", "keycloakId": "keycloak_id", "email": "email", "name": "name", "capacity": "capacity", "active": "active",
              "available": "available", "lastSeenAt": "last_seen_at"},
    "admin": {"id": "id", "keycloakId": "keycloak_id", "email": "email", "name": "name", "lastSeenAt": "last_seen_at"},
}  # fmt: skip

REVIEW_COLUMNS = {
    "id": "id", "kind": "kind", "status": "status", "question": "question", "answer": "answer", "title": "title",
    "examples": "examples", "agentAnswers": "agent_answers", "conversationIds": "conversation_ids", "count": "count",
    "embedding": "embedding", "publishedPath": "published_path", "createdAt": "created_at", "updatedAt": "updated_at",
    "reviewedBy": "reviewed_by", "reviewedAt": "reviewed_at",
}  # fmt: skip
REVIEW_JSON = {"examples", "agentAnswers"}

CONVERSATION_SELECT = """
SELECT c.*, lm.sender AS lm_sender, lm.text AS lm_text, lm.created_at AS lm_at, h.packet AS current_handoff,
       (SELECT max(created_at) FROM messages mc WHERE mc.conversation_id = c.id AND mc.sender = 'customer') AS last_customer_at
FROM conversations c
LEFT JOIN LATERAL (
    SELECT sender, text, created_at FROM messages m
    WHERE m.conversation_id = c.id AND m.sender <> 'system' ORDER BY seq DESC LIMIT 1
) lm ON true
LEFT JOIN handoffs h ON h.conversation_id = c.id AND h.current
"""


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _to_db(profile: dict) -> list:
    """Column values for a wire-format profile (ISO date strings become dates)."""
    return [date.fromisoformat(v) if k == "customerSince" and isinstance(v, str) else v for k, v in profile.items()]


def _person(kind: Kind, row: dict | None) -> dict | None:
    if row is None:
        return None
    out = {wire: _iso(row[column]) for wire, column in COLUMNS[kind].items()}
    if kind == "customer":
        out["lifetimeValue"] = float(out["lifetimeValue"])
    return out


def _head(row: dict) -> dict:
    """A conversations row (with the joined last message / current handoff) in wire format."""
    return with_defaults({
        "id": row["id"],
        "customer": row["customer"],
        "status": row["status"],
        "assignee": row["assignee"],
        "subject": row["subject"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "closedAt": row["closed_at"],
        "closedReason": row["closed_reason"],
        "followUpOf": row["follow_up"],
        "customerSeenAt": row["customer_seen_at"],
        "insights": row["insights"],
        "copilot": row["copilot"],
        "traceIds": list(row["trace_ids"] or []),
        "reviewedAt": row["reviewed_at"],
        "anonymizedAt": row["anonymized_at"],
        "botTurn": row.get("bot_turn"),
        "contact": row.get("contact"),
        "customerLeftAt": row.get("customer_left_at"),
        "handoff": row.get("current_handoff"),
        "handoffHistory": [],
        "lastMessage": {"sender": row["lm_sender"], "text": row["lm_text"], "createdAt": row["lm_at"]} if row.get("lm_sender") else None,
        "lastCustomerMessageAt": row.get("last_customer_at"),
    })  # fmt: skip


def _message(row: dict) -> dict:
    return {"id": row["id"], "sender": row["sender"], "text": row["text"], "createdAt": row["created_at"],
            "meta": row["meta"], "event": row["event"], "author": row["author"]}  # fmt: skip


def _review(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = {wire: _iso(row[column]) for wire, column in REVIEW_COLUMNS.items()}
    out["conversationIds"] = list(out["conversationIds"] or [])
    out["embedding"] = list(out["embedding"]) if out["embedding"] is not None else None
    return out


def _filter_sql(f: ConversationFilter) -> tuple[str, list]:
    where, params = [], []
    if f.status:
        where.append("c.status = %s")
        params.append(f.status)
    if f.open_only:
        where.append("c.status <> 'resolved'")
    if f.customer_id:
        where.append("c.customer_id = %s")
        params.append(f.customer_id)
    if f.assignee_id:
        where.append("c.assignee_id = %s")
        params.append(f.assignee_id)
    if f.visible_to_agent:
        where.append("(c.status <> 'resolved' OR c.assignee_id = %s)")
        params.append(f.visible_to_agent)
    if f.q and f.q.strip():
        where.append("(c.customer->>'name' ILIKE %s OR c.subject ILIKE %s)")
        term = f"%{f.q.strip()}%"
        params += [term, term]
    return (" WHERE " + " AND ".join(where)) if where else "", params


POOL_SIZE = 20
RESERVED_CONNECTIONS = 2  # for synchronous callers outside the async limiter (the Prometheus scrape)


class PostgresRepository(Repository):
    """Database work runs on its own threads, one per connection — never on the default executor, where
    retrieval's CPU work could crowd it out. A request waits for a free connection in the event loop
    (`_slots`) before it takes a thread, so no thread ever sits blocked waiting for a connection: under
    load, requests queue instead of deadlocking."""

    def __init__(self, url: str) -> None:
        self.pool = ConnectionPool(
            url, min_size=2, max_size=POOL_SIZE, open=False, kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 5}
        )
        self._threads = ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="baton-db")
        self._slots: asyncio.Semaphore | None = None

    async def _call(self, fn, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(self._threads, functools.partial(fn, *args, **kwargs))

    @asynccontextmanager
    async def _connection(self):
        if self._slots is None:
            self._slots = asyncio.Semaphore(POOL_SIZE - RESERVED_CONNECTIONS)
        async with self._slots:
            conn = await self._call(self.pool.getconn)
            try:
                yield conn
            finally:
                await self._call(self.pool.putconn, conn)

    async def _run(self, fn):
        async with self._connection() as conn:
            return await self._call(fn, conn)

    async def start(self) -> None:
        await self._call(self.pool.open, wait=True, timeout=15)
        await self._run(self._migrate)

    async def close(self) -> None:
        await self._call(self.pool.close)
        self._threads.shutdown(wait=False)

    # ── Migrations ──

    def _migrate(self, conn) -> None:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(727274)")  # one process migrates; the others wait
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version integer NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            version = conn.execute("SELECT coalesce(max(version), 0) AS v FROM schema_version").fetchone()["v"]
            if version == 0:
                # A fresh database, or one created before versioning (its tables already exist): both
                # end up at v1 here, then migrate forward the same way.
                conn.execute(V1_USERS_AND_DOCUMENTS)
                conn.execute("INSERT INTO schema_version (version) VALUES (1)")
                version = 1
            if version < 2:
                conn.execute(V2_NORMALISED)
                for row in conn.execute("SELECT doc FROM conversations_v1 ORDER BY created_at").fetchall():
                    self._insert_conversation(conn, with_defaults(row["doc"]))
                conn.execute("INSERT INTO schema_version (version) VALUES (2)")
            if version < 3:
                conn.execute(V3_AUDIT_AND_REVIEW)
                conn.execute("INSERT INTO schema_version (version) VALUES (3)")
            if version < 4:
                conn.execute(V4_WIDGET_CUSTOMERS)
                conn.execute("INSERT INTO schema_version (version) VALUES (4)")
            if version < 5:
                conn.execute(V5_BOT_TURN)
                conn.execute("INSERT INTO schema_version (version) VALUES (5)")
            if version < 6:
                conn.execute(V6_AVAILABILITY)
                conn.execute("INSERT INTO schema_version (version) VALUES (6)")
            if version < 7:
                conn.execute(V7_PRESENCE)
                conn.execute("INSERT INTO schema_version (version) VALUES (7)")

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
                    conn.execute(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})", _to_db(fresh))
                    row_id = fresh["id"]
                else:
                    row_id = row["id"]
                return conn.execute(
                    f"""UPDATE {table} SET keycloak_id = %s, name = COALESCE(NULLIF(%s, ''), name),
                        email = COALESCE(%s, email), last_seen_at = now() WHERE id = %s RETURNING *""",
                    (identity.sub, identity.name, identity.email, row_id),
                ).fetchone()

        try:
            return _person(kind, await self._run(work))
        except UniqueViolation:
            # Another process created or claimed the row between our reads; it exists now — read it.
            return _person(kind, await self._run(work))

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
        return _person(kind, row)

    async def list_people(self, kind: Kind) -> list[dict]:
        rows = await self._run(lambda conn: conn.execute(f"SELECT * FROM {TABLE[kind]} ORDER BY name").fetchall())
        return [_person(kind, r) for r in rows]

    async def available_agents(self, seen_within_s: int) -> list[dict]:
        rows = await self._run(
            lambda conn: conn.execute(
                """SELECT * FROM agents WHERE active AND available AND last_seen_at > now() - make_interval(secs => %s)""",
                (seen_within_s,),
            ).fetchall()
        )
        return [_person("agent", r) for r in rows]

    async def handoffs_ahead(self, conversation_id: str) -> int:
        row = await self._run(
            lambda conn: conn.execute(
                """WITH waiting AS (
                       SELECT c.id, CASE h.priority WHEN 'urgent' THEN 2 WHEN 'high' THEN 1 ELSE 0 END AS rank, h.requested_at
                       FROM conversations c JOIN handoffs h ON h.conversation_id = c.id AND h.current
                       WHERE c.status = 'handoff_pending')
                   SELECT count(*) AS n FROM waiting w, waiting me
                   WHERE me.id = %s AND (w.rank > me.rank OR (w.rank = me.rank AND w.requested_at < me.requested_at))""",
                (conversation_id,),
            ).fetchone()
        )
        return row["n"]

    async def typical_handoff_wait_ms(self, since: int) -> float | None:
        row = await self._run(
            lambda conn: conn.execute(
                """SELECT count(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY accepted_at - requested_at) AS median
                   FROM handoffs WHERE accepted_at IS NOT NULL AND requested_at >= %s""",
                (since,),
            ).fetchone()
        )
        return float(row["median"]) if row["n"] >= 3 else None

    async def update_agent(
        self, agent_id: str, *, capacity: int | None = None, active: bool | None = None, available: bool | None = None
    ) -> dict | None:
        row = await self._run(
            lambda conn: conn.execute(
                """UPDATE agents SET capacity = COALESCE(%s, capacity), active = COALESCE(%s, active), available = COALESCE(%s, available)
                   WHERE id = %s RETURNING *""",
                (capacity, active, available, agent_id),
            ).fetchone()
        )
        return _person("agent", row)

    async def create_visitor(self) -> dict:
        row = new_visitor()
        names = [COLUMNS["customer"][k] for k in row if k in COLUMNS["customer"]]
        values = _to_db({k: v for k, v in row.items() if k in COLUMNS["customer"]})
        created = await self._run(
            lambda conn: conn.execute(f"INSERT INTO customers ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))}) RETURNING *", values).fetchone()
        )
        return _person("customer", created)

    async def upsert_external_customer(self, external_id: str, name: str | None, email: str | None) -> dict:
        def work(conn):
            with conn.transaction():
                row = conn.execute("SELECT * FROM customers WHERE external_id = %s FOR UPDATE", (external_id,)).fetchone()
                if row is None and email:
                    row = conn.execute(
                        "SELECT * FROM customers WHERE email = %s AND external_id IS NULL AND NOT is_visitor FOR UPDATE", (email,)
                    ).fetchone()
                if row is None:
                    fresh = new_person("customer", Identity(sub="", name=name or "Customer", email=email, email_verified=True))
                    fresh["keycloakId"] = None
                    names = [COLUMNS["customer"][k] for k in fresh]
                    conn.execute(f"INSERT INTO customers ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})", _to_db(fresh))
                    row_id = fresh["id"]
                else:
                    row_id = row["id"]
                return conn.execute(
                    """UPDATE customers SET external_id = %s, is_visitor = false, name = COALESCE(NULLIF(%s, ''), name),
                           email = COALESCE(%s, email), last_seen_at = now() WHERE id = %s RETURNING *""",
                    (external_id, name, email, row_id),
                ).fetchone()

        try:
            return _person("customer", await self._run(work))
        except UniqueViolation:  # created by a concurrent request a moment ago
            return _person("customer", await self._run(work))

    async def delete_customer(self, customer_id: str) -> dict:
        def work(conn):
            with conn.transaction():
                rows = conn.execute("SELECT id, trace_ids FROM conversations WHERE customer_id = %s", (customer_id,)).fetchall()
                conn.execute("DELETE FROM conversations WHERE customer_id = %s", (customer_id,))  # messages, handoffs, events cascade
                conn.execute("DELETE FROM conversations_v1 WHERE customer_id = %s", (customer_id,))  # pre-migration copies
                conn.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
                return {"conversations": len(rows), "conversationIds": [r["id"] for r in rows],
                        "traceIds": sorted({t for r in rows for t in (r["trace_ids"] or [])})}  # fmt: skip

        return await self._run(work)

    # ── Conversations ──

    def _insert_conversation(self, conn, c: dict) -> None:
        conn.execute(
            """INSERT INTO conversations (id, customer_id, status, assignee_id, assignee, subject, customer, insights, copilot,
                   follow_up_of_id, follow_up, created_at, updated_at, closed_at, closed_reason, customer_seen_at, trace_ids,
                   reviewed_at, anonymized_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (c["id"], c["customer"]["id"], str(c["status"]), (c["assignee"] or {}).get("id"), Jsonb(c["assignee"]), c["subject"],
             Jsonb(c["customer"]), Jsonb(c["insights"]), Jsonb(c["copilot"]), (c["followUpOf"] or {}).get("id"), Jsonb(c["followUpOf"]),
             c["createdAt"], c["updatedAt"], c["closedAt"], c["closedReason"], c["customerSeenAt"], c["traceIds"],
             c["reviewedAt"], c["anonymizedAt"]),
        )  # fmt: skip
        # bot_turn is left NULL: a new conversation has no turn in progress (_save writes it from then on).
        self._write_children(conn, c, messages_from=0)

    def _write_children(self, conn, c: dict, messages_from: int) -> None:
        for seq, m in enumerate(c["messages"][messages_from:], start=messages_from):
            conn.execute(
                "INSERT INTO messages (id, conversation_id, seq, sender, text, created_at, meta, event, author) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (m["id"], c["id"], seq, str(m["sender"]), m["text"], m["createdAt"], Jsonb(m.get("meta")), Jsonb(m.get("event")), Jsonb(m.get("author"))),
            )
            if m["sender"] == "system" and m.get("event"):
                event = m["event"]
                conn.execute(
                    "INSERT INTO conversation_events (conversation_id, type, at, actor_id, data) VALUES (%s, %s, %s, %s, %s)",
                    (c["id"], str(event["type"]), m["createdAt"], event.get("agentId"), Jsonb(event)),
                )
        packets = [*c["handoffHistory"], *([c["handoff"]] if c["handoff"] else [])]
        for seq, p in enumerate(packets):
            conn.execute(
                """INSERT INTO handoffs (id, conversation_id, seq, current, status, reason, priority, requested_at, accepted_at, accepted_by_id, packet)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET seq = EXCLUDED.seq, current = EXCLUDED.current, status = EXCLUDED.status, priority = EXCLUDED.priority,
                       accepted_at = EXCLUDED.accepted_at, accepted_by_id = EXCLUDED.accepted_by_id, packet = EXCLUDED.packet""",
                (p["id"], c["id"], seq, p is c["handoff"], str(p["status"]), str(p["reason"]), str(p["priority"]), p["requestedAt"],
                 p.get("acceptedAt"), (p.get("acceptedBy") or {}).get("id"), Jsonb(p)),
            )  # fmt: skip

    def _load(self, conn, conversation_id: str, *, lock: bool) -> dict | None:
        if lock and conn.execute("SELECT 1 FROM conversations WHERE id = %s FOR UPDATE", (conversation_id,)).fetchone() is None:
            return None
        row = conn.execute(f"{CONVERSATION_SELECT} WHERE c.id = %s", (conversation_id,)).fetchone()
        if row is None:
            return None
        conversation = _head(row)
        conversation["messages"] = [_message(m) for m in conn.execute("SELECT * FROM messages WHERE conversation_id = %s ORDER BY seq", (conversation_id,)).fetchall()]
        conversation["handoffHistory"] = [
            h["packet"] for h in conn.execute("SELECT packet FROM handoffs WHERE conversation_id = %s AND NOT current ORDER BY seq", (conversation_id,)).fetchall()
        ]
        for key in ("lastMessage", "lastCustomerMessageAt"):
            conversation.pop(key, None)
        return conversation

    async def create_conversation(self, conversation: dict) -> None:
        def work(conn):
            with conn.transaction():
                self._insert_conversation(conn, with_defaults(conversation))

        try:
            await self._run(work)
        except UniqueViolation as error:
            if "conversations_one_open_per_customer" in str(error):
                raise AlreadyOpen(conversation["customer"]["id"]) from error
            raise

    @asynccontextmanager
    async def transaction(self, conversation_id: str, *, agent: str | None = None):
        async with self._connection() as conn:
            conn.autocommit = False
            try:
                load = await self._call(self._lock_agent, conn, agent) if agent else None  # agent first, then the row
                conversation = await self._call(self._load, conn, conversation_id, lock=True)
                if conversation is not None and agent:
                    conversation["_agentLoad"] = load
                loaded_messages = len(conversation["messages"]) if conversation else 0
                try:
                    yield conversation
                except BaseException:
                    await self._call(conn.rollback)
                    raise
                if conversation is not None:
                    await self._call(self._save, conn, conversation, loaded_messages)
                await self._call(conn.commit)
            finally:
                if conn.info.transaction_status != 0:  # still in a transaction (e.g. the save failed): roll back
                    await self._call(conn.rollback)
                conn.autocommit = True

    @staticmethod
    def _lock_agent(conn, agent_id: str) -> int:
        """Lock an agent until this transaction ends (in every process), then count their active chats."""
        key = int.from_bytes(hashlib.sha256(f"agent:{agent_id}".encode()).digest()[:8], "big", signed=True)
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        sql = "SELECT count(*) AS n FROM conversations WHERE status = 'agent_active' AND assignee_id = %s"
        return conn.execute(sql, (agent_id,)).fetchone()["n"]

    def _save(self, conn, c: dict, loaded_messages: int) -> None:
        conn.execute(
            """UPDATE conversations SET status = %s, assignee_id = %s, assignee = %s, subject = %s, customer = %s, insights = %s,
                   copilot = %s, follow_up_of_id = %s, follow_up = %s, updated_at = %s, closed_at = %s, closed_reason = %s,
                   customer_seen_at = GREATEST(customer_seen_at, %s), trace_ids = %s, reviewed_at = %s, anonymized_at = %s,
                   bot_turn = %s, contact = %s, customer_left_at = %s
               WHERE id = %s""",
            (str(c["status"]), (c["assignee"] or {}).get("id"), Jsonb(c["assignee"]), c["subject"], Jsonb(c["customer"]), Jsonb(c["insights"]),
             Jsonb(c["copilot"]), (c["followUpOf"] or {}).get("id"), Jsonb(c["followUpOf"]), c["updatedAt"], c["closedAt"], c["closedReason"],
             c["customerSeenAt"], c["traceIds"], c["reviewedAt"], c["anonymizedAt"], Jsonb(c.get("botTurn")), Jsonb(c.get("contact")), c.get("customerLeftAt"),
             c["id"]),
        )  # fmt: skip
        if c.get("_rewriteMessages"):  # anonymisation rewrites the transcript in place
            c.pop("_rewriteMessages")
            for seq, m in enumerate(c["messages"]):
                conn.execute("UPDATE messages SET text = %s, meta = %s, author = %s WHERE conversation_id = %s AND seq = %s",
                             (m["text"], Jsonb(m.get("meta")), Jsonb(m.get("author")), c["id"], seq))  # fmt: skip
        self._write_children(conn, c, messages_from=loaded_messages)

    async def get_conversation(self, conversation_id: str) -> dict | None:
        return await self._run(lambda conn: self._load(conn, conversation_id, lock=False))

    async def list_conversations(self, f: ConversationFilter, *, with_handoffs: bool = False) -> list[dict]:
        where, params = _filter_sql(f)

        def work(conn):
            rows = conn.execute(f"{CONVERSATION_SELECT}{where} ORDER BY c.updated_at DESC LIMIT %s", [*params, f.limit]).fetchall()
            heads = [_head(r) for r in rows]
            if with_handoffs and heads:
                history: dict[str, list] = {}
                for h in conn.execute(
                    "SELECT conversation_id, packet FROM handoffs WHERE conversation_id = ANY(%s) AND NOT current ORDER BY seq", ([x["id"] for x in heads],)
                ).fetchall():
                    history.setdefault(h["conversation_id"], []).append(h["packet"])
                for x in heads:
                    x["handoffHistory"] = history.get(x["id"], [])
            return heads

        return await self._run(work)

    async def mark_customer_seen(self, conversation_id: str, now: int) -> None:
        # Throttled: one write per 15 s per conversation, however often the chat window polls.
        await self._run(
            lambda conn: conn.execute(
                "UPDATE conversations SET customer_seen_at = %s WHERE id = %s AND status <> 'resolved' AND (customer_seen_at IS NULL OR customer_seen_at < %s)",
                (now, conversation_id, now - 15_000),
            )
        )

    async def touch_customer(self, conversation_id: str, customer_id: str, now: int) -> dict | None:
        row = await self._run(
            lambda conn: conn.execute(
                """UPDATE conversations SET customer_seen_at = GREATEST(COALESCE(customer_seen_at, 0), %s)
                   WHERE id = %s AND customer_id = %s AND status <> 'resolved' RETURNING status, customer_left_at""",
                (now, conversation_id, customer_id),
            ).fetchone()
        )
        return {"status": row["status"], "customerLeftAt": row["customer_left_at"]} if row else None

    async def count_active(self, agent_id: str) -> int:
        row = await self._run(
            lambda conn: conn.execute("SELECT count(*) AS n FROM conversations WHERE status = 'agent_active' AND assignee_id = %s", (agent_id,)).fetchone()
        )
        return row["n"]

    def desk_stats(self, now: int, breach_ms: float) -> dict:
        with self.pool.connection() as conn:
            counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM conversations GROUP BY status").fetchall()}
            waits = conn.execute(
                """SELECT min(h.requested_at) AS oldest, count(*) FILTER (WHERE %s - h.requested_at >= %s) AS breaches
                   FROM handoffs h JOIN conversations c ON c.id = h.conversation_id
                   WHERE h.current AND c.status = 'handoff_pending'""",
                (now, breach_ms),
            ).fetchone()
        by_status = {s: counts.get(s, 0) for s in (*OPEN_STATUSES, "resolved")}
        oldest = (now - waits["oldest"]) / 1000 if waits["oldest"] else 0.0
        return {"byStatus": by_status, "oldestHandoffWaitSeconds": max(0.0, oldest), "slaBreaches": waits["breaches"] or 0}

    async def conversations_to_review(self, limit: int) -> list[dict]:
        def work(conn):
            ids = conn.execute(
                "SELECT id FROM conversations WHERE status = 'resolved' AND reviewed_at IS NULL AND anonymized_at IS NULL ORDER BY closed_at LIMIT %s",
                (limit,),
            ).fetchall()
            return [self._load(conn, r["id"], lock=False) for r in ids]

        return await self._run(work)

    async def expired_conversation_ids(self, closed_before: int, limit: int) -> list[str]:
        rows = await self._run(
            lambda conn: conn.execute(
                "SELECT id FROM conversations WHERE status = 'resolved' AND anonymized_at IS NULL AND coalesce(closed_at, updated_at) < %s LIMIT %s",
                (closed_before, limit),
            ).fetchall()
        )
        return [r["id"] for r in rows]

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

    # ── Audit log ──

    async def add_audit(self, entry: dict) -> None:
        await self._run(
            lambda conn: conn.execute(
                """INSERT INTO access_log (actor_id, actor_name, actor_role, action, conversation_id, customer_id, detail)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (entry.get("actorId"), entry.get("actorName"), entry.get("actorRole"), entry["action"], entry.get("conversationId"),
                 entry.get("customerId"), Jsonb(entry.get("detail") or {})),
            )
        )  # fmt: skip

    async def list_audit(self, *, actor_id=None, conversation_id=None, action=None, limit=200) -> list[dict]:
        where, params = [], []
        for column, value in (("actor_id", actor_id), ("conversation_id", conversation_id), ("action", action)):
            if value:
                where.append(f"{column} = %s")
                params.append(value)
        sql = "SELECT * FROM access_log" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY at DESC LIMIT %s"
        rows = await self._run(lambda conn: conn.execute(sql, [*params, limit]).fetchall())
        return [{"id": r["id"], "at": r["at"].isoformat(), "actorId": r["actor_id"], "actorName": r["actor_name"], "actorRole": r["actor_role"],
                 "action": r["action"], "conversationId": r["conversation_id"], "customerId": r["customer_id"], "detail": r["detail"]}
                for r in rows]  # fmt: skip

    # ── Review queue ──

    async def list_review_items(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        where, params = [], []
        if kind:
            where.append("kind = %s")
            params.append(kind)
        if status:
            where.append("status = %s")
            params.append(status)
        sql = "SELECT * FROM review_items" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY count DESC, created_at"
        return [_review(r) for r in await self._run(lambda conn: conn.execute(sql, params).fetchall())]

    async def get_review_item(self, item_id: str) -> dict | None:
        return _review(await self._run(lambda conn: conn.execute("SELECT * FROM review_items WHERE id = %s", (item_id,)).fetchone()))

    async def save_review_item(self, item: dict) -> dict:
        columns = [c for w, c in REVIEW_COLUMNS.items() if w in item and w not in ("createdAt", "updatedAt")]
        values = [Jsonb(item[w]) if w in REVIEW_JSON else item[w] for w, c in REVIEW_COLUMNS.items() if c in columns]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "id")
        sql = (
            f"INSERT INTO review_items ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now() RETURNING *"
        )
        return _review(await self._run(lambda conn: conn.execute(sql, values).fetchone()))

    async def forget_conversations_in_review(self, conversation_ids: list[str]) -> None:
        await self._run(
            lambda conn: conn.execute(
                "UPDATE review_items SET conversation_ids = ARRAY(SELECT unnest(conversation_ids) EXCEPT SELECT unnest(%s::text[]))"
                " WHERE conversation_ids && %s::text[]",
                (conversation_ids, conversation_ids),
            )
        )

    # ── Coordination ──

    @asynccontextmanager
    async def exclusive(self, name: str):
        """Session-level advisory lock on a dedicated connection: one runner of a job across processes."""
        key = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)
        async with self._connection() as conn:
            acquired = (await self._call(lambda: conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (key,)).fetchone()))["ok"]
            try:
                yield acquired
            finally:
                if acquired:
                    await self._call(lambda: conn.execute("SELECT pg_advisory_unlock(%s)", (key,)))
