"""The HTTP contract and its access rules, with the RAG answerer replaced by a stand-in (no index, model
or Groq key) and Keycloak replaced by a fixed signed-in user per request (token verification itself is
tested in test_auth.py). The `client` fixture is in conftest.py."""

from tests.support import ALEX, JADE, JORDAN, MAYA, PRIYA, SAM, say, start

# ── Customers ────────────────────────────────────────────────────────────────


def test_customer_gets_a_cited_answer_in_a_customer_safe_view(client):
    body = say(client, start(client), "How long does a refund take?").json()
    reply = body["messages"][-1]
    assert body["status"] == "bot_active"
    assert reply["sender"] == "bot" and reply["text"] == "Refunds take 2 business days."
    assert reply["sources"] == [{"title": "Refund processing times", "url": "/help/refunds"}]
    # Nothing internal leaks: no scores, brief, insights or copilot.
    assert "meta" not in reply and not {"handoff", "insights", "copilot", "customer"} & set(body)
    assert [c["id"] for c in client.as_(MAYA).get("/me/conversations").json()] == [body["id"]]


def test_handoff_is_explained_to_the_agent_but_not_to_the_customer(client):
    conversation_id = start(client, JORDAN)
    body = say(client, conversation_id, "There is an unauthorized charge of $89.00 on my card", JORDAN).json()
    assert body["status"] == "handoff_pending"
    assert [m["sender"] for m in body["messages"]] == ["customer", "bot", "system"]
    assert body["messages"][-1]["text"] == "Connecting you with a member of our team…"
    assert "Sensitive" not in str(body)

    queue = client.as_(ALEX).get("/conversations").json()
    item = next(c for c in queue if c["id"] == conversation_id)
    assert item["handoff"]["reason"] == "sensitive_topic" and item["handoff"]["priority"] == "urgent"
    assert item["customer"] == {"id": "cus_jordan", "name": "Jordan Okafor", "tier": "enterprise"}  # seeded CRM profile claimed by email

    accepted = client.as_(ALEX).post(f"/conversations/{conversation_id}/handoff/accept").json()
    assert accepted["status"] == "agent_active" and accepted["assignee"] == {"id": "agt_alex", "name": "Alex Rivera"}
    replied = client.as_(ALEX).post(f"/conversations/{conversation_id}/agent-messages", json={"text": "Looking into it."}).json()
    assert replied["messages"][-1]["author"]["id"] == "agt_alex"

    seen = client.as_(JORDAN).get(f"/me/conversations/{conversation_id}").json()
    assert seen["agent"] == {"name": "Alex"}
    assert [m["text"] for m in seen["messages"][-2:]] == ["Alex joined the chat", "Looking into it."]

    resolved = client.as_(ALEX).post(f"/conversations/{conversation_id}/resolve").json()
    assert resolved["status"] == "resolved"


def test_llm_failure_degrades_to_a_handoff_not_an_error(client):
    conversation_id = start(client)
    assert say(client, conversation_id, "How do I connect my domain?").status_code == 200
    detail = client.as_(ALEX).get(f"/conversations/{conversation_id}").json()
    assert detail["handoff"]["reason"] == "assistant_unavailable"


def test_out_of_scope_question_hands_off(client):
    conversation_id = start(client)
    say(client, conversation_id, "Do you offer bulk pricing for schools?")
    assert client.as_(ALEX).get(f"/conversations/{conversation_id}").json()["handoff"]["reason"] == "low_confidence"


# ── Access rules ─────────────────────────────────────────────────────────────


def test_signed_out_requests_are_rejected(client):
    res = client.as_(None).get("/me")
    assert res.status_code == 401 and res.headers["www-authenticate"].startswith("Bearer")
    assert client.as_(None).get("/conversations").status_code == 401
    assert client.as_(None).get("/health").status_code == 200


def test_customers_only_ever_see_their_own_conversations(client):
    mine = start(client, MAYA)
    assert client.as_(SAM).get(f"/me/conversations/{mine}").status_code == 404  # not 403: existence isn't revealed
    assert say(client, mine, "hello?", SAM).status_code == 404
    assert client.as_(SAM).get("/me/conversations").json() == []
    assert client.as_(SAM).get("/conversations").status_code == 403
    assert client.as_(SAM).get(f"/conversations/{mine}").status_code == 403
    assert client.as_(SAM).get("/customers").status_code == 403


def test_role_boundaries(client):
    assert client.as_(MAYA).get("/admin/agents").status_code == 403
    assert client.as_(ALEX).get("/admin/agents").status_code == 403
    assert client.as_(ALEX).post("/me/conversations").status_code == 403  # staff don't chat as customers
    assert client.as_(JADE).get("/admin/agents").status_code == 200
    assert client.as_(JADE).get("/conversations").status_code == 200


def test_messages_while_waiting_reach_the_brief_and_can_raise_priority(client):
    conversation_id = start(client)
    say(client, conversation_id, "I want to talk to a real person please")
    queued = next(c for c in client.as_(ALEX).get("/conversations").json() if c["id"] == conversation_id)
    assert queued["handoff"]["priority"] == "normal" and queued["handoff"]["addedWhileWaiting"] == 0

    # The bot stays quiet, but says once that the message reached the team.
    body = say(client, conversation_id, "Actually there's an unauthorized charge of $89.00 on my card").json()
    assert body["status"] == "handoff_pending"
    assert [m["sender"] for m in body["messages"][-2:]] == ["customer", "bot"] and "added that to your request" in body["messages"][-1]["text"]
    body = say(client, conversation_id, "It happened yesterday").json()
    assert body["messages"][-1]["sender"] == "customer"  # no second acknowledgement
    assert "Priority" not in str(body)  # the escalation is for agents only

    queued = next(c for c in client.as_(ALEX).get("/conversations").json() if c["id"] == conversation_id)
    assert queued["handoff"]["priority"] == "urgent" and queued["handoff"]["addedWhileWaiting"] == 2
    brief = client.as_(ALEX).get(f"/conversations/{conversation_id}").json()["handoff"]
    assert [m["text"] for m in brief["addedWhileWaiting"]] == ["Actually there's an unauthorized charge of $89.00 on my card", "It happened yesterday"]
    assert brief["escalated"]["from"] == "normal" and brief["escalated"]["to"] == "urgent"
    assert any(e["value"] == "$89.00" for e in brief["entities"])

    # A calmer message later never lowers it again.
    say(client, conversation_id, "Thanks, I'll wait")
    assert client.as_(ALEX).get(f"/conversations/{conversation_id}").json()["handoff"]["priority"] == "urgent"


def test_agent_identity_comes_from_the_token(client):
    conversation_id = start(client)
    say(client, conversation_id, "I want to talk to a real person please")
    client.as_(ALEX).post(f"/conversations/{conversation_id}/handoff/accept")
    # Priya can't reply to, return or resolve Alex's conversation — there's no agentId to spoof.
    assert client.as_(PRIYA).post(f"/conversations/{conversation_id}/agent-messages", json={"text": "hi", "agentId": "agt_alex"}).status_code == 403
    assert client.as_(PRIYA).post(f"/conversations/{conversation_id}/handoff/return").status_code == 403
    assert client.as_(PRIYA).post(f"/conversations/{conversation_id}/resolve").status_code == 403


def test_me_for_customers_and_staff(client):
    maya = client.as_(MAYA).get("/me").json()
    assert maya["user"]["roles"] == ["customer"] and maya["customer"]["tier"] == "plus" and maya["privacy"]
    assert maya.get("agent") is None

    jade = client.as_(JADE).get("/me").json()
    assert jade["agent"]["id"] == "agt_jade" and jade["admin"]["id"] == "adm_jade"
    assert jade.get("customer") is None


# ── Admin ────────────────────────────────────────────────────────────────────


def test_admin_controls_agent_capacity_and_access(client):
    assert client.as_(JADE).patch("/admin/agents/agt_alex", json={"capacity": 1}).json()["capacity"] == 1
    first, second = start(client, MAYA), start(client, SAM)
    say(client, first, "I want to talk to a real person please", MAYA)
    say(client, second, "Can I speak to a human?", SAM)
    assert client.as_(ALEX).post(f"/conversations/{first}/handoff/accept").status_code == 200
    at_capacity = client.as_(ALEX).post(f"/conversations/{second}/handoff/accept")
    assert at_capacity.status_code == 409 and "capacity" in at_capacity.json()["message"]

    client.as_(JADE).patch("/admin/agents/agt_alex", json={"active": False})
    blocked = client.as_(ALEX).get("/conversations")
    assert blocked.status_code == 403 and "disabled" in blocked.json()["message"]
    agents = {a["id"]: a for a in client.as_(JADE).get("/admin/agents").json()}
    assert agents["agt_alex"]["active"] is False and agents["agt_alex"]["activeChats"] == 1
    assert client.as_(JADE).patch("/admin/agents/agt_nobody", json={"active": True}).status_code == 404
    assert client.as_(JADE).patch("/admin/agents/agt_alex", json={"capacity": 0}).status_code == 400


def test_admin_policy_changes_apply_to_the_next_message(client):
    policy = client.as_(JADE).get("/admin/policy").json()
    assert set(policy["values"]) == {"noMatchThreshold", "sentimentThreshold", "maxFailedAttempts", "procedureThreshold"}

    # A neutral message counts as "frustrated" once the sentiment threshold is raised above zero.
    updated = client.as_(JADE).put("/admin/policy", json={"sentimentThreshold": 0.5}).json()
    assert updated["values"]["sentimentThreshold"] == 0.5 and updated["updatedBy"] == "Jade Kim"
    conversation_id = start(client)
    say(client, conversation_id, "How long does a refund take?")
    assert client.as_(ALEX).get(f"/conversations/{conversation_id}").json()["handoff"]["reason"] == "negative_sentiment"

    assert client.as_(JADE).put("/admin/policy", json={"maxFailedAttempts": 1.5}).status_code == 400
    assert client.as_(JADE).put("/admin/policy", json={"sentimentThreshold": 3}).status_code == 400
    assert client.as_(JADE).put("/admin/policy", json={"temperature": 1}).status_code == 400
    reset = client.as_(JADE).post("/admin/policy/reset").json()
    assert reset["values"] == reset["defaults"]
    assert client.as_(ALEX).put("/admin/policy", json={"sentimentThreshold": 0}).status_code == 403


def test_admin_sees_every_conversation_and_insights(client):
    answered, handed_off = start(client, MAYA), start(client, JORDAN)
    say(client, answered, "How long does a refund take?", MAYA)
    say(client, handed_off, "There is an unauthorized charge on my card", JORDAN)

    everything = client.as_(JADE).get("/admin/conversations").json()
    assert {c["id"] for c in everything} == {answered, handed_off}
    pending = client.as_(JADE).get("/admin/conversations", params={"status": "handoff_pending"}).json()
    assert [c["id"] for c in pending] == [handed_off]
    assert [c["id"] for c in client.as_(JADE).get("/admin/conversations", params={"q": "maya"}).json()] == [answered]

    insights = client.as_(JADE).get("/admin/insights").json()
    assert insights["conversations"]["total"] == 2
    assert insights["handoffs"]["byReason"] == [{"reason": "sensitive_topic", "label": "Sensitive topic", "count": 1}]
    assert insights["bot"]["outcomes"]["answered"] == 1
    assert {"grafana", "langfuse", "keycloakUsers"} <= set(insights["links"])


# ── Contract ─────────────────────────────────────────────────────────────────


def test_errors_use_the_message_shape_the_app_reads(client):
    conversation_id = start(client)
    missing = client.as_(MAYA).post(f"/me/conversations/{conversation_id}/messages", json={})
    assert missing.status_code == 400 and missing.json()["message"].startswith('"text"')
    assert client.as_(ALEX).get("/conversations/conv_nope").status_code == 404
    conflict = client.as_(ALEX).post(f"/conversations/{conversation_id}/handoff/accept")
    assert conflict.status_code == 409 and "Cannot accept a handoff" in conflict.json()["message"]


def test_metrics_and_openapi(client):
    say(client, start(client), "How long does a refund take?")
    metrics = client.as_(None).get("/metrics").text
    assert 'rag_bot_turns_total{outcome="answered",service="baton-api"}' in metrics
    assert 'http_requests_total{method="POST",route="customer_message"' in metrics
    assert "conversations{" in metrics
    schema = client.as_(None).get("/openapi.json").json()
    assert "/conversations/{conversation_id}/handoff/accept" in schema["paths"]
    assert "/admin/policy" in schema["paths"] and "/me/conversations/{conversation_id}/messages" in schema["paths"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
