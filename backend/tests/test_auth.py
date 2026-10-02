"""Access-token verification against a throwaway RSA key standing in for the realm's signing key."""

import asyncio
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.security import HTTPAuthorizationCredentials

from app import auth
from app.auth import TokenVerifier

ISSUER = "http://localhost:8080/realms/baton"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def verifier(monkeypatch):
    v = TokenVerifier(ISSUER, "baton-api")
    monkeypatch.setattr(v.keys, "get_signing_key_from_jwt", lambda _token: type("K", (), {"key": KEY.public_key()})())
    return v


def token(key=KEY, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": ["baton-api", "account"], "sub": "6f1c-uuid", "iat": now, "exp": now + 300,
        "preferred_username": "maya.chen", "name": "Maya Chen", "email": "maya.chen@example.com", "email_verified": True,
        "realm_access": {"roles": ["customer", "offline_access", "default-roles-baton"]},
    }  # fmt: skip
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


def test_valid_token_becomes_a_principal_with_app_roles_only(verifier):
    who = verifier.verify(token())
    assert who.sub == "6f1c-uuid" and who.username == "maya.chen" and who.email_verified
    assert who.roles == {"customer"} and not who.is_staff


@pytest.mark.parametrize(
    "bad",
    [
        {"aud": "account"},  # issued for another client
        {"iss": "http://evil.example/realms/baton"},
        {"exp": int(time.time()) - 60},
        {"sub": None},
    ],
)
def test_tokens_for_someone_else_or_expired_are_rejected(verifier, bad):
    with pytest.raises(jwt.PyJWTError):
        verifier.verify(token(**bad))


def test_token_signed_with_another_key_is_rejected(verifier):
    with pytest.raises(jwt.InvalidSignatureError):
        verifier.verify(token(key=OTHER_KEY))


def test_principal_dependency_turns_failures_into_401(verifier, monkeypatch):
    monkeypatch.setattr(auth, "verifier", lambda: verifier)
    with pytest.raises(auth.ApiError) as missing:
        asyncio.run(auth.principal(None))
    assert missing.value.status == 401
    with pytest.raises(auth.ApiError) as expired:
        asyncio.run(auth.principal(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token(exp=int(time.time()) - 60))))
    assert expired.value.status == 401
    ok = asyncio.run(auth.principal(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token(realm_access={"roles": ["agent"]}))))
    assert ok.roles == {"agent"} and ok.is_staff


def test_concurrent_first_requests_create_one_profile(monkeypatch):
    """A freshly signed-in app fires several requests at once; only one may create the profile row."""
    from app.db.repository import MemoryRepository

    repo = MemoryRepository()
    calls = []
    original = repo.upsert_person

    async def counting(kind, identity):
        calls.append(kind)
        await asyncio.sleep(0.01)  # widen the race window
        return await original(kind, identity)

    monkeypatch.setattr(repo, "upsert_person", counting)
    monkeypatch.setattr(auth, "repository", lambda: repo)
    auth._profiles.clear()
    who = auth.Principal(sub="kc-new-agent", username="new", name="New Agent", email="new@baton.example", email_verified=True, roles=frozenset({"agent"}))

    async def burst():
        return await asyncio.gather(*(auth.profile("agent", who) for _ in range(5)))

    profiles = asyncio.run(burst())
    assert calls == ["agent"] and len({p["id"] for p in profiles}) == 1
    auth._profiles.clear()
