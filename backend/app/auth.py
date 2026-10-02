"""Authentication and authorization for the API. Two kinds of bearer token:

    staff      Keycloak access tokens (RS256), verified locally against the realm's published keys —
               issuer, audience (baton-api), expiry. Realm roles: `agent` (the desk), `admin` (admin).
    customers  widget session tokens (HS256, issuer "baton-widget") from POST /widget/session — see
               app/widget.py. Customers never sign in to Baton; they only reach their own conversations.

The token's issuer picks the verifier, and each verifier pins its own algorithm, so one kind can never be
passed off as the other.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import widget
from app.config import settings
from app.conversation.lifecycle import ApiError
from app.db import Identity, repository

STAFF_ROLES = ("agent", "admin")


@dataclass(frozen=True)
class Principal:
    sub: str
    username: str
    name: str
    email: str | None
    email_verified: bool
    roles: frozenset[str]
    customer_id: str | None = None  # widget sessions only

    @property
    def is_customer(self) -> bool:
        return self.customer_id is not None

    @property
    def is_staff(self) -> bool:
        return bool(self.roles & {"agent", "admin"})

    @property
    def identity(self) -> Identity:
        return Identity(sub=self.sub, name=self.name, email=self.email, email_verified=self.email_verified)


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, jwks_url: str | None = None) -> None:
        self.issuer, self.audience = issuer, audience
        # Keys are cached and refetched when a token names an unknown key id (Keycloak key rotation).
        self.keys = jwt.PyJWKClient(jwks_url or f"{issuer}/protocol/openid-connect/certs", cache_keys=True, lifespan=3600, timeout=5)

    def verify(self, token: str) -> Principal:
        key = self.keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=10,
        )
        roles = frozenset(claims.get("realm_access", {}).get("roles", [])) & frozenset(STAFF_ROLES)
        username = claims.get("preferred_username") or claims["sub"]
        return Principal(
            sub=claims["sub"],
            username=username,
            name=claims.get("name") or username,
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified")),
            roles=roles,
        )


@lru_cache(maxsize=1)
def verifier() -> TokenVerifier:
    return TokenVerifier(settings.keycloak_issuer, settings.keycloak_audience, settings.keycloak_jwks_url)


_bearer = HTTPBearer(auto_error=False, description="Keycloak access token for the baton-api audience")


def widget_principal(token: str) -> Principal:
    claims = widget.verify_session(token)
    return Principal(sub=claims["sub"], username=claims["sub"], name=claims.get("name") or "Customer", email=None,
                     email_verified=False, roles=frozenset({"customer"}), customer_id=claims["sub"])  # fmt: skip


def verify_token(token: str) -> Principal:
    issuer = jwt.decode(token, options={"verify_signature": False}).get("iss")  # only to choose the verifier
    return widget_principal(token) if issuer == widget.ISSUER else verifier().verify(token)


async def principal(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if credentials is None:
        raise ApiError(401, "Sign in required.")
    try:
        # The first call per key fetches the realm's public keys over HTTP; keep it off the event loop.
        return await asyncio.to_thread(verify_token, credentials.credentials)
    except jwt.PyJWKClientConnectionError as error:
        raise ApiError(503, "Can't reach the identity provider to verify your sign-in.") from error
    except jwt.PyJWTError as error:
        raise ApiError(401, f"Invalid or expired token: {error}") from error


# ── Profiles (the customers / agents / admins tables), refreshed at most every few minutes ──

# Short, so an admin disabling an agent takes effect quickly in every API process.
_PROFILE_TTL_S = 30
_profiles: dict[tuple[str, str], tuple[float, dict]] = {}
# A freshly signed-in app fires several requests at once; only one of them should create the row.
_profile_locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)


async def profile(kind: str, who: Principal) -> dict:
    key = (kind, who.sub)
    async with _profile_locks[key]:
        cached = _profiles.get(key)
        if cached and time.monotonic() - cached[0] < _PROFILE_TTL_S:
            return cached[1]
        row = await repository().upsert_person(kind, who.identity)
        _profiles[key] = (time.monotonic(), row)
        return row


def forget_profile(kind: str, person_id: str) -> None:
    """Drop a cached profile after an admin changes it (capacity, active)."""
    for key, (_, profile) in list(_profiles.items()):
        if key[0] == kind and profile["id"] == person_id:
            del _profiles[key]


async def current_customer(who: Principal = Depends(principal)) -> dict:
    """The customer behind a widget session. Staff tokens can't act as customers."""
    if not who.is_customer:
        raise ApiError(403, "Customers chat through the website widget; staff accounts can't.")
    key = ("customer", who.customer_id)
    cached = _profiles.get(key)
    if cached and time.monotonic() - cached[0] < _PROFILE_TTL_S:
        return cached[1]
    customer = await repository().get_person("customer", who.customer_id)
    if customer is None:  # erased since the session started
        raise ApiError(401, "This chat session has ended. Start a new one.")
    _profiles[key] = (time.monotonic(), customer)
    return customer


async def current_agent(who: Principal = Depends(principal)) -> dict:
    if "agent" not in who.roles:
        raise ApiError(403, "This needs the agent role.")
    agent = await profile("agent", who)
    if not agent["active"]:
        raise ApiError(403, "Your agent account is disabled. Ask an admin to re-enable it.")
    return agent


async def current_admin(who: Principal = Depends(principal)) -> dict:
    if "admin" not in who.roles:
        raise ApiError(403, "This needs the admin role.")
    return await profile("admin", who)


async def current_staff(who: Principal = Depends(principal)) -> Principal:
    if not who.is_staff:
        raise ApiError(403, "This needs the agent or admin role.")
    return who
