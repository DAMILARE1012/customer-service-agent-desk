# The API reads its own secrets, the database password and the Keycloak service-account secret —
# nothing else: no listing, no writing, not Keycloak's own passwords.
path "secret/data/baton/api" {
  capabilities = ["read"]
}

path "secret/data/baton/database" {
  capabilities = ["read"]
}

path "secret/data/baton/keycloak-client" {
  capabilities = ["read"]
}
