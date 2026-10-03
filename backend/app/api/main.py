"""Baton API — customer chat, the agent desk and admin, behind Keycloak sign-in.

    uv run baton-api      → http://localhost:8787  (OpenAPI docs at /docs, metrics at /metrics)

Who can call what (roles come from the Keycloak access token):

    customer   /me/conversations…            their own conversations, customer-safe view
    agent      /conversations…, /customers   the desk: queue, briefs, replies, handoff transitions
    admin      /admin/…                      agents, customers, conversations, policy, review, audit

Agent and customer identities always come from the token, never from the request body. Conversations
are read from storage on every request and changed inside a locked transaction, so the API can run as
several processes behind a load balancer.
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import audit, auth, jobs, secrets, team, widget
from app.admin import insights as admin_insights
from app.admin import policy as admin_policy
from app.api import schemas
from app.auth import Principal, current_admin, current_agent, current_customer, current_staff
from app.config import settings
from app.console import utf8_console
from app.conversation import engine, store
from app.conversation.constants import ClosedReason, Status
from app.conversation.lifecycle import ApiError
from app.conversation.util import now_ms
from app.conversation.views import customer_summary, customer_view, session_outcome
from app.db import create_repository, repository, seed_demo_people, set_repository
from app.notify import alerts
from app.observability import online_eval
from app.observability.metrics import StateCollector, http_duration, http_requests, label, registry
from app.observability.tracing import init_tracing, shutdown
from app.privacy.erasure import erase_customer
from app.rag.answerer import get_retriever
from app.ratelimit import RateLimiter
from app.review import publish
from app.review.pipeline import run_review

log = logging.getLogger("baton-api")

# The widget is public: limit how fast one client can open sessions and one customer can send messages.
session_limiter = RateLimiter(settings.widget_sessions_per_hour, 3600, "Too many new chat sessions from this network. Try again later.")
message_limiter = RateLimiter(settings.widget_messages_per_minute, 60, "You’re sending messages too quickly — give it a moment.")

# ── Index freshness for the gauges (ingestion runs as a separate process) ────
_index_cache = {"at": 0.0, "value": {"chunks": 0, "builtAt": None, "checkedAt": {}}}


def _index_state() -> dict:
    if time.monotonic() - _index_cache["at"] < 15:
        return _index_cache["value"]
    try:
        manifest = json.loads((settings.index_path / "manifest.json").read_text(encoding="utf-8"))
        value = {
            "chunks": manifest["count"] - manifest.get("duplicates", 0),
            "builtAt": manifest["builtAt"],
            "checkedAt": {source: s["checkedAt"] for source, s in manifest.get("sources", {}).items()},
        }
    except (OSError, KeyError, ValueError):
        value = {"chunks": 0, "builtAt": None, "checkedAt": {}}
    _index_cache.update(at=time.monotonic(), value=value)
    return value


registry.register(StateCollector(store.desk_stats, _index_state))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(secrets.load)  # first: the Langfuse, Groq and widget secrets may live in Vault
    tracing = init_tracing()
    repo = create_repository()
    await repo.start()
    set_repository(repo)
    if settings.seed_demo_data:
        await seed_demo_people(repo)
    await admin_policy.load()
    await team.load_hours()

    log.info("Loading knowledge index and embedding model…")
    retriever = await asyncio.to_thread(get_retriever)
    # Models load lazily; one search now keeps that (several seconds) off the first customer's message.
    await asyncio.to_thread(lambda: retriever.search("warm up", top_k=1))
    online_eval.start()
    background = jobs.start()
    log.info(
        "Baton API ready · %s chunks · reranker %s · model %s · LLM %s · storage %s · auth %s · retention %s · tracing %s",
        retriever.size,
        settings.reranker_model or "off",
        settings.groq_model,
        "configured" if settings.groq_api_key else "MISSING (every question hands off)",
        "Postgres" if settings.database_url else "in memory",
        settings.keycloak_issuer,
        f"{settings.retention_days} days" if settings.retention_days else "forever",
        f"Langfuse at {settings.langfuse_base_url}" if tracing else "off",
    )
    yield
    await jobs.stop(background)
    await online_eval.stop()
    shutdown()  # flush pending traces and scores
    await repo.close()
    set_repository(None)


app = FastAPI(
    title="Baton API",
    version="0.4.0",
    description="Baton — a customer-service RAG assistant that knows when to pass the baton to a human.",
    lifespan=lifespan,
    responses={
        400: {"model": schemas.ErrorResponse},
        401: {"model": schemas.ErrorResponse},
        403: {"model": schemas.ErrorResponse},
        404: {"model": schemas.ErrorResponse},
        409: {"model": schemas.ErrorResponse},
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origin.split(",")],
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Errors: always {"message": …}, the shape the web app reads ───────────────


@app.exception_handler(ApiError)
async def _api_error(_: Request, error: ApiError):
    headers = {"WWW-Authenticate": 'Bearer realm="baton"'} if error.status == 401 else None
    return JSONResponse({"message": error.message}, status_code=error.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, error: RequestValidationError):
    first = error.errors()[0] if error.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "body"
    return JSONResponse({"message": f'"{field}" {first.get("msg", "is invalid").lower()}.'}, status_code=400)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, error: StarletteHTTPException):
    message = f"No route for {request.method} {request.url.path}" if error.status_code == 404 else str(error.detail)
    return JSONResponse({"message": message}, status_code=error.status_code)


# ── HTTP metrics (route names, never raw paths) ──────────────────────────────


@app.middleware("http")
async def _metrics(request: Request, call_next):
    if request.url.path in ("/metrics", "/health") or request.method == "OPTIONS":
        return await call_next(request)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        name = getattr(route, "name", None) or "unmatched"
        http_duration.labels(**label(method=request.method, route=name)).observe(time.perf_counter() - started)
        http_requests.labels(**label(method=request.method, route=name, status=str(status))).inc()


# Ops endpoints are unauthenticated: bind the API to localhost or put them behind your proxy in production.
@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@app.get("/health", tags=["ops"])
def health():
    return {"ok": True, "llmConfigured": bool(settings.groq_api_key), "tracing": settings.langfuse_enabled,
            "storage": "postgres" if settings.database_url else "memory", "authIssuer": settings.keycloak_issuer,
            "reranker": settings.reranker_model or None, "secrets": secrets.source, "index": _index_state()}  # fmt: skip


# ── Everyone signed in ───────────────────────────────────────────────────────


def privacy_notice() -> dict:
    days = settings.retention_days
    kept = f"for {days} days" if days else "until you ask us to delete them"
    text = settings.privacy_notice or (
        f"Conversations are kept {kept} so our support team can help you, then their text is deleted. "
        "Team members can read this chat; personal details are removed before we use conversations to improve our help centre."
    )
    return {"retentionDays": days, "notice": text}


@app.get("/me", response_model=schemas.Me, tags=["account"], name="me")
async def me(who: Principal = Depends(auth.principal)):
    """Who this token belongs to: a widget customer, or a staff member with their agent / admin profiles."""
    if who.is_customer:
        customer = await auth.current_customer(who)
        user = {"sub": who.sub, "username": customer["id"], "name": customer["name"], "email": customer.get("email"), "roles": ["customer"]}
        return {"user": user, "customer": customer, "privacy": privacy_notice()}
    profiles = {}
    if "agent" in who.roles:
        profiles["agent"] = await auth.profile("agent", who)  # a disabled agent still sees their profile
    if "admin" in who.roles:
        profiles["admin"] = await auth.current_admin(who)
    user = {"sub": who.sub, "username": who.username, "name": who.name, "email": who.email, "roles": sorted(who.roles)}
    return {"user": user, **profiles}


# ── The chat widget: sessions for customers (who never sign in to Baton) ──────


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.post("/widget/session", response_model=schemas.WidgetSession, tags=["widget"], name="widget_session")
async def widget_session(request: Request, body: schemas.WidgetSessionRequest = Body(default_factory=schemas.WidgetSessionRequest)):
    """Open a chat session from the widget. Without `identity` the customer is an anonymous visitor; with an
    identity token signed by your website's backend they're linked to their customer profile."""
    session_limiter.check(_client_ip(request))
    if body.identity:
        claims = widget.verify_identity(body.identity)
        customer = await repository().upsert_external_customer(str(claims["sub"]), claims.get("name"), claims.get("email"))
        session = widget.issue_session(customer, identified=True)
    else:
        customer = await repository().create_visitor()
        session = widget.issue_session(customer, identified=False)
    return {**session, "customer": {"id": customer["id"], "name": customer["name"]}}


def _demo_only() -> None:
    if not settings.widget_demo_identity:
        raise ApiError(404, "Not found.")


@app.get("/widget/demo-customers", tags=["widget"], name="widget_demo_customers", include_in_schema=False)
async def widget_demo_customers():
    """Local demo only: the customers a demo store can pretend to have signed in."""
    _demo_only()
    return [{"id": c["id"], "name": c["name"], "tier": c["tier"]} for c in await repository().list_people("customer") if not c.get("isVisitor")]


@app.post("/widget/demo-identity", tags=["widget"], name="widget_demo_identity", include_in_schema=False)
async def widget_demo_identity(body: schemas.DemoIdentityRequest):
    """Local demo only: signs an identity token the way your website's backend would for a signed-in customer."""
    _demo_only()
    customer = await repository().get_person("customer", body.customer_id)
    if customer is None or customer.get("isVisitor"):
        raise ApiError(404, f"Customer {body.customer_id} not found.")
    return {"identity": widget.sign_demo_identity(customer)}


# ── Customers: their own conversations ───────────────────────────────────────


def _snapshot(customer: dict) -> dict:
    """The customer profile as copied into a conversation or listed to staff (no identity-provider fields)."""
    return {k: v for k, v in customer.items() if k not in ("keycloakId", "lastSeenAt")}


@app.get("/me/conversations", response_model=list[schemas.CustomerConversationSummary], tags=["customer"], name="my_conversations")
async def my_conversations(customer: dict = Depends(current_customer)):
    return [customer_summary(c) for c in await store.heads(customer_id=customer["id"])]


@app.post("/me/conversations", response_model=schemas.CustomerConversation, tags=["customer"], name="start_conversation")
async def start_conversation(
    body: schemas.StartConversation = Body(default_factory=schemas.StartConversation), customer: dict = Depends(current_customer)
):
    """Start a session — or resume the live one: a customer has at most one open conversation, so a
    page reload or a second tab never strands them outside a queue they're already waiting in."""
    live = await store.open_conversation_of(customer["id"])
    if live:
        return await _customer_view(await store.get(live["id"]))
    follow_up = None
    if body.follow_up_of:
        previous = await store.get_own(body.follow_up_of, customer)
        if previous["status"] != Status.RESOLVED:
            raise ApiError(409, "You can only follow up on a conversation that has ended.")
        follow_up = session_outcome(previous)  # for the agent; the bot starts with a clean slate
    created = engine.create_conversation(_snapshot(customer), now_ms(), follow_up)
    try:
        await store.create(created)
    except store.AlreadyOpen:  # another tab or process started one a moment ago: join it
        live = await store.open_conversation_of(customer["id"])
        return await _customer_view(await store.get(live["id"]))
    return await _customer_view(created)


@app.get("/me/conversations/{conversation_id}", response_model=schemas.CustomerConversation, tags=["customer"], name="my_conversation")
async def my_conversation(conversation_id: str, customer: dict = Depends(current_customer)):
    conversation = await store.get_own(conversation_id, customer)
    if conversation["status"] != Status.RESOLVED:
        await store.mark_seen(conversation_id)  # presence: the chat window is open
    return await _customer_view(conversation)


@app.post("/me/conversations/{conversation_id}/end", response_model=schemas.CustomerConversation, tags=["customer"], name="end_conversation")
async def end_conversation(conversation_id: str, customer: dict = Depends(current_customer)):
    async with store.own_transaction(conversation_id, customer) as conversation:
        engine.close_conversation(conversation, ClosedReason.ENDED_BY_CUSTOMER, now_ms())
    return await _customer_view(conversation)


@app.post("/me/conversations/{conversation_id}/messages", response_model=schemas.CustomerConversation, tags=["customer"], name="customer_message")
async def customer_message(conversation_id: str, body: schemas.CustomerMessage, customer: dict = Depends(current_customer)):
    message_limiter.check(customer["id"])
    # Locked only to record the message and to save the reply — never during the LLM call (see engine.py).
    return await _customer_view(await engine.receive_customer_message(conversation_id, customer, body.text.strip()))


@app.post("/me/conversations/{conversation_id}/contact", response_model=schemas.CustomerConversation, tags=["customer"], name="leave_contact")
async def leave_contact(conversation_id: str, body: schemas.ContactRequest, customer: dict = Depends(current_customer)):
    """An email for the reply, in case the customer has left the chat when an agent answers."""
    email = team.valid_email(body.email)
    async with store.own_transaction(conversation_id, customer) as conversation:
        engine.leave_contact(conversation, email, now_ms())
    return await _customer_view(conversation)


async def _customer_view(conversation: dict) -> dict:
    return {**customer_view(conversation), "waiting": await team.waiting_info(conversation, now_ms())}


_background: set[asyncio.Task] = set()


def _in_background(coro) -> None:
    """Fire and forget (e.g. an email), keeping a reference so the task isn't garbage-collected mid-flight."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


# ── Agents: the desk ─────────────────────────────────────────────────────────


def _assigned_to(conversation: dict, agent: dict) -> None:
    if (conversation["assignee"] or {}).get("id") != agent["id"]:
        raise ApiError(403, "This conversation is assigned to another agent.")


def _staff_actor(who: Principal) -> dict:
    return audit.actor({"sub": who.sub, "name": who.name}, "admin" if "admin" in who.roles else "agent")


@app.get("/customers", response_model=list[schemas.Customer], tags=["desk"], name="customers")
async def customers(_: Principal = Depends(current_staff)):
    return [_snapshot(c) for c in await repository().list_people("customer")]


@app.get("/customers/{customer_id}/conversations", response_model=list[schemas.SessionOutcome], tags=["desk"], name="customer_timeline")
async def customer_timeline(customer_id: str, who: Principal = Depends(current_staff)):
    """Every session this customer has had, most recent first — what agents see instead of the bot
    carrying old conversations forward."""
    await audit.record(_staff_actor(who), "customer.timeline.view", customer_id=customer_id)
    return [session_outcome(c) for c in await store.heads(customer_id=customer_id, with_handoffs=True)]


@app.get("/conversations", response_model=list[schemas.ConversationSummary], tags=["desk"], name="conversations")
async def conversations(agent: dict = Depends(current_agent)):
    return [store.to_summary(c) for c in await store.heads(visible_to_agent=agent["id"])]


@app.get("/conversations/{conversation_id}", response_model=schemas.Conversation, tags=["desk"], name="conversation")
async def conversation(conversation_id: str, who: Principal = Depends(current_staff)):
    found = await store.get(conversation_id)
    await audit.record(_staff_actor(who), "conversation.view", conversation_id=conversation_id, customer_id=found["customer"]["id"])
    return found


@app.post("/conversations/{conversation_id}/agent-messages", response_model=schemas.Conversation, tags=["desk"], name="agent_message")
async def agent_message(conversation_id: str, body: schemas.AgentMessage, agent: dict = Depends(current_agent)):
    text = body.text.strip()
    async with store.transaction(conversation_id) as current:
        engine.post_agent_message(current, agent, text, now_ms())
    _in_background(alerts.email_reply_if_away(current, agent["name"], text))  # if the customer has left the chat
    return current


@app.put("/me/availability", response_model=schemas.Agent, tags=["desk"], name="set_availability")
async def set_availability(body: schemas.AvailabilityUpdate, agent: dict = Depends(current_agent)):
    """The desk's Online / Away switch: Away agents don't count as someone available to customers."""
    updated = await repository().update_agent(agent["id"], available=body.available)
    auth.forget_profile("agent", agent["id"])
    team.forget_status()
    return updated


@app.post("/conversations/{conversation_id}/handoff/accept", response_model=schemas.Conversation, tags=["handoff"], name="accept_handoff")
async def accept_handoff(conversation_id: str, agent: dict = Depends(current_agent)):
    return await engine.accept_handoff(conversation_id, agent)  # capacity is checked under the agent's lock


@app.post("/conversations/{conversation_id}/handoff/return", response_model=schemas.Conversation, tags=["handoff"], name="return_to_bot")
async def return_to_bot(conversation_id: str, agent: dict = Depends(current_agent)):
    async with store.transaction(conversation_id) as current:
        _assigned_to(current, agent)
        engine.return_to_bot(current, agent, now_ms())
    return current


@app.post("/conversations/{conversation_id}/takeover", response_model=schemas.Conversation, tags=["handoff"], name="take_over")
async def take_over(conversation_id: str, agent: dict = Depends(current_agent)):
    return await engine.take_over(conversation_id, agent)


@app.post("/conversations/{conversation_id}/resolve", response_model=schemas.Conversation, tags=["desk"], name="resolve")
async def resolve(conversation_id: str, agent: dict = Depends(current_agent)):
    async with store.transaction(conversation_id) as current:
        if current["status"] == Status.AGENT_ACTIVE:
            _assigned_to(current, agent)
        engine.resolve_conversation(current, agent, now_ms())
    return current


# ── Admins ───────────────────────────────────────────────────────────────────


async def _agent_overview(agent: dict) -> dict:
    return {**agent, "activeChats": await store.active_count(agent["id"]), "signedInOnce": bool(agent.get("keycloakId"))}


@app.get("/admin/agents", response_model=list[schemas.AgentOverview], tags=["admin"], name="admin_agents")
async def admin_agents(_: dict = Depends(current_admin)):
    return [await _agent_overview(a) for a in await repository().list_people("agent")]


@app.patch("/admin/agents/{agent_id}", response_model=schemas.AgentOverview, tags=["admin"], name="admin_update_agent")
async def admin_update_agent(agent_id: str, body: schemas.AgentUpdate, admin: dict = Depends(current_admin)):
    updated = await repository().update_agent(agent_id, capacity=body.capacity, active=body.active)
    if updated is None:
        raise ApiError(404, f"Agent {agent_id} not found.")
    auth.forget_profile("agent", agent_id)  # this process now; the others within the profile cache's 30 s
    await audit.record(audit.actor(admin, "admin"), "agent.update", detail={"agentId": agent_id, **body.model_dump(exclude_none=True)})
    return await _agent_overview(updated)


@app.get("/admin/customers", response_model=list[schemas.CustomerOverview], tags=["admin"], name="admin_customers")
async def admin_customers(_: dict = Depends(current_admin)):
    counts: dict[str, int] = {}
    for c in await store.heads(limit=100_000):
        counts[c["customer"]["id"]] = counts.get(c["customer"]["id"], 0) + 1
    return [{**_snapshot(c), "conversations": counts.get(c["id"], 0), "signedInOnce": bool(c.get("keycloakId")), "lastSeenAt": c.get("lastSeenAt")}
            for c in await repository().list_people("customer")]  # fmt: skip


@app.post("/admin/customers/{customer_id}/erase", response_model=schemas.ErasureReport, tags=["admin"], name="admin_erase_customer")
async def admin_erase_customer(customer_id: str, body: schemas.EraseRequest, admin: dict = Depends(current_admin)):
    """Delete everything about one customer: profile, conversations, traces and Keycloak account."""
    if body.confirm != customer_id:
        raise ApiError(400, "Confirm the erasure by sending the customer's id as `confirm`.")
    report = await erase_customer(customer_id)
    detail = {"conversations": report["conversations"], "traces": report["traces"].get("deleted", 0), "identityDeleted": report["identity"]["deleted"]}
    await audit.record(audit.actor(admin, "admin"), "customer.erase", customer_id=customer_id, detail=detail)
    return report


@app.get("/admin/conversations", response_model=list[schemas.ConversationSummary], tags=["admin"], name="admin_conversations")
async def admin_conversations(
    status: Status | None = None,
    agent_id: str | None = Query(None, alias="agentId"),
    q: str | None = Query(None, max_length=100, description="Customer name or subject contains"),
    _: dict = Depends(current_admin),
):
    return [store.to_summary(c) for c in await store.heads(status=status, assignee_id=agent_id, q=q)]


@app.get("/admin/policy", response_model=schemas.Policy, tags=["admin"], name="admin_policy")
def get_policy(_: dict = Depends(current_admin)):
    return admin_policy.current()


@app.put("/admin/policy", response_model=schemas.Policy, tags=["admin"], name="admin_update_policy")
async def update_policy(values: dict[str, float], admin: dict = Depends(current_admin)):
    result = await admin_policy.update(values, admin)
    await audit.record(audit.actor(admin, "admin"), "policy.update", detail=values)
    return result


@app.post("/admin/policy/reset", response_model=schemas.Policy, tags=["admin"], name="admin_reset_policy")
async def reset_policy(admin: dict = Depends(current_admin)):
    result = await admin_policy.reset(admin)
    await audit.record(audit.actor(admin, "admin"), "policy.reset")
    return result


async def _team_status() -> dict:
    current = await team.status(now_ms())
    return {"hours": team.business_hours(), "openNow": current["open"], "agentsOnline": current["agentsOnline"],
            "available": current["available"], "backAtText": current["backAtText"]}  # fmt: skip


@app.get("/admin/business-hours", response_model=schemas.TeamStatus, tags=["admin"], name="admin_business_hours")
async def get_business_hours(_: dict = Depends(current_admin)):
    team.forget_status()
    return await _team_status()


@app.put("/admin/business-hours", response_model=schemas.TeamStatus, tags=["admin"], name="admin_update_business_hours")
async def update_business_hours(body: schemas.BusinessHours, admin: dict = Depends(current_admin)):
    await team.save_hours(body.model_dump(), admin["name"])
    await audit.record(audit.actor(admin, "admin"), "business_hours.update", detail=body.model_dump())
    return await _team_status()


@app.get("/admin/insights", tags=["admin"], name="admin_insights")
async def get_insights(_: dict = Depends(current_admin)):
    return admin_insights.insights(await store.heads(with_handoffs=True, limit=100_000))


# ── Admin: review queue ──


def _public_item(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "embedding"}


async def _review_item(item_id: str) -> dict:
    item = await repository().get_review_item(item_id)
    if item is None:
        raise ApiError(404, f"Review item {item_id} not found.")
    return item


@app.get("/admin/review", response_model=list[schemas.ReviewItem], tags=["admin"], name="admin_review_items")
async def admin_review_items(kind: str | None = None, status: str | None = None, _: dict = Depends(current_admin)):
    return [_public_item(i) for i in await repository().list_review_items(kind, status)]


@app.post("/admin/review/run", tags=["admin"], name="admin_review_run")
async def admin_review_run(admin: dict = Depends(current_admin)):
    report = await run_review()
    await audit.record(audit.actor(admin, "admin"), "review.run", detail=report)
    return report


@app.patch("/admin/review/{item_id}", response_model=schemas.ReviewItem, tags=["admin"], name="admin_review_update")
async def admin_review_update(item_id: str, body: schemas.ReviewUpdate, _: dict = Depends(current_admin)):
    item = await _review_item(item_id)
    if item["status"] in ("published", "approved"):
        raise ApiError(409, "This item has already been published or approved.")
    item.update(body.model_dump(exclude_none=True))
    return _public_item(await repository().save_review_item(item))


@app.post("/admin/review/{item_id}/publish", response_model=schemas.ReviewItem, tags=["admin"], name="admin_review_publish")
async def admin_review_publish(item_id: str, admin: dict = Depends(current_admin)):
    item = await publish.publish_article(await _review_item(item_id), admin["name"])
    await audit.record(audit.actor(admin, "admin"), "review.publish", detail={"itemId": item_id, "path": item["publishedPath"]})
    return _public_item(item)


@app.post("/admin/review/{item_id}/approve", response_model=schemas.ReviewItem, tags=["admin"], name="admin_review_approve")
async def admin_review_approve(item_id: str, admin: dict = Depends(current_admin)):
    item = await publish.approve_test_question(await _review_item(item_id), admin["name"])
    await audit.record(audit.actor(admin, "admin"), "review.approve", detail={"itemId": item_id})
    return _public_item(item)


@app.post("/admin/review/{item_id}/reject", response_model=schemas.ReviewItem, tags=["admin"], name="admin_review_reject")
async def admin_review_reject(item_id: str, admin: dict = Depends(current_admin)):
    item = await _review_item(item_id)
    item.update(status="rejected", reviewedBy=admin["name"])
    await audit.record(audit.actor(admin, "admin"), "review.reject", detail={"itemId": item_id})
    return _public_item(await repository().save_review_item(item))


@app.post("/admin/knowledge/reindex", tags=["admin"], name="admin_reindex")
async def admin_reindex(admin: dict = Depends(current_admin)):
    """Index new and changed help-centre articles now. Running API processes pick the new index up within a minute."""
    report = await publish.reindex()
    await audit.record(audit.actor(admin, "admin"), "knowledge.reindex", detail=report)
    return report


# ── Admin: audit log ──


@app.get("/admin/audit", response_model=list[schemas.AuditEntry], tags=["admin"], name="admin_audit")
async def admin_audit(
    actor_id: str | None = Query(None, alias="actorId"),
    conversation_id: str | None = Query(None, alias="conversationId"),
    action: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    _: dict = Depends(current_admin),
):
    return await repository().list_audit(actor_id=actor_id, conversation_id=conversation_id, action=action, limit=limit)


def run() -> None:
    import uvicorn

    utf8_console()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 0.0.0.0 so Prometheus (in Docker) can reach the API via host.docker.internal, and so it works in a container.
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=settings.server_port, workers=settings.api_workers, log_level="info")


if __name__ == "__main__":
    run()
