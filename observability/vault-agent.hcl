# Vault Agent, run once before the observability stack starts: logs in with the "baton-observability"
# AppRole, renders each service's secrets into the obs_secrets volume (inside Docker only) and exits.
# Values are single-quoted for the shell (generated ones are letters and digits).

exit_after_auth = true
pid_file        = "/tmp/vault-agent.pid"

vault {
  address = "http://vault:8200" # on the infrastructure's network (baton_default)
}

auto_auth {
  method "approle" {
    config = {
      role_id_file_path                   = "/vault/local/obs_role_id"
      secret_id_file_path                 = "/vault/local/obs_secret_id"
      remove_secret_id_file_after_reading = false
    }
  }
}

template_config {
  exit_on_retry_failure = true # Vault down or a secret missing: nothing starts, loudly
}

# Postgres reads POSTGRES_PASSWORD_FILE; Grafana reads GF_SECURITY_ADMIN_PASSWORD__FILE; Redis's health check reads its file.
template {
  destination = "/run/obs-secrets/postgres_password"
  perms       = "0644"
  contents    = "{{ with secret \"secret/data/baton/observability\" }}{{ .Data.data.LANGFUSE_POSTGRES_PASSWORD }}{{ end }}"
}

template {
  destination = "/run/obs-secrets/grafana_admin_password"
  perms       = "0644"
  contents    = "{{ with secret \"secret/data/baton/observability\" }}{{ .Data.data.GRAFANA_ADMIN_PASSWORD }}{{ end }}"
}

template {
  destination = "/run/obs-secrets/redis_password"
  perms       = "0644"
  contents    = "{{ with secret \"secret/data/baton/observability\" }}{{ .Data.data.LANGFUSE_REDIS_PASSWORD }}{{ end }}"
}

# Sourced by observability/with-secrets.sh before each image's own entrypoint.
template {
  destination = "/run/obs-secrets/langfuse.env"
  perms       = "0644"
  contents    = <<-EOT
  {{- with secret "secret/data/baton/observability" }}
  DATABASE_URL='postgresql://postgres:{{ .Data.data.LANGFUSE_POSTGRES_PASSWORD | urlquery }}@postgres:5432/postgres'
  SALT='{{ .Data.data.LANGFUSE_SALT }}'
  ENCRYPTION_KEY='{{ .Data.data.LANGFUSE_ENCRYPTION_KEY }}'
  CLICKHOUSE_PASSWORD='{{ .Data.data.LANGFUSE_CLICKHOUSE_PASSWORD }}'
  REDIS_AUTH='{{ .Data.data.LANGFUSE_REDIS_PASSWORD }}'
  LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY='{{ .Data.data.LANGFUSE_MINIO_PASSWORD }}'
  LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY='{{ .Data.data.LANGFUSE_MINIO_PASSWORD }}'
  {{- end }}
  EOT
}

# Only the web container: sessions, and the headless first start (project keys, first user).
template {
  destination = "/run/obs-secrets/langfuse-web.env"
  perms       = "0644"
  contents    = <<-EOT
  {{- with secret "secret/data/baton/observability" }}
  NEXTAUTH_SECRET='{{ .Data.data.LANGFUSE_NEXTAUTH_SECRET }}'
  LANGFUSE_INIT_USER_PASSWORD='{{ .Data.data.LANGFUSE_INIT_USER_PASSWORD }}'
  {{- end }}
  {{- with secret "secret/data/baton/langfuse-project" }}
  LANGFUSE_INIT_PROJECT_PUBLIC_KEY='{{ .Data.data.LANGFUSE_PUBLIC_KEY }}'
  LANGFUSE_INIT_PROJECT_SECRET_KEY='{{ .Data.data.LANGFUSE_SECRET_KEY }}'
  {{- end }}
  EOT
}

template {
  destination = "/run/obs-secrets/clickhouse.env"
  perms       = "0644"
  contents    = "{{ with secret \"secret/data/baton/observability\" }}CLICKHOUSE_PASSWORD='{{ .Data.data.LANGFUSE_CLICKHOUSE_PASSWORD }}'{{ end }}\n"
}

template {
  destination = "/run/obs-secrets/redis.env"
  perms       = "0644"
  contents    = "{{ with secret \"secret/data/baton/observability\" }}REDIS_PASSWORD='{{ .Data.data.LANGFUSE_REDIS_PASSWORD }}'{{ end }}\n"
}

template {
  destination = "/run/obs-secrets/minio.env"
  perms       = "0644"
  contents    = "{{ with secret \"secret/data/baton/observability\" }}MINIO_ROOT_PASSWORD='{{ .Data.data.LANGFUSE_MINIO_PASSWORD }}'{{ end }}\n"
}
