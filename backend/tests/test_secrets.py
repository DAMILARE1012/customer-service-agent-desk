"""Secrets from Vault (app/secrets.py), against a fake Vault: AppRole login, KV v2 reads from several paths,
Vault as the only source once configured, and failing loudly."""

import httpx
import pytest

from app import secrets
from app.config import settings

TOKEN = "hvs.test-token"
PATHS = "secret/baton/api,secret/baton/database,secret/baton/keycloak-client"


def fake_vault(store, *, login_ok=True, seen=None):
    """store: {"baton/api": {...}, ...} — what's in Vault."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.path)
        if request.url.path == "/v1/auth/approle/login":
            body = request.read().decode().replace(" ", "")
            if not login_ok or '"role_id":"role-1"' not in body:
                return httpx.Response(400, json={"errors": ["invalid role or secret ID"]})
            return httpx.Response(200, json={"auth": {"client_token": TOKEN}})
        if request.url.path.startswith("/v1/secret/data/"):
            if request.headers.get("x-vault-token") != TOKEN:
                return httpx.Response(403, json={"errors": ["permission denied"]})
            data = store.get(request.url.path.removeprefix("/v1/secret/data/"))
            if data is None:
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(200, json={"data": {"data": data, "metadata": {"version": 1}}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


FULL = {
    "baton/api": {"GROQ_API_KEY": "gsk-from-vault", "WIDGET_SIGNING_SECRET": "sign-v", "SOMETHING_ELSE": "ignored", "SMTP_PASSWORD": ""},
    "baton/database": {"BATON_DB_PASSWORD": "p@ss:w/rd"},
    "baton/keycloak-client": {"KEYCLOAK_ADMIN_CLIENT_SECRET": "kc-client"},
}


@pytest.fixture()
def vault_settings(monkeypatch, tmp_path):
    (tmp_path / "role_id").write_text("role-1\n")
    (tmp_path / "secret_id").write_text("secret-1\n")
    for name, value in {
        "vault_addr": "http://vault.test:8200", "vault_token": "", "vault_role_id": "", "vault_secret_id": "",
        "vault_role_id_file": str(tmp_path / "role_id"), "vault_secret_id_file": str(tmp_path / "secret_id"),
        "vault_secret_paths": PATHS, "database_url": "postgresql://baton@db:5432/baton",
        "groq_api_key": "from-env", "widget_signing_secret": "from-env", "widget_identity_secret": "from-env",
        "keycloak_admin_client_secret": "", "smtp_password": "",
    }.items():  # fmt: skip
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(secrets, "source", "environment")
    return tmp_path


def test_secrets_come_from_vault_across_paths(vault_settings):
    seen = []
    applied = secrets.load(transport=fake_vault(FULL, seen=seen))
    assert applied == ["GROQ_API_KEY", "WIDGET_SIGNING_SECRET", "KEYCLOAK_ADMIN_CLIENT_SECRET", "BATON_DB_PASSWORD"]
    assert settings.groq_api_key == "gsk-from-vault" and settings.keycloak_admin_client_secret == "kc-client"
    assert settings.database_url == "postgresql://baton:p%40ss%3Aw%2Frd@db:5432/baton"  # escaped into the URL
    assert secrets.source == "vault"
    assert seen == ["/v1/auth/approle/login", "/v1/secret/data/baton/api", "/v1/secret/data/baton/database", "/v1/secret/data/baton/keycloak-client"]


def test_once_vault_is_configured_the_environment_is_not_a_fallback(vault_settings, caplog):
    secrets.load(transport=fake_vault(FULL))
    assert settings.widget_identity_secret == ""  # set in the environment, missing from Vault → not used
    assert "ignored WIDGET_IDENTITY_SECRET from the environment" in caplog.text
    assert "from-env" not in caplog.text and "gsk-from-vault" not in caplog.text  # values are never logged


def test_a_token_works_instead_of_approle(vault_settings, monkeypatch):
    monkeypatch.setattr(settings, "vault_token", TOKEN)
    seen = []
    secrets.load(transport=fake_vault(FULL, seen=seen))
    assert "/v1/auth/approle/login" not in seen and settings.groq_api_key == "gsk-from-vault"


def test_startup_fails_loudly_when_vault_says_no(vault_settings):
    with pytest.raises(secrets.VaultError, match="refused the AppRole login"):
        secrets.load(transport=fake_vault(FULL, login_ok=False))
    with pytest.raises(secrets.VaultError, match="No secret at secret/baton/database"):
        secrets.load(transport=fake_vault({"baton/api": {}, "baton/keycloak-client": {}}))
    assert settings.groq_api_key == "from-env" and secrets.source == "environment"  # nothing half-applied


def test_startup_fails_when_vault_is_unreachable(vault_settings):
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(secrets.VaultError, match="Can't reach Vault"):
        secrets.load(attempts=2, transport=httpx.MockTransport(down))


def test_missing_credential_files_are_explained(vault_settings, monkeypatch):
    monkeypatch.setattr(settings, "vault_role_id_file", str(vault_settings / "missing"))
    with pytest.raises(secrets.VaultError, match="vault-init"):
        secrets.load(transport=fake_vault(FULL))


def test_without_vault_the_environment_is_used(vault_settings, monkeypatch):
    monkeypatch.setattr(settings, "vault_addr", "")
    assert secrets.load(transport=fake_vault(FULL)) == []
    assert settings.groq_api_key == "from-env" and settings.database_url == "postgresql://baton@db:5432/baton"
