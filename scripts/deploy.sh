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
docker compose exec -T openclaw-gateway sh -c '
  mkdir -p /home/node/.openclaw/workspace/skills/climbing-journal \
    /home/node/.openclaw/agents/main/agent/workshop-skills/climbing-journal
  cp /opt/climbing-journal/skills/climbing-journal/SKILL.md \
    /home/node/.openclaw/workspace/skills/climbing-journal/SKILL.md
  cp /opt/climbing-journal/skills/climbing-journal/SKILL.md \
    /home/node/.openclaw/agents/main/agent/workshop-skills/climbing-journal/SKILL.md
'
docker compose exec -T openclaw-gateway node dist/index.js config patch \
  --file /opt/climbing-journal/deploy/openclaw/cloudru-deepseek.json
docker compose restart openclaw-gateway
docker compose ps

echo "API health: https://<your-domain>/health"
echo "Gateway UI: ssh -L 18789:127.0.0.1:18789 <server>"
