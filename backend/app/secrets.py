"""The API's secrets from HashiCorp Vault — the API depends on Vault, not the other way round.

With VAULT_ADDR set, the API logs in at startup — AppRole (VAULT_ROLE_ID / VAULT_SECRET_ID, or the *_FILE
variants), or a token (VAULT_TOKEN) — and reads the KV v2 secrets in VAULT_SECRET_PATHS:

    secret/baton/api              its own secrets (Groq key, widget secrets, SMTP password, webhook)
    secret/baton/database         the database password, added to DATABASE_URL
    secret/baton/keycloak-client  the Keycloak service-account secret (Keycloak reads the same one)
    secret/baton/langfuse-project the Langfuse project keys (Langfuse creates its project from the same)

Strict: with Vault configured, every name in SECRETS comes from Vault only. A value left in the
environment is ignored (with a warning), so a secret missing from Vault shows up as missing instead of
quietly working from a stale copy. If Vault can't be reached or refuses access, startup fails. Values
are read once (restart after rotating one) and never logged. Without VAULT_ADDR, the environment is used.
"""

import logging
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.config import ROOT, settings

log = logging.getLogger(__name__)

# Vault key (same as the environment variable) → settings attribute
SECRETS = {
    "GROQ_API_KEY": "groq_api_key",
    "WIDGET_SIGNING_SECRET": "widget_signing_secret",
    "WIDGET_IDENTITY_SECRET": "widget_identity_secret",
    "KEYCLOAK_ADMIN_CLIENT_SECRET": "keycloak_admin_client_secret",
    "LANGFUSE_PUBLIC_KEY": "langfuse_public_key",
    "LANGFUSE_SECRET_KEY": "langfuse_secret_key",
    "SMTP_PASSWORD": "smtp_password",
    "ALERT_WEBHOOK_URL": "alert_webhook_url",
}
DATABASE_PASSWORD = "BATON_DB_PASSWORD"  # goes into DATABASE_URL rather than a setting of its own

source = "environment"  # reported by /health: "environment" or "vault"


class VaultError(RuntimeError):
    pass


def _credential(value: str, file: str) -> str:
    if value:
        return value
    if file:
        path = Path(file) if Path(file).is_absolute() else ROOT / file
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise VaultError(f"Can't read {path}: {error.strerror}. Has vault-init run (npm run infra:up)?") from error
    return ""


def _token(client: httpx.Client) -> str:
    if settings.vault_token:
        return settings.vault_token
    role_id = _credential(settings.vault_role_id, settings.vault_role_id_file)
    secret_id = _credential(settings.vault_secret_id, settings.vault_secret_id_file)
    if not role_id or not secret_id:
        raise VaultError("VAULT_ADDR is set but there are no credentials: set VAULT_ROLE_ID/VAULT_SECRET_ID (or their _FILE variants) or VAULT_TOKEN.")
    response = client.post("/v1/auth/approle/login", json={"role_id": role_id, "secret_id": secret_id})
    if response.status_code != 200:
        raise VaultError(f"Vault refused the AppRole login ({response.status_code}).")
    return response.json()["auth"]["client_token"]


def _read(client: httpx.Client, token: str, secret_path: str) -> dict:
    mount, _, path = secret_path.partition("/")
    response = client.get(f"/v1/{mount}/data/{path}", headers={"X-Vault-Token": token})
    if response.status_code == 404:
        raise VaultError(f"No secret at {secret_path} — run npm run infra:up (vault-init fills it), or add it in the Vault UI.")
    if response.status_code != 200:
        raise VaultError(f"Vault refused to read {secret_path} ({response.status_code}).")
    return response.json()["data"]["data"]


def _paths() -> list[str]:
    return [p.strip() for p in settings.vault_secret_paths.split(",") if p.strip()]


def _with_password(url: str, password: str) -> str:
    parts = urlsplit(url)
    user = parts.username or ""
    host = parts.hostname or ""
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


def load(*, attempts: int = 10, transport: httpx.BaseTransport | None = None) -> list[str]:
    """Apply the secrets from Vault to `settings`; returns the names applied. No-op without VAULT_ADDR."""
    global source
    if not settings.vault_addr:
        return []
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(base_url=settings.vault_addr.rstrip("/"), timeout=5, transport=transport) as client:
                token = _token(client)
                values: dict = {}
                for path in _paths():
                    values.update(_read(client, token, path))
            break
        except httpx.HTTPError as error:  # Vault may still be starting or unsealing
            last = error
            time.sleep(min(2.0, 0.25 * 2**attempt))
    else:
        raise VaultError(f"Can't reach Vault at {settings.vault_addr}: {last}")

    applied, ignored = [], []
    for name, attribute in SECRETS.items():
        if values.get(name):
            setattr(settings, attribute, values[name])
            applied.append(name)
        else:
            if getattr(settings, attribute):
                ignored.append(name)
            setattr(settings, attribute, "")  # strict: Vault is the only source once it's configured
    if values.get(DATABASE_PASSWORD) and settings.database_url:
        settings.database_url = _with_password(settings.database_url, values[DATABASE_PASSWORD])
        applied.append(DATABASE_PASSWORD)
    source = "vault"
    log.info("secrets from Vault (%s): %s", ", ".join(_paths()), ", ".join(applied) or "none")
    if ignored:
        log.warning("ignored %s from the environment: with Vault configured, add them to Vault instead", ", ".join(ignored))
    return applied
