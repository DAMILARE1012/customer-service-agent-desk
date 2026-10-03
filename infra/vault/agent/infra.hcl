# Vault Agent, run once before Postgres and Keycloak start: logs in with the "baton-infra" AppRole,
# renders their passwords into the infra_secrets volume (inside Docker, never on your disk) and exits.
# Postgres reads POSTGRES_PASSWORD_FILE; Keycloak sources keycloak.env.

exit_after_auth = true
pid_file        = "/tmp/vault-agent.pid"

vault {
  address = "http://vault:8200"
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path                   = "/vault/local/infra_role_id"
      secret_id_file_path                 = "/vault/local/infra_secret_id"
      remove_secret_id_file_after_reading = false
    }
  }
}

template_config {
  exit_on_retry_failure = true # a missing secret stops everything that depends on it, loudly
}

template {
  destination = "/run/baton-secrets/db_password"
  perms       = "0644"
  contents    = <<-EOT
  {{- with secret "secret/data/baton/database" }}{{ .Data.data.BATON_DB_PASSWORD }}{{ end -}}
  EOT
}

template {
  destination = "/run/baton-secrets/keycloak_db_password"
  perms       = "0644"
  contents    = <<-EOT
  {{- with secret "secret/data/baton/keycloak" }}{{ .Data.data.KEYCLOAK_DB_PASSWORD }}{{ end -}}
  EOT
}

# Keycloak's settings, as shell variable assignments (single-quoted: values may contain any character but ').
template {
  destination = "/run/baton-secrets/keycloak.env"
  perms       = "0644"
  contents    = <<-EOT
  {{- with secret "secret/data/baton/keycloak" }}
  KC_DB_PASSWORD='{{ .Data.data.KEYCLOAK_DB_PASSWORD }}'
  KC_BOOTSTRAP_ADMIN_PASSWORD='{{ .Data.data.KEYCLOAK_ADMIN_PASSWORD }}'
  BATON_DEMO_PASSWORD='{{ .Data.data.BATON_DEMO_PASSWORD }}'
  {{- end }}
  {{- with secret "secret/data/baton/keycloak-client" }}
  BATON_API_ADMIN_SECRET='{{ .Data.data.KEYCLOAK_ADMIN_CLIENT_SECRET }}'
  {{- end }}
  EOT
}
