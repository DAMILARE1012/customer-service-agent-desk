"""Read a secret from the LOCAL Vault (npm run infra:up) with the root token vault-init left in
infra/vault/local/init.txt — for load-test tooling on a developer machine only, never in the app."""

import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    env_file = ROOT / ".env"
    if not env_file.exists():  # e.g. Locust running in a container: settings come from the environment
        return default
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip() or default
    return default


def read(path: str) -> dict:
    """read("keycloak") → the KV v2 data at secret/baton/keycloak."""
    init = Path(_env("VAULT_LOCAL_DIR", str(ROOT / "infra/vault/local"))) / "init.txt"
    match = re.search(r"Initial Root Token: (\S+)", init.read_text()) if init.exists() else None
    if not match:
        raise SystemExit(f"No local Vault root token at {init} — start the infrastructure first: npm run infra:up")
    addr = _env("VAULT_ADDR", "http://127.0.0.1:8200").rstrip("/") or "http://127.0.0.1:8200"
    request = urllib.request.Request(f"{addr}/v1/secret/data/baton/{path}", headers={"X-Vault-Token": match.group(1)})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())["data"]["data"]


def setting(name: str, default: str = "") -> str:
    """A non-secret setting from the environment or .env."""
    return _env(name, default)
