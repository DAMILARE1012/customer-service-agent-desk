"""Add (or remove) the Keycloak client the load test's agents sign in with.

Agents normally sign in through the browser (authorization code + PKCE). Locust can't drive a browser,
so this adds a public client, "baton-loadtest", that allows the username/password ("direct access")
grant, with the same baton-api audience as the staff app. LOCAL DEVELOPMENT ONLY — it is not in the
realm file, and you should never add it to a production realm.

    npm run loadtest:setup               # add it (safe to repeat)
    npm run loadtest:setup -- --remove   # remove it
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_vault  # noqa: E402

CLIENT_ID = "baton-loadtest"


def call(method: str, url: str, token: str | None = None, body=None, form=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Add or remove the load-test Keycloak client")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()

    keycloak = local_vault.setting("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
    realm = local_vault.setting("KEYCLOAK_REALM", "baton")
    admin_token = call("POST", f"{keycloak}/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli",
        "username": local_vault.setting("KEYCLOAK_ADMIN_USER", "admin"),
        "password": local_vault.read("keycloak")["KEYCLOAK_ADMIN_PASSWORD"],
    })["access_token"]  # fmt: skip
    clients = f"{keycloak}/admin/realms/{realm}/clients"
    existing = call("GET", f"{clients}?clientId={CLIENT_ID}", admin_token)

    if args.remove:
        for client in existing:
            call("DELETE", f"{clients}/{client['id']}", admin_token)
        print(f"removed {CLIENT_ID}" if existing else f"{CLIENT_ID} wasn't there")
        return
    if existing:
        print(f"{CLIENT_ID} already exists")
        return
    web = call("GET", f"{clients}?clientId=baton-web", admin_token)[0]
    audience = [m for m in call("GET", f"{clients}/{web['id']}/protocol-mappers/models", admin_token) if m["protocolMapper"] == "oidc-audience-mapper"]
    call("POST", clients, admin_token, {
        "clientId": CLIENT_ID,
        "name": "Load tests (local only — remove with npm run loadtest:setup -- --remove)",
        "publicClient": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": True,
        "protocolMappers": [{k: v for k, v in m.items() if k != "id"} for m in audience],
    })  # fmt: skip
    print(f"added {CLIENT_ID} (direct access grant, audience {', '.join(m['config'].get('included.client.audience', '?') for m in audience)})")


if __name__ == "__main__":
    main()
