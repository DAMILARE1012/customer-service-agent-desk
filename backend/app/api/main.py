"""Baton API — customer chat, the agent desk and admin, behind Keycloak sign-in.

    uv run baton-api      → http://localhost:8787  (OpenAPI docs at /docs, metrics at /metrics)

Who can call what (roles come from the Keycloak access token):

    customer   /me/conversations…            their own conversations, customer-safe view
    agent      /conversations…, /customers   the desk: queue, briefs, replies, handoff transitions
    admin      /admin/…                      agents, every conversation, handoff policy, insights

Agent and customer identities always come from the token, never from the request body.
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import auth
from app.admin import insights as admin_insights
from app.admin import policy as admin_policy
from app.api import schemas
from app.auth import Principal, current_admin, current_agent, current_customer, current_staff
from app.config import settings
from app.console import utf8_console
from app.conversation import engine, store
from app.conversation.constants import Status
from app.conversation.lifecycle import ApiError
from app.conversation.util import now_ms
from app.conversation.views import customer_summary, customer_view
from app.db import create_repository, repository, seed_demo_people, set_repository
from app.observability import online_eval
from app.observability.metrics import StateCollector, http_duration, http_requests, label, registry
from app.observability.tracing import init_tracing, shutdown
from app.rag.answerer import get_retriever

log = logging.getLogger("baton-api")

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
    tracing = init_tracing()
    repo = create_repository()
    await repo.start()
    set_repository(repo)
    if settings.seed_demo_data:
        await seed_demo_people(repo)
    loaded = await store.load()
    await admin_policy.load()

    log.info("Loading knowledge index and embedding model…")
    retriever = await asyncio.to_thread(get_retriever)
    # Models load lazily; one search now keeps that (several seconds) off the first customer's message.
    await asyncio.to_thread(lambda: retriever.search("warm up", top_k=1))
    online_eval.start()
    log.info(
        "Baton API ready · %s chunks · reranker %s · model %s · LLM %s · storage %s (%s conversations) · auth %s · tracing %s",
        retriever.size,
        settings.reranker_model or "off",
        settings.groq_model,
        "configured" if settings.groq_api_key else "MISSING (every question hands off)",
        "Postgres" if settings.database_url else "in memory",
        loaded,
        settings.keycloak_issuer,
        f"Langfuse at {settings.langfuse_base_url}" if tracing else "off",
    )
    yield
    await online_eval.stop()
    shutdown()  # flush pending traces and scores
    await repo.close()
    set_repository(None)


app = FastAPI(
    title="Baton API",
    version="0.3.0",
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
            "reranker": settings.reranker_model or None, "index": _index_state()}  # fmt: skip


# ── Everyone signed in ───────────────────────────────────────────────────────


@app.get("/me", response_model=schemas.Me, tags=["account"], name="me")
async def me(who: Principal = Depends(auth.principal)):
    """The signed-in user, their roles, and the profile row for each role they have."""
    profiles = {}
    if "customer" in who.roles and not who.is_staff:
        profiles["customer"] = await auth.current_customer(who)
    if "agent" in who.roles:
        profiles["agent"] = await auth.profile("agent", who)  # a disabled agent still sees their profile
    if "admin" in who.roles:
        profiles["admin"] = await auth.current_admin(who)
    user = {"sub": who.sub, "username": who.username, "name": who.name, "email": who.email, "roles": sorted(who.roles)}
    return {"user": user, **profiles}


# ── Customers: their own conversations ───────────────────────────────────────


def _snapshot(customer: dict) -> dict:
    """The customer profile as copied into a conversation or listed to staff (no identity-provider fields)."""
    return {k: v for k, v in customer.items() if k not in ("keycloakId", "lastSeenAt")}


@app.get("/me/conversations", response_model=list[schemas.CustomerConversationSummary], tags=["customer"], name="my_conversations")
def my_conversations(customer: dict = Depends(current_customer)):
    return [customer_summary(c) for c in store.conversations_of(customer["id"])]


@app.post("/me/conversations", response_model=schemas.CustomerConversation, tags=["customer"], name="start_conversation")
async def start_conversation(customer: dict = Depends(current_customer)):
    created = engine.create_conversation(_snapshot(customer), now_ms())
    return customer_view(await store.persist(created))


@app.get("/me/conversations/{conversation_id}", response_model=schemas.CustomerConversation, tags=["customer"], name="my_conversation")
def my_conversation(conversation_id: str, customer: dict = Depends(current_customer)):
    return customer_view(store.find_own_conversation(conversation_id, customer))


@app.post("/me/conversations/{conversation_id}/messages", response_model=schemas.CustomerConversation, tags=["customer"], name="customer_message")
async def customer_message(conversation_id: str, body: schemas.CustomerMessage, customer: dict = Depends(current_customer)):
    store.find_own_conversation(conversation_id, customer)  # ownership before queueing on the lock
    async with store.lock_for(conversation_id):  # one operation per conversation at a time, in order
        conversation = store.find_own_conversation(conversation_id, customer)
        await engine.receive_customer_message(conversation, body.text.strip(), now_ms())
        return customer_view(await store.persist(conversation))


# ── Agents: the desk ─────────────────────────────────────────────────────────


def _visible_to_agent(conversation: dict, agent: dict) -> bool:
    """Open conversations, plus resolved ones this agent handled."""
    return conversation["status"] != Status.RESOLVED or (conversation["assignee"] or {}).get("id") == agent["id"]


def _assigned_to(conversation: dict, agent: dict) -> None:
    if (conversation["assignee"] or {}).get("id") != agent["id"]:
        raise ApiError(403, "This conversation is assigned to another agent.")


def _check_capacity(agent: dict) -> None:
    if store.active_count(agent["id"]) >= agent["capacity"]:
        raise ApiError(409, f"You’re at capacity ({agent['capacity']} active chats). Resolve or return one first.")


@app.get("/customers", response_model=list[schemas.Customer], tags=["desk"], name="customers")
async def customers(_: Principal = Depends(current_staff)):
    return [_snapshot(c) for c in await repository().list_people("customer")]


@app.get("/conversations", response_model=list[schemas.ConversationSummary], tags=["desk"], name="conversations")
def conversations(agent: dict = Depends(current_agent)):
    return [store.to_summary(c) for c in store.all_conversations() if _visible_to_agent(c, agent)]


@app.get("/conversations/{conversation_id}", response_model=schemas.Conversation, tags=["desk"], name="conversation")
def conversation(conversation_id: str, _: Principal = Depends(current_staff)):
    return store.find_conversation(conversation_id)


@app.post("/conversations/{conversation_id}/agent-messages", response_model=schemas.Conversation, tags=["desk"], name="agent_message")
async def agent_message(conversation_id: str, body: schemas.AgentMessage, agent: dict = Depends(current_agent)):
    async with store.lock_for(conversation_id):
        current = store.find_conversation(conversation_id)
        engine.post_agent_message(current, agent, body.text.strip(), now_ms())
        return await store.persist(current)


@app.post("/conversations/{conversation_id}/handoff/accept", response_model=schemas.Conversation, tags=["handoff"], name="accept_handoff")
async def accept_handoff(conversation_id: str, agent: dict = Depends(current_agent)):
    async with store.lock_for(conversation_id):
        current = store.find_conversation(conversation_id)
        _check_capacity(agent)
        await engine.accept_handoff(current, agent, now_ms())
        return await store.persist(current)


@app.post("/conversations/{conversation_id}/handoff/return", response_model=schemas.Conversation, tags=["handoff"], name="return_to_bot")
async def return_to_bot(conversation_id: str, agent: dict = Depends(current_agent)):
    async with store.lock_for(conversation_id):
        current = store.find_conversation(conversation_id)
        _assigned_to(current, agent)
        engine.return_to_bot(current, agent, now_ms())
        return await store.persist(current)


@app.post("/conversations/{conversation_id}/takeover", response_model=schemas.Conversation, tags=["handoff"], name="take_over")
async def take_over(conversation_id: str, agent: dict = Depends(current_agent)):
    async with store.lock_for(conversation_id):
        current = store.find_conversation(conversation_id)
        _check_capacity(agent)
        await engine.take_over(current, agent, now_ms())
        return await store.persist(current)


@app.post("/conversations/{conversation_id}/resolve", response_model=schemas.Conversation, tags=["desk"], name="resolve")
async def resolve(conversation_id: str, agent: dict = Depends(current_agent)):
    async with store.lock_for(conversation_id):
        current = store.find_conversation(conversation_id)
        if current["status"] == Status.AGENT_ACTIVE:
            _assigned_to(current, agent)
        engine.resolve_conversation(current, agent, now_ms())
        return await store.persist(current)


# ── Admins ───────────────────────────────────────────────────────────────────


def _agent_overview(agent: dict) -> dict:
    return {**agent, "activeChats": store.active_count(agent["id"]), "signedInOnce": bool(agent.get("keycloakId"))}


@app.get("/admin/agents", response_model=list[schemas.AgentOverview], tags=["admin"], name="admin_agents")
async def admin_agents(_: dict = Depends(current_admin)):
    return [_agent_overview(a) for a in await repository().list_people("agent")]


@app.patch("/admin/agents/{agent_id}", response_model=schemas.AgentOverview, tags=["admin"], name="admin_update_agent")
async def admin_update_agent(agent_id: str, body: schemas.AgentUpdate, _: dict = Depends(current_admin)):
    updated = await repository().update_agent(agent_id, capacity=body.capacity, active=body.active)
    if updated is None:
        raise ApiError(404, f"Agent {agent_id} not found.")
    auth.forget_profile("agent", agent_id)  # the change applies to their next request
    return _agent_overview(updated)


@app.get("/admin/conversations", response_model=list[schemas.ConversationSummary], tags=["admin"], name="admin_conversations")
def admin_conversations(
    status: Status | None = None,
    agent_id: str | None = Query(None, alias="agentId"),
    q: str | None = Query(None, max_length=100, description="Customer name or subject contains"),
    _: dict = Depends(current_admin),
):
    term = (q or "").strip().lower()
    rows = [
        c for c in store.all_conversations()
        if (status is None or c["status"] == status)
        and (agent_id is None or (c["assignee"] or {}).get("id") == agent_id)
        and (not term or term in c["customer"]["name"].lower() or term in (c["subject"] or "").lower())
    ]  # fmt: skip
    return [store.to_summary(c) for c in sorted(rows, key=lambda c: c["updatedAt"], reverse=True)]


@app.get("/admin/policy", response_model=schemas.Policy, tags=["admin"], name="admin_policy")
def get_policy(_: dict = Depends(current_admin)):
    return admin_policy.current()


@app.put("/admin/policy", response_model=schemas.Policy, tags=["admin"], name="admin_update_policy")
async def update_policy(values: dict[str, float], admin: dict = Depends(current_admin)):
    return await admin_policy.update(values, admin)


@app.post("/admin/policy/reset", response_model=schemas.Policy, tags=["admin"], name="admin_reset_policy")
async def reset_policy(admin: dict = Depends(current_admin)):
    return await admin_policy.reset(admin)


@app.get("/admin/insights", tags=["admin"], name="admin_insights")
def get_insights(_: dict = Depends(current_admin)):
    return admin_insights.insights()


def run() -> None:
    import uvicorn

    utf8_console()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 0.0.0.0 so Prometheus (in Docker) can reach the API via host.docker.internal.
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=settings.server_port, log_level="info")


if __name__ == "__main__":
    run()
