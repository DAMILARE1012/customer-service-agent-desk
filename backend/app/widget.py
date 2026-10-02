"""The customer chat widget's identity model. Customers never sign in to Baton:

  visitor      someone browsing your site. Opening the widget creates a visitor profile and a session
               token the widget keeps (WIDGET_VISITOR_DAYS), so a returning visitor sees their chat.
  identified   someone already signed in to your site. Your site's backend vouches for them with a
               short-lived identity token signed with WIDGET_IDENTITY_SECRET (HS256):

                   {"sub": "<your user id>", "email": "...", "name": "...", "iat": ..., "exp": <≤ 24 h later>}

               Baton links the chat to their customer profile (claiming a seeded CRM row by email the
               first time) and their history follows them across devices.

Both end up holding a Baton widget session token (HS256, WIDGET_SIGNING_SECRET, issuer "baton-widget"),
which the API accepts for the customer routes only. Staff sign in with Keycloak; customers never do.
"""

import secrets
import time

import jwt

from app.config import settings
from app.conversation.lifecycle import ApiError

ISSUER = "baton-widget"
AUDIENCE = "baton-api"
MAX_IDENTITY_LIFETIME_S = 24 * 3600


def _require(secret: str, what: str) -> str:
    if not secret:
        raise ApiError(503, f"The chat widget isn't configured ({what} is not set).")
    return secret


def issue_session(customer: dict, *, identified: bool) -> dict:
    now = int(time.time())
    lifetime = settings.widget_identified_hours * 3600 if identified else settings.widget_visitor_days * 86400
    claims = {
        "iss": ISSUER, "aud": AUDIENCE, "sub": customer["id"], "kind": "identified" if identified else "visitor",
        "name": customer["name"], "iat": now, "exp": now + lifetime, "jti": secrets.token_hex(8),
    }  # fmt: skip
    token = jwt.encode(claims, _require(settings.widget_signing_secret, "WIDGET_SIGNING_SECRET"), algorithm="HS256")
    return {"token": token, "expiresAt": claims["exp"] * 1000, "kind": claims["kind"]}


def verify_session(token: str) -> dict:
    """Claims of a valid widget session token (raises jwt.PyJWTError otherwise)."""
    secret = settings.widget_signing_secret
    if not secret:
        raise jwt.InvalidTokenError("the chat widget isn't configured")
    return jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER, options={"require": ["exp", "iat", "sub", "iss", "aud"]})


def verify_identity(token: str) -> dict:
    """Claims of an identity token signed by your website's backend."""
    secret = _require(settings.widget_identity_secret, "WIDGET_IDENTITY_SECRET")
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "iat", "sub"], "verify_aud": False}, leeway=30)
    except jwt.PyJWTError as error:
        raise ApiError(401, f"The customer's identity token was rejected: {error}") from error
    if claims["exp"] - claims["iat"] > MAX_IDENTITY_LIFETIME_S:
        raise ApiError(401, "Identity tokens must expire within 24 hours of being issued.")
    if not str(claims["sub"]).strip():
        raise ApiError(401, "The identity token has no subject (your user id).")
    return claims


def sign_demo_identity(customer: dict) -> str:
    """What your website's backend would do for a signed-in customer — local demo only."""
    now = int(time.time())
    claims = {"sub": customer["id"], "email": customer.get("email"), "name": customer["name"], "iat": now, "exp": now + 3600}
    return jwt.encode(claims, _require(settings.widget_identity_secret, "WIDGET_IDENTITY_SECRET"), algorithm="HS256")
