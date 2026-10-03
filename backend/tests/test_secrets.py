"""Secrets from Vault (app/secrets.py), against a fake Vault: AppRole login, KV v2 read, and failing loudly."""

import httpx
import pytest

from app import secrets
from app.config import settings

TOKEN = "hvs.test-token"


def fake_vault(*, data=None, login_ok=True, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request.method, request.url.path, request.headers.get("x-vault-token")))
        if request.url.path == "/v1/auth/approle/login":
            body = request.read().decode()
            if not login_ok or '"role_id":"role-1"' not in body.replace(" ", ""):
                return httpx.Response(400, json={"errors": ["invalid role or secret ID"]})
            return httpx.Response(200, json={"auth": {"client_token": TOKEN}})
        if request.url.path == "/v1/secret/data/baton/api":
            if request.headers.get("x-vault-token") != TOKEN:
                return httpx.Response(403, json={"errors": ["permission denied"]})
            if data is None:
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(200, json={"data": {"data": data, "metadata": {"version": 1}}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture()
def vault_settings(monkeypatch, tmp_path):
    (tmp_path / "role_id").write_text("role-1\n")
    (tmp_path / "secret_id").write_text("secret-1\n")
    for name, value in {
        "vault_addr": "http://vault.test:8200", "vault_token": "", "vault_role_id": "", "vault_secret_id": "",
        "vault_role_id_file": str(tmp_path / "role_id"), "vault_secret_id_file": str(tmp_path / "secret_id"),
        "vault_secret_path": "secret/baton/api", "groq_api_key": "from-env", "widget_signing_secret": "from-env",
    }.items():  # fmt: skip
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(secrets, "source", "environment")
    return tmp_path


def test_secrets_come_from_vault_over_the_environment(vault_settings):
    seen = []
    applied = secrets.load(transport=fake_vault(data={"GROQ_API_KEY": "gsk-from-vault", "SOMETHING_ELSE": "ignored", "SMTP_PASSWORD": ""}, seen=seen))
    assert applied == ["GROQ_API_KEY"]  # empty values and unknown names are skipped
    assert settings.groq_api_key == "gsk-from-vault"
    assert settings.widget_signing_secret == "from-env"  # not in Vault: the environment's value stays
    assert secrets.source == "vault"
    assert [path for _, path, _ in seen] == ["/v1/auth/approle/login", "/v1/secret/data/baton/api"]


def test_a_token_works_instead_of_approle(vault_settings, monkeypatch):
    monkeypatch.setattr(settings, "vault_token", TOKEN)
    seen = []
    secrets.load(transport=fake_vault(data={"GROQ_API_KEY": "gsk-2"}, seen=seen))
    assert [path for _, path, _ in seen] == ["/v1/secret/data/baton/api"] and settings.groq_api_key == "gsk-2"


def test_startup_fails_loudly_when_vault_says_no(vault_settings):
    with pytest.raises(secrets.VaultError, match="refused the AppRole login"):
        secrets.load(transport=fake_vault(data={}, login_ok=False))
    with pytest.raises(secrets.VaultError, match="vault:seed"):
        secrets.load(transport=fake_vault(data=None))
    assert settings.groq_api_key == "from-env" and secrets.source == "environment"


def test_startup_fails_when_vault_is_unreachable(vault_settings):
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(secrets.VaultError, match="Can't reach Vault"):
        secrets.load(attempts=2, transport=httpx.MockTransport(down))


def test_missing_credential_files_are_explained(vault_settings, monkeypatch):
    monkeypatch.setattr(settings, "vault_role_id_file", str(vault_settings / "missing"))
    with pytest.raises(secrets.VaultError, match="vault-init"):
        secrets.load(transport=fake_vault(data={}))


def test_without_vault_nothing_changes(vault_settings, monkeypatch):
    monkeypatch.setattr(settings, "vault_addr", "")
    assert secrets.load(transport=fake_vault(data={"GROQ_API_KEY": "x"})) == []
    assert settings.groq_api_key == "from-env"
