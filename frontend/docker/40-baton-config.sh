#!/bin/sh
# Writes /config.js from the container's VITE_* variables, so one image serves anyone's URLs.
# Only VITE_* names are exported — they're public by design (the browser sees them). The same check as
# vite.config.js refuses names that look like secrets.
set -eu
out=/usr/share/nginx/html/config.js
secret='(^|_)(KEY|APIKEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|CREDENTIALS?)(_|$)'

if env | grep -E '^VITE_[A-Z0-9_]+=' | cut -d= -f1 | grep -Eiq "$secret"; then
  echo "baton: refusing to expose a VITE_* variable that looks like a secret to the browser" >&2
  exit 1
fi

{
  printf 'window.__BATON_CONFIG__ = {'
  sep=''
  env | grep -E '^VITE_[A-Z0-9_]+=' | sort | while IFS='=' read -r name value; do
    escaped=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '%s"%s": "%s"' "$sep" "$name" "$escaped"
    sep=', '
  done
  printf '};\n'
} > "$out"
echo "baton: wrote $out"
