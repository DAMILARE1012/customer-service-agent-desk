"""Data rules: redaction, retention, one-step erasure and the audit log."""

import asyncio

import pytest

from app.config import settings
from app.db import repository
from app.privacy import retention
from app.privacy.redact import redact
from tests.support import ALEX, JADE, MAYA, SAM, say, start

DAY = 86_400_000


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mail me at maya.chen@example.com please", "Mail me at [EMAIL] please"),
        ("Card 4111 1111 1111 1111 was charged", "Card [CARD] was charged"),
        ("Tracking 1234 5678 9012 3456 isn't a card", "Tracking 1234 5678 9012 3456 isn't a card"),  # fails the Luhn check
        ("Call +1 (206) 555-0142 tomorrow", "Call [PHONE] tomorrow"),
        ("Where is order 48213?", "Where is order [ORDER]?"),
        ("My order #50912 is late", "My order [ORDER] is late"),
        ("IBAN DE89 3704 0044 0532 0130 00 please", "IBAN [IBAN] please"),
        ("From 192.168.10.4 it fails", "From [IP] it fails"),
        ("I paid $89.00 on 12/03", "I paid $89.00 on 12/03"),  # amounts and dates stay: they're the question
    ],
)
def test_redaction_patterns(text, expected):
    assert redact(text) == expected


def test_redaction_removes_known_names():
    assert redact("Hi, Maya Chen here — maya again", ["Maya Chen", "Maya", "Chen"]) == "Hi, [NAME] here — [NAME] again"


def test_retention_wipes_text_but_keeps_the_shape(client, monkeypatch):
    deleted = []

    async def fake_delete(ids):
        deleted.extend(ids)
        return {"deleted": len(ids)}

    monkeypatch.setattr(retention, "delete_traces", fake_delete)
    conversation_id = start(client)
    say(client, conversation_id, "There is an unauthorized charge on my card, email maya.chen@example.com")
    client.as_(ALEX).post(f"/conversations/{conversation_id}/handoff/accept")
    client.as_(ALEX).post(f"/conversations/{conversation_id}/resolve")
    repository().conversations[conversation_id]["traceIds"] = ["trace-1"]

    closed_at = repository().conversations[conversation_id]["closedAt"]
    report = asyncio.run(retention.apply_retention(now=closed_at + (settings.retention_days + 1) * DAY))
    assert report["anonymized"] == 1 and deleted == ["trace-1"]

    stored = repository().conversations[conversation_id]
    assert all(m["text"] == "[removed]" for m in stored["messages"] if m["sender"] != "system")
    assert stored["subject"] is None and stored["customer"]["name"] == "Former conversation"
    assert stored["handoff"]["summary"] == "[removed]" and stored["handoff"]["entities"] == []
    assert stored["handoff"]["reason"] == "sensitive_topic" and stored["closedReason"] == "resolved"  # reporting still works
    # Already anonymised: a second run leaves it alone.
    assert asyncio.run(retention.apply_retention(now=closed_at + 400 * DAY))["anonymized"] == 0


def test_erasure_deletes_everything_about_a_customer(client):
    first = start(client, MAYA)
    say(client, first, "How long does a refund take?", MAYA)
    client.as_(MAYA).post(f"/me/conversations/{first}/end")
    start(client, MAYA)
    other = start(client, SAM)

    assert client.as_(JADE).post("/admin/customers/cus_maya/erase", json={"confirm": "nope"}).status_code == 400
    assert client.as_(ALEX).post("/admin/customers/cus_maya/erase", json={"confirm": "cus_maya"}).status_code == 403
    report = client.as_(JADE).post("/admin/customers/cus_maya/erase", json={"confirm": "cus_maya"}).json()
    assert report["conversations"] == 2 and report["customerId"] == "cus_maya"
    assert report["identity"]["deleted"] is False and "widget" in report["identity"]["note"] and report["complete"] is True

    assert not any(c["customer"]["id"] == "cus_maya" for c in repository().conversations.values())
    assert other in repository().conversations  # nobody else is touched
    customers = {c["id"] for c in client.as_(JADE).get("/admin/customers").json()}
    assert "cus_maya" not in customers and "cus_sam" in customers
    # Her widget session ends with her data: the widget starts a fresh, empty session.
    assert client.as_(MAYA).get("/me/conversations").status_code == 401

    entry = client.as_(JADE).get("/admin/audit", params={"action": "customer.erase"}).json()[0]
    assert entry["customerId"] == "cus_maya" and entry["detail"]["conversations"] == 2 and entry["actorName"] == "Jade Kim"


def test_audit_log_records_who_opened_which_transcript(client):
    conversation_id = start(client)
    say(client, conversation_id, "Can I talk to a real person?")
    for _ in range(3):  # the desk polls; one entry per person per conversation per 10 minutes
        client.as_(ALEX).get(f"/conversations/{conversation_id}")
    client.as_(JADE).get(f"/conversations/{conversation_id}")
    client.as_(ALEX).get("/customers/cus_maya/conversations")

    views = client.as_(JADE).get("/admin/audit", params={"conversationId": conversation_id}).json()
    assert sorted(v["actorName"] for v in views) == ["Alex Rivera", "Jade Kim"]
    assert {v["action"] for v in views} == {"conversation.view"} and views[0]["customerId"] == "cus_maya"
    assert any(e["action"] == "customer.timeline.view" for e in client.as_(JADE).get("/admin/audit").json())
    assert client.as_(ALEX).get("/admin/audit").status_code == 403


def test_customers_see_the_privacy_notice(client):
    me = client.as_(MAYA).get("/me").json()
    assert me["privacy"]["retentionDays"] == settings.retention_days and "deleted" in me["privacy"]["notice"]
    assert client.as_(ALEX).get("/me").json().get("privacy") is None
