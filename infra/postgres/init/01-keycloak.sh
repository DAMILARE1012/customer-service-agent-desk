#!/bin/sh
# Runs once, when the database volume is first created: Keycloak gets its own user and database on
# the same server, so it can never read or write the app's tables. Its password comes from Vault
# (rendered by Vault Agent into KEYCLOAK_DB_PASSWORD_FILE — see infra/vault/agent/infra.hcl).
set -eu

kc_password=$(cat "${KEYCLOAK_DB_PASSWORD_FILE:?}")
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v kc_password="$kc_password" <<'SQL'
CREATE ROLE keycloak LOGIN PASSWORD :'kc_password';
CREATE DATABASE keycloak OWNER keycloak;
SQL
