"""The API's secrets from HashiCorp Vault (optional).

With VAULT_ADDR set, the API logs in at startup — AppRole (VAULT_ROLE_ID / VAULT_SECRET_ID, or the *_FILE
variants), or a token (VAULT_TOKEN) — reads the KV v2 secret VAULT_SECRET_PATH (default secret/baton/api)
and uses its values over anything in the environment. Without VAULT_ADDR, secrets come from environment
variables as before.

Only the names in SECRETS are read; anything else in the secret is ignored. Values are never logged.
If Vault is configured but can't be reached or refuses access, startup fails: running without the
secrets would only fail later and less clearly. Values are read once; restart the API after rotating one.
"""

import logging
import time
from pathlib import Path

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


def _read(client: httpx.Client) -> dict:
    token = _token(client)
    mount, _, path = settings.vault_secret_path.partition("/")
    response = client.get(f"/v1/{mount}/data/{path}", headers={"X-Vault-Token": token})
    if response.status_code == 404:
        raise VaultError(f"No secret at {settings.vault_secret_path} — run npm run vault:seed, or add it in the Vault UI.")
    if response.status_code != 200:
        raise VaultError(f"Vault refused to read {settings.vault_secret_path} ({response.status_code}).")
    return response.json()["data"]["data"]


def load(*, attempts: int = 10, transport: httpx.BaseTransport | None = None) -> list[str]:
    """Apply the secrets from Vault to `settings`; returns the names applied. No-op without VAULT_ADDR."""
    global source
    if not settings.vault_addr:
        return []
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(base_url=settings.vault_addr.rstrip("/"), timeout=5, transport=transport) as client:
                values = _read(client)
            break
        except httpx.HTTPError as error:  # Vault may still be starting or unsealing
            last = error
            time.sleep(min(2.0, 0.25 * 2**attempt))
    else:
        raise VaultError(f"Can't reach Vault at {settings.vault_addr}: {last}")
    applied = [name for name in SECRETS if values.get(name)]
    for name in applied:
        setattr(settings, SECRETS[name], values[name])
    source = "vault"
    log.info("secrets from Vault (%s): %s", settings.vault_secret_path, ", ".join(applied) or "none")
    return applied
