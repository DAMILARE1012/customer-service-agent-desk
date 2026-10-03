# Vault Agent for the observability stack (Langfuse, its databases, Grafana) reads their passwords and
# the Langfuse project keys it creates the project with — nothing of the app's.
path "secret/data/baton/observability" {
  capabilities = ["read"]
}

path "secret/data/baton/langfuse-project" {
  capabilities = ["read"]
}
