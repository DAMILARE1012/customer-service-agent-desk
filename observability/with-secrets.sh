#!/bin/sh
# Load the secrets Vault Agent rendered for this service (SECRETS_FILE: one or more env files), then run
# the image's own entrypoint and command, unchanged.
set -eu
for file in $SECRETS_FILE; do
  set -a
  . "$file"
  set +a
done
exec "$@"
