# Vault for Baton's local stack: a real server (not -dev mode), so secrets survive restarts.
# Production differences are noted inline — see the README's "Deploying" section.

ui            = true
disable_mlock = true # containers can't lock memory without IPC_LOCK; production: run with IPC_LOCK, or on a host with swap off

# Single-node storage on a Docker volume. Production: integrated storage (raft) across three nodes.
storage "file" {
  path = "/vault/file"
}

# Plain HTTP on the private Docker network and on 127.0.0.1 only. Production: TLS (tls_cert_file /
# tls_key_file), or terminate TLS at a load balancer that only the app's subnets can reach.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr = "http://vault:8200"

# Production on AWS: let Vault unseal itself with KMS instead of a key on disk:
# seal "awskms" {
#   region     = "eu-west-2"
#   kms_key_id = "alias/baton-vault-unseal"
# }
