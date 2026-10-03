"""Support sessions: they end (and never reopen), customers resume only live ones, follow-ups link to
the past for agents, and idle sessions close themselves."""

import asyncio

from app.config import settings
from app.conversation import sessions
from app.db import repository
from tests.support import ALEX, JADE, JORDAN, LENA, MAYA, SAM, customer, say, start

MINUTE = 60_000
DAY = 24 * 60 * MINUTE


def visitor():
    """A website visitor: no email, so nobody can answer them once they've left."""
    row = asyncio.run(repository().create_visitor())
    return customer(row["id"], row["name"])


def test_a_closed_conversation_never_reopens(client):
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    ended = client.as_(MAYA).post(f"/me/conversations/{conversation_id}/end").json()
    assert ended["status"] == "resolved" and ended["closedReason"] == "ended_by_customer"
    assert ended["messages"][-1]["text"] == "You ended the chat"

    reply = say(client, conversation_id, "One more thing…")
    assert reply.status_code == 409 and "has ended" in reply.json()["message"]
    assert client.as_(MAYA).post(f"/me/conversations/{conversation_id}/end").status_code == 409


def test_one_live_session_per_customer(client):
    first = start(client)
    assert start(client) == first  # a reload or second tab resumes the live session
    client.as_(MAYA).post(f"/me/conversations/{first}/end")
    second = start(client)
    assert second != first
    listed = client.as_(MAYA).get("/me/conversations").json()
    assert [c["id"] for c in listed] == [second, first] and listed[1]["closedReason"] == "ended_by_customer"


def test_follow_up_links_the_past_for_agents_not_the_bot(client):
    previous = start(client)
    say(client, previous, "I want to talk to a real person please")
    client.as_(ALEX).post(f"/conversations/{previous}/handoff/accept")
    client.as_(ALEX).post(f"/conversations/{previous}/resolve")

    created = client.as_(MAYA).post("/me/conversations", json={"followUpOf": previous}).json()
    assert created["followUpOf"] == {"id": previous, "subject": "I want to talk to a real person please"}
    assert created["messages"] == []  # the customer starts fresh

    detail = client.as_(ALEX).get(f"/conversations/{created['id']}").json()
    link = detail["followUpOf"]
    assert link["id"] == previous and link["closedReason"] == "resolved" and link["handledBy"] == "Alex Rivera"
    assert link["handoffReason"] == "customer_request" and link["summary"]
    queue = {c["id"]: c for c in client.as_(ALEX).get("/conversations").json()}
    assert queue[created["id"]]["followUpOf"] == previous


def test_follow_up_rules(client):
    live = start(client, MAYA)
    # Only an ended conversation can be followed up (an open one is simply resumed).
    assert client.as_(SAM).post("/me/conversations", json={"followUpOf": live}).status_code == 404  # not Sam's
    client.as_(MAYA).post(f"/me/conversations/{live}/end")
    other = start(client, SAM)
    client.as_(SAM).post(f"/me/conversations/{other}/end")
    assert client.as_(MAYA).post("/me/conversations", json={"followUpOf": other}).status_code == 404


def test_idle_sessions_close_themselves(client):
    guest = visitor()
    bot_idle, waiting, present, with_agent = (start(client, who) for who in (MAYA, guest, LENA, JORDAN))
    say(client, bot_idle, "How long does a refund take?", MAYA)
    say(client, waiting, "Can I speak to a human?", guest)
    say(client, present, "Can I talk to a real person?", LENA)
    say(client, with_agent, "I want to talk to a real person please", JORDAN)
    client.as_(ALEX).post(f"/conversations/{with_agent}/handoff/accept")

    later = max(c["updatedAt"] for c in repository().conversations.values()) + int(settings.session_idle_minutes * MINUTE)
    repository().conversations.get(present)["customerSeenAt"] = later - MINUTE  # still has the chat open
    closed = asyncio.run(sessions.sweep(now=later, started_at=0))

    reasons = {c["id"]: c["closedReason"] for c in closed}
    assert reasons == {bot_idle: "inactive", waiting: "abandoned", with_agent: "inactive"}
    abandoned = repository().conversations.get(waiting)
    assert abandoned["handoff"]["status"] == "abandoned"
    assert waiting not in {c["id"] for c in client.as_(ALEX).get("/conversations").json()}
    assert client.as_(guest).get(f"/me/conversations/{waiting}").json()["messages"][-1]["text"].startswith("Chat closed")
    assert repository().conversations.get(present)["status"] == "handoff_pending"


def test_a_request_we_can_answer_by_email_stays_queued(client):
    """Sam's website vouched for an email: leaving the chat doesn't abandon the request — the team replies
    by email — until OFFLINE_FOLLOWUP_DAYS have passed."""
    waiting = start(client, SAM)
    say(client, waiting, "Can I speak to a human?", SAM)
    asked = repository().conversations.get(waiting)["updatedAt"]

    assert asyncio.run(sessions.sweep(now=asked + 2 * 60 * MINUTE, started_at=0)) == []
    assert repository().conversations.get(waiting)["status"] == "handoff_pending"
    closed = asyncio.run(sessions.sweep(now=asked + settings.offline_followup_days * DAY + MINUTE, started_at=0))
    assert [c["closedReason"] for c in closed] == ["abandoned"]


def test_agents_see_the_customer_timeline(client):
    first = start(client)
    say(client, first, "How long does a refund take?")
    client.as_(MAYA).post(f"/me/conversations/{first}/end")
    second = start(client)
    say(client, second, "There is an unauthorized charge on my card")

    timeline = client.as_(ALEX).get("/customers/cus_maya/conversations").json()
    assert [t["id"] for t in timeline] == [second, first]
    assert timeline[0]["handoffReason"] == "sensitive_topic" and timeline[0]["closedReason"] is None
    assert timeline[1]["botAnswers"] == 1 and "answered 1 question" in timeline[1]["summary"]
    assert client.as_(MAYA).get("/customers/cus_maya/conversations").status_code == 403


def test_insights_report_how_sessions_end(client):
    guest = visitor()
    waiting = start(client, guest)
    say(client, waiting, "Can I speak to a human?", guest)
    asyncio.run(sessions.sweep(now=repository().conversations.get(waiting)["updatedAt"] + int(settings.session_abandon_minutes * MINUTE) + 1, started_at=0))
    numbers = client.as_(JADE).get("/admin/insights").json()["sessions"]
    assert numbers["byClosedReason"]["abandoned"] == 1 and numbers["abandonmentRate"] == 1
