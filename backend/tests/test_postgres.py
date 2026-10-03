"""PostgresRepository against a real database (skipped unless BATON_TEST_DATABASE_URL is set):

    docker exec baton-db-1 createdb -U baton baton_test
    BATON_TEST_DATABASE_URL=postgresql://baton:<password>@127.0.0.1:5433/baton_test uv run pytest tests/test_postgres.py

Every test starts from an empty schema. Never point this at a database you care about.
"""

import asyncio
import os

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.conversation import lifecycle
from app.db.postgres import V1_USERS_AND_DOCUMENTS, PostgresRepository
from app.db.repository import AlreadyOpen, ConversationFilter, Identity

URL = os.environ.get("BATON_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set BATON_TEST_DATABASE_URL to run the Postgres tests")

CUSTOMER = {"id": "cus_t1", "name": "Test Customer", "email": "t1@example.com", "tier": "plus", "location": "Lagos, NG",
            "customerSince": "2024-01-02", "lifetimeValue": 10.5, "orderCount": 1, "previousConversations": 0}  # fmt: skip


def reset_schema():
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")


def run(coro):
    return asyncio.run(coro)


async def started() -> PostgresRepository:
    repo = PostgresRepository(URL)
    await repo.start()
    await repo.seed_person("customer", CUSTOMER)
    return repo


def conversation(now=1_000) -> dict:
    snapshot = {k: v for k, v in CUSTOMER.items()}
    return lifecycle.create_conversation(snapshot, now)


def test_migrates_a_v1_database_of_documents():
    reset_schema()
    legacy = conversation(500)
    lifecycle.add_message(legacy, {"sender": "customer", "text": "Old question", "createdAt": 600})
    lifecycle.resolve_conversation(legacy, {"name": "Alex"}, 700)
    with psycopg.connect(URL, autocommit=True) as conn:  # a database from before schema versioning
        conn.execute(V1_USERS_AND_DOCUMENTS)
        conn.execute("INSERT INTO customers (id, name, email) VALUES (%s, %s, %s)", (CUSTOMER["id"], CUSTOMER["name"], CUSTOMER["email"]))
        conn.execute("INSERT INTO conversations (id, customer_id, status, created_at, updated_at, doc) VALUES (%s, %s, %s, %s, %s, %s)",
                     (legacy["id"], CUSTOMER["id"], "resolved", 500, 700, Jsonb(legacy)))  # fmt: skip

    async def check():
        repo = PostgresRepository(URL)
        await repo.start()
        await repo.start()  # idempotent: already at the latest version
        try:
            moved = await repo.get_conversation(legacy["id"])
            assert [m["text"] for m in moved["messages"]] == ["Old question", "Resolved by Alex"]
            assert moved["closedReason"] == "resolved" and moved["traceIds"] == []
        finally:
            await repo.close()

    run(check())
    with psycopg.connect(URL) as conn:
        assert [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4, 5]
        assert conn.execute("SELECT count(*) FROM conversation_events WHERE conversation_id = %s", (legacy["id"],)).fetchone()[0] == 1


def test_transactions_serialise_changes_to_one_conversation():
    reset_schema()

    async def scenario():
        repo = await started()
        try:
            c = conversation()
            await repo.create_conversation(c)

            async def append(text, delay):
                async with repo.transaction(c["id"]) as locked:
                    await asyncio.sleep(delay)  # slow work while locked
                    lifecycle.add_message(locked, {"sender": "customer", "text": text, "createdAt": 2_000})

            await asyncio.gather(append("first", 0.3), append("second", 0))
            stored = await repo.get_conversation(c["id"])
            assert sorted(m["text"] for m in stored["messages"]) == ["first", "second"]  # no lost update

            with pytest.raises(RuntimeError):
                async with repo.transaction(c["id"]) as locked:
                    lifecycle.add_message(locked, {"sender": "customer", "text": "rolled back", "createdAt": 3_000})
                    raise RuntimeError("boom")
            assert len((await repo.get_conversation(c["id"]))["messages"]) == 2

            async with repo.transaction(c["id"]) as locked:  # a bot turn's claim round-trips
                locked["botTurn"] = {"messageId": "msg_1", "startedAt": 4_000}
            assert (await repo.get_conversation(c["id"]))["botTurn"] == {"messageId": "msg_1", "startedAt": 4_000}
            async with repo.transaction(c["id"]) as locked:
                locked["botTurn"] = None
            assert (await repo.get_conversation(c["id"]))["botTurn"] is None

            async with repo.transaction("conv_missing") as missing:
                assert missing is None
        finally:
            await repo.close()

    run(scenario())


def test_one_live_session_lists_and_counts():
    reset_schema()

    async def scenario():
        repo = await started()
        try:
            c = conversation()
            await repo.create_conversation(c)
            with pytest.raises(AlreadyOpen):
                await repo.create_conversation(conversation())

            async with repo.transaction(c["id"]) as locked:
                lifecycle.add_message(locked, {"sender": "customer", "text": "Can I talk to a person?", "createdAt": 1_100})
                decision = {"primary": {"reason": "customer_request", "detail": "asked"}, "signals": [{"reason": "customer_request", "detail": "asked"}]}
                lifecycle.request_handoff(locked, decision, locked["messages"][-1], 1_200)
                lifecycle.accept_handoff(locked, {"id": "agt_x", "name": "Agent X"}, 1_300)

            heads = await repo.list_conversations(ConversationFilter(open_only=True), with_handoffs=True)
            assert [h["id"] for h in heads] == [c["id"]] and heads[0]["lastMessage"]["sender"] == "bot"  # the handoff notice
            assert heads[0]["lastCustomerMessageAt"] == 1_100 and heads[0]["handoff"]["status"] == "accepted"
            assert await repo.count_active("agt_x") == 1
            assert (await repo.list_conversations(ConversationFilter(q="test cust")))[0]["id"] == c["id"]
            assert repo.desk_stats(2_000, 300_000)["byStatus"]["agent_active"] == 1

            await repo.mark_customer_seen(c["id"], 50_000)
            await repo.mark_customer_seen(c["id"], 51_000)  # throttled: within 15 s of the last write
            assert (await repo.get_conversation(c["id"]))["customerSeenAt"] == 50_000

            async with repo.transaction(c["id"]) as locked:
                lifecycle.resolve_conversation(locked, {"name": "Agent X"}, 60_000)
            await repo.create_conversation(conversation(70_000))  # the first is closed: a new one is fine
        finally:
            await repo.close()

    run(scenario())


def test_people_audit_review_erasure_and_job_lock():
    reset_schema()

    async def scenario():
        repo = await started()
        try:
            claimed = await repo.upsert_person("customer", Identity(sub="kc-1", name="Test Customer", email="t1@example.com", email_verified=True))
            assert claimed["id"] == "cus_t1" and claimed["keycloakId"] == "kc-1"

            c = conversation()
            c["traceIds"] = ["tr-1"]
            await repo.create_conversation(c)
            await repo.add_audit({"actorId": "kc-a", "actorName": "Agent", "actorRole": "agent", "action": "conversation.view",
                                  "conversationId": c["id"], "customerId": "cus_t1", "detail": {}})  # fmt: skip
            assert (await repo.list_audit(conversation_id=c["id"]))[0]["actorName"] == "Agent"

            item = {"id": "rev_1", "kind": "knowledge_gap", "status": "pending", "question": "q?", "answer": "", "title": "",
                    "examples": ["q?"], "agentAnswers": [], "conversationIds": [c["id"], "conv_other"], "count": 1,
                    "embedding": [0.1, 0.2], "publishedPath": None}  # fmt: skip
            saved = await repo.save_review_item(item)
            assert saved["embedding"] == pytest.approx([0.1, 0.2]) and saved["createdAt"]

            removed = await repo.delete_customer("cus_t1")
            await repo.forget_conversations_in_review(removed["conversationIds"])
            assert removed == {"conversations": 1, "conversationIds": [c["id"]], "traceIds": ["tr-1"]}
            assert await repo.get_conversation(c["id"]) is None and await repo.get_person("customer", "cus_t1") is None
            assert (await repo.get_review_item("rev_1"))["conversationIds"] == ["conv_other"]

            async with repo.exclusive("job") as first:
                async with repo.exclusive("job") as second:
                    assert first is True and second is False
            async with repo.exclusive("job") as again:
                assert again is True
        finally:
            await repo.close()

    run(scenario())


def test_widget_visitors_and_identified_customers():
    reset_schema()

    async def scenario():
        repo = await started()
        try:
            visitor = await repo.create_visitor()
            assert visitor["isVisitor"] is True and visitor["name"].startswith("Visitor ") and visitor["email"] is None
            claimed = await repo.upsert_external_customer("shop-1", "Test Customer", "t1@example.com")
            assert claimed["id"] == "cus_t1" and claimed["externalId"] == "shop-1"  # seeded profile claimed by email
            again = await repo.upsert_external_customer("shop-1", "T. Customer", None)
            assert again["id"] == "cus_t1" and again["name"] == "T. Customer" and again["email"] == "t1@example.com"
            fresh = await repo.upsert_external_customer("shop-2", None, "new@example.org")
            assert fresh["id"] not in ("cus_t1", visitor["id"]) and fresh["name"] == "Customer" and fresh["isVisitor"] is False
        finally:
            await repo.close()

    run(scenario())
