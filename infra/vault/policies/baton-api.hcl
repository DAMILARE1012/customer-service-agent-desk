# The API reads its own secrets, the database password, the Keycloak service-account secret and the
# Langfuse project keys — nothing else: no listing, no writing, not other services' own passwords.
path "secret/data/baton/api" {
  capabilities = ["read"]
}

path "secret/data/baton/database" {
  capabilities = ["read"]
}

path "secret/data/baton/keycloak-client" {
  capabilities = ["read"]
}

path "secret/data/baton/langfuse-project" {
  capabilities = ["read"]
}
