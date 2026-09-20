#!/usr/bin/env sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example and fill every secret." >&2
  exit 1
fi

mkdir -p runtime/openclaw/config runtime/openclaw/workspace runtime/openclaw/auth-secrets runtime/certbot
chmod 700 runtime/openclaw/config runtime/openclaw/auth-secrets

docker compose config --quiet
docker compose build api openclaw-gateway
docker compose up -d
docker compose ps

echo "API health: https://<your-domain>/health"
echo "Gateway UI: ssh -L 18789:127.0.0.1:18789 <server>"
