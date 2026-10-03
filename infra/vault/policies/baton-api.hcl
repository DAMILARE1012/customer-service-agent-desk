# The API may read its own secrets and nothing else — no listing, no writing, no other paths.
path "secret/data/baton/api" {
  capabilities = ["read"]
}
