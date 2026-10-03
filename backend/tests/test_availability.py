"""Is anyone there? Business hours, agent presence, the customer's place in the queue, requests that
arrive while nobody is available, and the alerts that reach people who aren't looking at the desk."""

import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import team
from app.conversation.lifecycle import ApiError
from app.db import repository
from app.notify import alerts, mail, webhook
from tests.support import ALEX, JADE, JORDAN, LENA, MAYA, SAM, customer, say, start

LAGOS = {"enabled": True, "timezone": "Africa/Lagos", "days": [0, 1, 2, 3, 4], "open": "09:00", "close": "17:00"}


def ms(text: str, zone: str = "Africa/Lagos") -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(zone)).timestamp() * 1000)


def visitor():
    row = asyncio.run(repository().create_visitor())
    return customer(row["id"], row["name"])


def agent_online(client, who=ALEX):
    client.as_(who).get("/conversations")  # the desk polling is what marks an agent as present
    team.forget_status()


@pytest.fixture()
def outbox(monkeypatch):
    """Emails and webhook posts, captured instead of sent."""
    sent = {"email": [], "webhook": []}

    async def fake_send(to, subject, body, *, kind, reply_to=None):
        sent["email"].append({"to": [to] if isinstance(to, str) else list(to), "subject": subject, "body": body, "kind": kind})
        return True

    async def fake_post(text, *, kind):
        sent["webhook"].append({"text": text, "kind": kind})
        return True

    monkeypatch.setattr(mail, "send", fake_send)
    monkeypatch.setattr(webhook, "post", fake_post)
    monkeypatch.setattr(alerts.mail, "send", fake_send)
    monkeypatch.setattr(alerts.webhook, "post", fake_post)
    return sent


# ── Business hours ───────────────────────────────────────────────────────────


def test_business_hours_in_the_business_time_zone():
    assert team.is_open(ms("2026-10-05T10:00"), LAGOS)  # a Monday morning in Lagos
    assert not team.is_open(ms("2026-10-05T17:00"), LAGOS)  # closing time is exclusive
    assert not team.is_open(ms("2026-10-03T10:00"), LAGOS)  # Saturday
    assert team.is_open(ms("2026-10-05T09:30", "Europe/London"), LAGOS)  # 09:30 London = 09:30 Lagos (both UTC+1)
    friday_evening = ms("2026-10-02T18:00")
    assert team.next_open(friday_evening, LAGOS) == ms("2026-10-05T09:00")
    assert team.describe(team.next_open(friday_evening, LAGOS), LAGOS) == "Monday at 09:00 (WAT)"
    assert team.next_open(ms("2026-10-05T10:00"), LAGOS) is None
    assert team.is_open(ms("2026-10-03T03:00"), {**LAGOS, "enabled": False})  # not configured = always staffed


def test_business_hours_are_validated():
    with pytest.raises(ApiError, match="time zone"):
        team.validate_hours({**LAGOS, "timezone": "Mars/Olympus"})
    with pytest.raises(ApiError, match="before closing"):
        team.validate_hours({**LAGOS, "open": "18:00"})
    with pytest.raises(ApiError, match="days"):
        team.validate_hours({**LAGOS, "days": [7]})
    assert team.validate_hours({**LAGOS, "days": [4, 0, 0]})["days"] == [0, 4]


def test_admins_set_business_hours(client):
    saved = client.as_(JADE).put("/admin/business-hours", json=LAGOS)
    assert saved.status_code == 200 and saved.json()["hours"]["timezone"] == "Africa/Lagos"
    assert client.as_(JADE).put("/admin/business-hours", json={**LAGOS, "close": "25:00"}).status_code == 400
    assert client.as_(ALEX).get("/admin/business-hours").status_code == 403
    entry = client.as_(JADE).get("/admin/audit", params={"action": "business_hours.update"}).json()
    assert entry and entry[0]["detail"]["timezone"] == "Africa/Lagos"


# ── Nobody available ─────────────────────────────────────────────────────────


def test_a_request_while_nobody_is_available_asks_for_an_email(client):
    guest = visitor()
    conversation_id = start(client, guest)
    body = say(client, conversation_id, "Can I talk to a real person please?", guest).json()  # no agent has the desk open
    notice = next(m["text"] for m in reversed(body["messages"]) if m["sender"] == "bot")
    assert "nobody is available" in notice and "Leave your email" in notice
    assert body["waiting"]["teamAvailable"] is False and body["waiting"]["askForEmail"] is True
    assert body["messages"][-1]["text"].startswith("Your request is with our team")  # not "Connecting you…"

    assert client.as_(guest).post(f"/me/conversations/{conversation_id}/contact", json={"email": "not-an-email"}).status_code == 400
    left = client.as_(guest).post(f"/me/conversations/{conversation_id}/contact", json={"email": "guest@example.com"}).json()
    assert left["waiting"]["askForEmail"] is False and left["waiting"]["replyEmail"] == "g••••@example.com"
    assert "guest@example.com" not in str(left)  # the event with the full address is for agents only

    queued = next(c for c in client.as_(ALEX).get("/conversations").json() if c["id"] == conversation_id)
    assert queued["handoff"]["offline"] is True and queued["handoff"]["replyByEmail"] is True
    seen = client.as_(ALEX).get(f"/conversations/{conversation_id}").json()
    assert seen["contact"]["email"] == "guest@example.com"


def test_a_customer_the_website_vouched_for_is_told_where_the_reply_goes(client):
    conversation_id = start(client, SAM)  # seeded with an email
    body = say(client, conversation_id, "Can I speak to a human?", SAM).json()
    notice = next(m["text"] for m in reversed(body["messages"]) if m["sender"] == "bot")
    assert "We’ll email you at s" in notice and body["waiting"]["askForEmail"] is False


def test_an_away_agent_does_not_count_as_available(client):
    agent_online(client)
    assert client.as_(ALEX).put("/me/availability", json={"available": False}).json()["available"] is False
    conversation_id = start(client)
    body = say(client, conversation_id, "I want to talk to a real person please").json()
    assert body["waiting"]["teamAvailable"] is False
    client.as_(ALEX).put("/me/availability", json={"available": True})
    team.forget_status()
    assert client.as_(MAYA).get(f"/me/conversations/{conversation_id}").json()["waiting"]["teamAvailable"] is True


def test_outside_business_hours_the_customer_hears_when_the_team_is_back(client):
    agent_online(client)
    closed_today = [d for d in range(7) if d != datetime.now(ZoneInfo("Africa/Lagos")).weekday()][:2]
    client.as_(JADE).put("/admin/business-hours", json={**LAGOS, "days": closed_today})
    conversation_id = start(client)
    body = say(client, conversation_id, "I want to talk to a real person please").json()
    notice = next(m["text"] for m in reversed(body["messages"]) if m["sender"] == "bot")
    assert "we’re back" in notice and "(WAT)" in notice
    assert body["waiting"]["backAtText"].endswith("at 09:00 (WAT)")


# ── The queue ────────────────────────────────────────────────────────────────


def test_customers_see_their_place_in_line(client):
    agent_online(client)
    first, second = start(client, MAYA), start(client, LENA)
    say(client, first, "I want to talk to a real person please", MAYA)
    body = say(client, second, "Can I talk to a real person?", LENA).json()
    assert body["waiting"]["teamAvailable"] is True and body["waiting"]["position"] == 2
    assert "nobody is available" not in str(body)

    urgent = start(client, JORDAN)  # a sensitive topic goes ahead of both
    assert say(client, urgent, "There is an unauthorized charge of $89.00 on my card", JORDAN).json()["waiting"]["position"] == 1
    assert client.as_(LENA).get(f"/me/conversations/{second}").json()["waiting"]["position"] == 3
    client.as_(ALEX).post(f"/conversations/{urgent}/handoff/accept")
    assert client.as_(LENA).get(f"/me/conversations/{second}").json()["waiting"]["position"] == 2
    assert client.as_(MAYA).get(f"/me/conversations/{first}").json()["waiting"]["position"] == 1


# ── Alerts ───────────────────────────────────────────────────────────────────


def test_requests_while_nobody_is_available_alert_the_team_once(client, outbox):
    conversation_id = start(client)
    say(client, conversation_id, "I want to talk to a real person please")
    assert asyncio.run(alerts.escalate_waiting_handoffs()) == 1
    email = outbox["email"][0]
    assert email["kind"] == "agent_alert" and "while the team is away" in email["subject"]
    assert {"alex.rivera@baton.example", "priya.shah@baton.example"} <= set(email["to"])
    assert "maya.chen@" in email["body"] and "/desk" in email["body"]
    assert len(outbox["webhook"]) == 1
    assert asyncio.run(alerts.escalate_waiting_handoffs()) == 0  # once per handoff


def test_a_handoff_waiting_too_long_is_escalated(client, outbox):
    agent_online(client)
    conversation_id = start(client)
    say(client, conversation_id, "I want to talk to a real person please")
    assert asyncio.run(alerts.escalate_waiting_handoffs()) == 0  # someone is on it; not waited long yet
    repository().conversations.get(conversation_id)["handoff"]["requestedAt"] -= 10 * 60_000
    assert asyncio.run(alerts.escalate_waiting_handoffs()) == 1
    assert "Waiting 10 min" in outbox["email"][0]["subject"]


def test_a_reply_reaches_a_customer_who_has_left_by_email(client, outbox):
    agent_online(client)
    conversation_id = start(client)
    say(client, conversation_id, "I want to talk to a real person please")
    client.as_(ALEX).post(f"/conversations/{conversation_id}/handoff/accept")

    client.as_(ALEX).post(f"/conversations/{conversation_id}/agent-messages", json={"text": "Still there?"})
    time.sleep(0.2)
    assert outbox["email"] == []  # Maya still has the chat open

    repository().conversations.get(conversation_id)["customerSeenAt"] -= 30 * 60_000  # she left
    client.as_(ALEX).post(f"/conversations/{conversation_id}/agent-messages", json={"text": "Your refund is on its way."})
    for _ in range(20):
        if outbox["email"]:
            break
        time.sleep(0.05)
    email = outbox["email"][0]
    assert email["kind"] == "customer_reply" and email["to"] == ["maya.chen@example.com"]
    assert "Your refund is on its way." in email["body"] and email["body"].startswith("Hi Maya")
