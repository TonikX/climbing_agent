#!/usr/bin/env sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

if [ ! -f .env ]; then
  echo "Missing .env" >&2
  exit 1
fi

docker compose build openclaw-gateway

# Fresh installations only. Existing OpenClaw state should be copied to the
# configured persistent directories instead of running onboarding again.
docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js onboard --non-interactive --accept-risk --skip-health \
  --mode local --auth-choice openai-api-key --secret-input-mode ref \
  --gateway-auth token --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
  --skip-channels --no-install-daemon

docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js channels add --channel telegram --use-env

docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js plugins install --link /opt/climbing-journal --force --accept-capabilities

docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js plugins enable climbing-journal --accept-capabilities

docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js config set tools.alsoAllow \
  '["start_climbing_training","append_climbing_attempt","update_climbing_attempt","delete_climbing_attempt","finish_climbing_training","get_current_climbing_training","get_climbing_statistics","save_climbing_training","update_climbing_training","upsert_climbing_gear","find_climbing_routes","get_climbing_trainings"]' \
  --strict-json

docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js config set plugins.entries.codex.config.codexDynamicToolsLoading direct

docker compose up -d
