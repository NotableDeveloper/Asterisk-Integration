#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "$(uname)" = Darwin ] && [ -f /etc/ssl/cert.pem ]; then
  export SSL_CERT_FILE="${SSL_CERT_FILE:-/etc/ssl/cert.pem}"
fi
python3 scripts/download_models.py
docker compose build
docker compose up -d --force-recreate --wait
printf '\nAgent Assist: http://localhost:8000\n'
