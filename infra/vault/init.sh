#!/bin/sh
# One-shot setup for the local Vault, run by the vault-init service on every `infra:up`. Safe to repeat:
#
#   1. initialise Vault the first time (1 unseal key — local only; production uses KMS auto-unseal)
#   2. unseal it (Vault starts sealed after every restart)
#   3. enable a KV v2 secrets engine at secret/, the baton-api policy and an AppRole login for the API
#   4. the first time (or with VAULT_SEED=force), copy the API's secrets from .env into secret/baton/api
#
# Writes to /vault/local (= infra/vault/local, git-ignored): init.txt (unseal key + root token) and the
# API's AppRole credentials (role_id, secret_id). Treat that folder like .env.
set -eu
export VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
OUT=/vault/local
SECRETS="GROQ_API_KEY WIDGET_SIGNING_SECRET WIDGET_IDENTITY_SECRET KEYCLOAK_ADMIN_CLIENT_SECRET LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY SMTP_PASSWORD ALERT_WEBHOOK_URL"
umask 077
mkdir -p "$OUT"
chmod 755 "$OUT" # the API container reads role_id / secret_id; init.txt itself stays 600

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
  rm -f "$OUT/secret_id" # a fresh Vault means fresh AppRole credentials
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
vault policy write baton-api /vault/policies/baton-api.hcl >/dev/null
vault auth list | grep -q '^approle/' || vault auth enable approle >/dev/null
# Short-lived tokens; the secret_id itself doesn't expire here (rotate it with: vault write -f auth/approle/role/baton-api/secret-id).
vault write auth/approle/role/baton-api token_policies=baton-api token_ttl=1h token_max_ttl=4h secret_id_ttl=0 >/dev/null
vault read -field=role_id auth/approle/role/baton-api/role-id > "$OUT/role_id"
[ -s "$OUT/secret_id" ] || vault write -f -field=secret_id auth/approle/role/baton-api/secret-id > "$OUT/secret_id"
chmod 644 "$OUT/role_id" "$OUT/secret_id" # read by the API container's non-root user (the folder stays git-ignored)

if [ "${VAULT_SEED:-}" = "force" ] || ! vault kv get secret/baton/api >/dev/null 2>&1; then
  set --
  for name in $SECRETS; do
    eval "value=\${$name:-}"
    if [ -n "$value" ] && [ "$value" != "change-me" ]; then set -- "$@" "$name=$value"; fi
  done
  if [ "$#" -gt 0 ]; then
    vault kv put secret/baton/api "$@" >/dev/null
    echo "vault-init: stored $# secret(s) from .env in secret/baton/api (names only: $(for a in "$@"; do printf '%s ' "${a%%=*}"; done))"
  else
    echo "vault-init: no secrets in .env to store yet — add them in the UI (http://localhost:8200) or set them in .env and run npm run vault:seed"
  fi
fi
echo "vault-init: ready (UI http://localhost:8200 — root token in infra/vault/local/init.txt)"
