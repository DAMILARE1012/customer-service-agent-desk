#!/bin/sh
# One-shot setup for the local Vault — the first thing to run after Vault itself; everything else waits
# for it (see infra/docker-compose.yml). Safe to repeat on every `infra:up`:
#
#   1. initialise Vault the first time (1 unseal key — local only; production uses KMS auto-unseal)
#   2. unseal it (Vault starts sealed after every restart)
#   3. enable KV v2 at secret/, a policy and an AppRole per consumer: baton-api (the API) and
#      baton-infra (Vault Agent, which hands Postgres and Keycloak their passwords)
#   4. the first time a path is missing, fill it: from .env if a value is there, otherwise — for secrets
#      nobody needs to choose — a strong random value. With VAULT_SEED=force, values found in .env are
#      merged into what Vault already holds (nothing is regenerated, so the database password can't change).
#
# Writes to /vault/local (= infra/vault/local, git-ignored): init.txt (unseal key + root token) and each
# consumer's AppRole credentials. Treat that folder like a password manager's vault file.
set -eu
export VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
OUT=/vault/local
umask 077
mkdir -p "$OUT"
chmod 755 "$OUT" # containers read their AppRole files; init.txt itself stays 600

echo "vault-init: waiting for $VAULT_ADDR"
while :; do
  set +e; vault status >/dev/null 2>&1; rc=$?; set -e
  [ "$rc" -ne 1 ] && break # 0 = unsealed, 2 = sealed; 1 = not reachable yet
  sleep 1
done

set +e; vault operator init -status >/dev/null 2>&1; initialised=$?; set -e
if [ "$initialised" -eq 2 ]; then
  echo "vault-init: first start — initialising"
  vault operator init -key-shares=1 -key-threshold=1 > "$OUT/init.txt"
  rm -f "$OUT"/*_secret_id "$OUT/secret_id" # a fresh Vault means fresh AppRole credentials
elif [ ! -s "$OUT/init.txt" ]; then
  echo "vault-init: Vault is initialised but $OUT/init.txt is missing — can't unseal." >&2
  echo "            Restore that file, or start over: npm run infra:down -- -v (deletes ALL local data)." >&2
  exit 1
fi

UNSEAL_KEY=$(sed -n 's/^Unseal Key 1: //p' "$OUT/init.txt")
VAULT_TOKEN=$(sed -n 's/^Initial Root Token: //p' "$OUT/init.txt")
export VAULT_TOKEN
vault operator unseal "$UNSEAL_KEY" >/dev/null

vault secrets list | grep -q '^secret/' || vault secrets enable -path=secret -version=2 kv >/dev/null
vault auth list | grep -q '^approle/' || vault auth enable approle >/dev/null

# One policy + AppRole per consumer. Short-lived tokens; secret_ids don't expire here
# (rotate one with: vault write -f auth/approle/role/<role>/secret-id).
approle() { # approle <role> <file prefix>
  vault policy write "$1" "/vault/policies/$1.hcl" >/dev/null
  vault write "auth/approle/role/$1" token_policies="$1" token_ttl=1h token_max_ttl=4h secret_id_ttl=0 >/dev/null
  vault read -field=role_id "auth/approle/role/$1/role-id" > "$OUT/$2role_id"
  [ -s "$OUT/$2secret_id" ] || vault write -f -field=secret_id "auth/approle/role/$1/secret-id" > "$OUT/$2secret_id"
  chmod 644 "$OUT/$2role_id" "$OUT/$2secret_id"
}
approle baton-api ""
approle baton-infra "infra_"

random() { head -c 48 /dev/urandom | base64 | tr -d '+/=\n' | cut -c1-32; }

# seed <path> "<keys>" "<keys that may be generated>"
seed() {
  path="secret/baton/$1" keys="$2" generate=" $3 " # copied first: `set --` below reuses the positional parameters
  if vault kv get "$path" >/dev/null 2>&1; then exists=1; else exists=0; fi
  [ "$exists" -eq 1 ] && [ "${VAULT_SEED:-}" != "force" ] && return 0
  set --
  for name in $keys; do
    eval "value=\${$name:-}"
    [ "$value" = "change-me" ] && value=""
    if [ -z "$value" ] && [ "$exists" -eq 0 ] && echo "$generate" | grep -q " $name "; then value=$(random); fi
    if [ -n "$value" ]; then set -- "$@" "$name=$value"; fi
  done
  [ "$#" -eq 0 ] && { echo "vault-init: nothing to store in $path yet"; return 0; }
  if [ "$exists" -eq 1 ]; then vault kv patch "$path" "$@" >/dev/null; else vault kv put "$path" "$@" >/dev/null; fi
  echo "vault-init: $path ← $(for a in "$@"; do printf '%s ' "${a%%=*}"; done)(names only)"
}

seed database "BATON_DB_PASSWORD" "BATON_DB_PASSWORD"
seed keycloak "KEYCLOAK_DB_PASSWORD KEYCLOAK_ADMIN_PASSWORD BATON_DEMO_PASSWORD" "KEYCLOAK_DB_PASSWORD KEYCLOAK_ADMIN_PASSWORD BATON_DEMO_PASSWORD"
seed keycloak-client "KEYCLOAK_ADMIN_CLIENT_SECRET" "KEYCLOAK_ADMIN_CLIENT_SECRET"
seed api "GROQ_API_KEY WIDGET_SIGNING_SECRET WIDGET_IDENTITY_SECRET LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY SMTP_PASSWORD ALERT_WEBHOOK_URL" "WIDGET_SIGNING_SECRET WIDGET_IDENTITY_SECRET"

echo "vault-init: ready (UI http://localhost:8200 — root token in infra/vault/local/init.txt)"
