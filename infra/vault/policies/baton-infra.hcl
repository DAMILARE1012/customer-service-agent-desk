# Vault Agent for the infrastructure (Postgres, Keycloak) reads their passwords — not the API's secrets.
path "secret/data/baton/database" {
  capabilities = ["read"]
}

path "secret/data/baton/keycloak" {
  capabilities = ["read"]
}

path "secret/data/baton/keycloak-client" {
  capabilities = ["read"]
}
