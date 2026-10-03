"""How a chat ends when the customer leaves, disappears, comes back or goes quiet (conversation/sessions.py),
and the presence signals the widget sends (POST /me/conversations/{id}/presence)."""

import asyncio

from app.config import settings
from app.conversation import sessions
from app.db import repository
from tests.support import ALEX, LENA, MAYA, SAM, customer, say, start

SECOND = 1000
MINUTE = 60 * SECOND


def visitor():
    row = asyncio.run(repository().create_visitor())
    return customer(row["id"], row["name"])


def stored(conversation_id):
    return repository().conversations.get(conversation_id)


def presence(client, conversation_id, state, who=MAYA):
    return client.as_(who).post(f"/me/conversations/{conversation_id}/presence", json={"state": state})


def sweep_at(now):
    return {c["id"]: c["closedReason"] for c in asyncio.run(sessions.sweep(now=now, started_at=0))}


def test_a_customer_who_closes_the_page_ends_a_bot_chat_after_the_grace(client):
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    assert presence(client, conversation_id, "left").json() == {"status": "bot_active"}
    left_at = stored(conversation_id)["customerLeftAt"]

    assert sweep_at(left_at + 30 * SECOND) == {}  # still within the grace: they may be on the next page
    assert sweep_at(left_at + settings.customer_left_grace_seconds * SECOND + 1) == {conversation_id: "left"}
    closing = client.as_(MAYA).get(f"/me/conversations/{conversation_id}").json()["messages"][-1]["text"]
    assert closing == "Chat closed after you left. Start a new chat any time"


def test_coming_back_within_the_grace_keeps_the_chat(client):
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    presence(client, conversation_id, "left")
    assert presence(client, conversation_id, "here").json() == {"status": "bot_active"}  # the next page's widget
    assert stored(conversation_id)["customerLeftAt"] is None
    assert sweep_at(stored(conversation_id)["customerSeenAt"] + 2 * MINUTE) == {}


def test_a_customer_with_no_sign_of_life_is_treated_as_gone(client):
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    seen = stored(conversation_id)["customerSeenAt"]
    assert sweep_at(seen + 2 * MINUTE) == {}
    assert sweep_at(seen + settings.customer_gone_seconds * SECOND + 1) == {conversation_id: "left"}


def test_the_heartbeat_keeps_a_minimised_chat_alive(client):
    """The panel minimised doesn't mean gone: the widget's heartbeat continues while the page is open."""
    waiting = start(client, LENA)
    say(client, waiting, "Can I talk to a real person?", LENA)
    t0 = stored(waiting)["customerSeenAt"]
    stored(waiting)["customerSeenAt"] = t0 + 20 * MINUTE  # 20 minutes of heartbeats, no polling of the transcript
    assert sweep_at(t0 + 21 * MINUTE) == {}


def test_a_quiet_customer_is_asked_once_before_the_chat_closes(client):
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    asked = stored(conversation_id)["updatedAt"]
    nudge_at = asked + int((settings.session_idle_minutes - settings.session_nudge_minutes) * MINUTE)
    stored(conversation_id)["customerSeenAt"] = nudge_at  # on the page all along

    assert sweep_at(nudge_at) == {}
    nudge = client.as_(MAYA).get(f"/me/conversations/{conversation_id}").json()["messages"][-1]
    assert nudge["sender"] == "bot" and nudge["text"].startswith("Are you still there?")
    stored(conversation_id)["customerSeenAt"] = nudge_at + MINUTE  # the widget's heartbeat, a minute later
    sweep_at(nudge_at + MINUTE)
    assert sum(m["text"].startswith("Are you still there?") for m in stored(conversation_id)["messages"]) == 1  # once

    stored(conversation_id)["customerSeenAt"] = asked + int(settings.session_idle_minutes * MINUTE)
    assert sweep_at(asked + int(settings.session_idle_minutes * MINUTE)) == {conversation_id: "inactive"}


def test_answering_the_nudge_resets_it(client):
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    stored(conversation_id)["insights"]["idleNudgeAt"] = 1
    say(client, conversation_id, "Yes, still here — and for a gift card?")
    assert "idleNudgeAt" not in stored(conversation_id)["insights"]


def test_leaving_while_waiting_abandons_unless_we_can_reply_by_email(client):
    guest = visitor()
    no_email = start(client, guest)
    say(client, no_email, "Can I speak to a human?", guest)
    presence(client, no_email, "left", guest)
    with_email = start(client, SAM)  # the website vouched for Sam's email
    say(client, with_email, "Can I speak to a human?", SAM)
    presence(client, with_email, "left", SAM)

    later = max(stored(no_email)["customerLeftAt"], stored(with_email)["customerLeftAt"]) + 2 * MINUTE
    assert sweep_at(later) == {no_email: "abandoned"}
    assert stored(with_email)["status"] == "handoff_pending"  # stays queued: the team replies by email


def test_the_agent_sees_the_customer_leave_and_come_back(client):
    client.as_(ALEX).get("/conversations")  # someone is at the desk
    conversation_id = start(client)
    say(client, conversation_id, "I want to talk to a real person please")
    client.as_(ALEX).post(f"/conversations/{conversation_id}/handoff/accept")

    presence(client, conversation_id, "left")
    seen = client.as_(ALEX).get(f"/conversations/{conversation_id}").json()
    assert seen["messages"][-1]["text"] == "Customer left the chat" and seen["customerLeftAt"]
    queued = next(c for c in client.as_(ALEX).get("/conversations").json() if c["id"] == conversation_id)
    assert queued["customerLeftAt"] == seen["customerLeftAt"]
    assert sweep_at(seen["customerLeftAt"] + 5 * MINUTE) == {}  # with an agent, leaving doesn't close it

    client.as_(MAYA).get(f"/me/conversations/{conversation_id}")  # they're back (reopened the chat)
    back = client.as_(ALEX).get(f"/conversations/{conversation_id}").json()
    assert back["messages"][-1]["text"] == "Customer is back" and back["customerLeftAt"] is None
    customer_view = client.as_(MAYA).get(f"/me/conversations/{conversation_id}").json()
    assert not any(m["text"] in ("Customer left the chat", "Customer is back") for m in customer_view["messages"])  # agents only


def test_presence_is_only_for_your_own_open_chat(client):
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    assert presence(client, conversation_id, "here", SAM).json() == {"status": None}  # not Sam's: nothing recorded
    assert presence(client, conversation_id, "left", SAM).status_code == 404
    client.as_(MAYA).post(f"/me/conversations/{conversation_id}/end")
    assert presence(client, conversation_id, "here").json() == {"status": None}
    assert presence(client, conversation_id, "left").json() == {"status": None}
    assert presence(client, conversation_id, "away").status_code == 400  # the API reports validation errors as 400
