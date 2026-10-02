"""Authentication (Keycloak access tokens) and authorization (realm roles) for the API.

Every request carries `Authorization: Bearer <access token>` from the web app's Keycloak login. The
token is verified locally — signature against the realm's published keys, issuer, audience (baton-api)
and expiry — so no call to Keycloak is made per request. Roles come from `realm_access.roles`:

    customer   their own conversations only, through a customer-safe view
    agent      the desk: queue, handoff briefs, replies, resolve
    admin      agents, every conversation, handoff policy, insights

Staff accounts (agent or admin) never get a customer profile, even if Keycloak's default role gives
them `customer`: a person is either served by the desk or works on it.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.conversation.lifecycle import ApiError
from app.db import Identity, repository

ROLES = ("customer", "agent", "admin")


@dataclass(frozen=True)
class Principal:
    sub: str
    username: str
    name: str
    email: str | None
    email_verified: bool
    roles: frozenset[str]

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
        roles = frozenset(claims.get("realm_access", {}).get("roles", [])) & frozenset(ROLES)
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


async def principal(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if credentials is None:
        raise ApiError(401, "Sign in required.")
    try:
        # The first call per key fetches the realm's public keys over HTTP; keep it off the event loop.
        return await asyncio.to_thread(verifier().verify, credentials.credentials)
    except jwt.PyJWKClientConnectionError as error:
        raise ApiError(503, "Can't reach the identity provider to verify your sign-in.") from error
    except jwt.PyJWTError as error:
        raise ApiError(401, f"Invalid or expired token: {error}") from error


# ── Profiles (the customers / agents / admins tables), refreshed at most every few minutes ──

_PROFILE_TTL_S = 300
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
    if "customer" not in who.roles or who.is_staff:
        raise ApiError(403, "Only customers can do this.")
    return await profile("customer", who)


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
