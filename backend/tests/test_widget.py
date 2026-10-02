"""The chat widget: anonymous visitors, customers your website vouches for, and the real token path
(no dependency override — the API verifies the widget session token itself)."""

import time

import jwt

from app.api import main
from app.config import settings
from tests.support import ALEX, JADE


def session(client, identity=None):
    res = client.as_(None).post("/widget/session", json={"identity": identity} if identity else {})
    assert res.status_code == 200, res.text
    return res.json()


def as_widget(client, token):
    """Requests carrying the real widget token, verified by the API (no test override)."""
    main.app.dependency_overrides.pop(main.auth.principal, None)
    client.http.headers["Authorization"] = f"Bearer {token}"
    return client.http


def identity_token(sub="shop-user-42", email="river@example.org", name="River Stone", lifetime=600, secret=None):
    now = int(time.time())
    claims = {"sub": sub, "email": email, "name": name, "iat": now, "exp": now + lifetime}
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret or settings.widget_identity_secret, algorithm="HS256")


def test_a_visitor_chats_without_signing_in(client):
    visitor = session(client)
    assert visitor["kind"] == "visitor" and visitor["customer"]["name"].startswith("Visitor ")
    http = as_widget(client, visitor["token"])
    me = http.get("/me").json()
    assert me["user"]["roles"] == ["customer"] and me["customer"]["isVisitor"] is True and me["privacy"]["notice"]

    conversation = http.post("/me/conversations").json()
    reply = http.post(f"/me/conversations/{conversation['id']}/messages", json={"text": "How long does a refund take?"}).json()
    assert reply["messages"][-1]["text"] == "Refunds take 2 business days."
    assert [c["id"] for c in http.get("/me/conversations").json()] == [conversation["id"]]
    # A widget token is for the customer routes only.
    assert http.get("/conversations").status_code == 403 and http.get("/admin/agents").status_code == 403


def test_your_website_vouches_for_a_signed_in_customer(client):
    river = session(client, identity_token())
    assert river["kind"] == "identified" and river["customer"]["name"] == "River Stone"
    again = session(client, identity_token(name="River S."))  # same user id → same profile, name refreshed
    assert again["customer"]["id"] == river["customer"]["id"] and again["customer"]["name"] == "River S."

    # A seeded CRM profile is claimed by email the first time the website identifies that customer.
    maya = session(client, identity_token(sub="shop-user-7", email="maya.chen@example.com", name="Maya Chen"))
    assert maya["customer"]["id"] == "cus_maya"
    profile = as_widget(client, maya["token"]).get("/me").json()["customer"]
    assert profile["tier"] == "plus" and profile["externalId"] == "shop-user-7" and profile["isVisitor"] is False


def test_forged_or_long_lived_identities_are_rejected(client):
    assert client.as_(None).post("/widget/session", json={"identity": identity_token(secret="not-the-shared-secret-at-all-0000")}).status_code == 401
    assert client.as_(None).post("/widget/session", json={"identity": identity_token(lifetime=3 * 86400)}).status_code == 401
    assert client.as_(None).post("/widget/session", json={"identity": identity_token(lifetime=-120)}).status_code == 401
    # A widget token signed with the wrong secret, or presented as if from Keycloak, gets nowhere.
    forged = jwt.encode({"iss": "baton-widget", "aud": "baton-api", "sub": "cus_maya", "iat": int(time.time()), "exp": int(time.time()) + 60},
                        "guessed-secret-guessed-secret-1234", algorithm="HS256")  # fmt: skip
    assert as_widget(client, forged).get("/me").status_code == 401


def test_staff_tokens_cant_act_as_customers(client):
    assert client.as_(ALEX).post("/me/conversations").status_code == 403
    assert client.as_(JADE).get("/me/conversations").status_code == 403


def test_demo_identity_is_off_unless_enabled(client, monkeypatch):
    demo = client.as_(None).post("/widget/demo-identity", json={"customerId": "cus_jordan"}).json()
    assert session(client, demo["identity"])["customer"]["id"] == "cus_jordan"
    assert any(c["id"] == "cus_jordan" for c in client.as_(None).get("/widget/demo-customers").json())
    monkeypatch.setattr(settings, "widget_demo_identity", False)
    assert client.as_(None).post("/widget/demo-identity", json={"customerId": "cus_jordan"}).status_code == 404
    assert client.as_(None).get("/widget/demo-customers").status_code == 404


def test_rate_limits_protect_the_public_widget(client, monkeypatch):
    monkeypatch.setattr(main.session_limiter, "limit", 2)
    session(client)
    session(client)
    assert client.as_(None).post("/widget/session", json={}).status_code == 429

    main.session_limiter.reset()
    monkeypatch.setattr(main.message_limiter, "limit", 2)
    http = as_widget(client, session(client)["token"])
    conversation = http.post("/me/conversations").json()
    codes = [http.post(f"/me/conversations/{conversation['id']}/messages", json={"text": "hello there"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_the_widget_needs_its_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "widget_signing_secret", "")
    res = client.as_(None).post("/widget/session", json={})
    assert res.status_code == 503 and "WIDGET_SIGNING_SECRET" in res.json()["message"]
