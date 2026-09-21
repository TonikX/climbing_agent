#!/bin/sh
set -eu

data_dir="${1:-/srv/climbing-journal/openclaw/workspace/data}"
backup_dir="${2:-/srv/climbing-journal/backups}"
backup_name="journal-data-before-db-sync-$(date -u +%Y%m%dT%H%M%SZ).tar"

mkdir -p "$backup_dir"
tar -C "$(dirname "$data_dir")" -cf "$backup_dir/$backup_name" "$(basename "$data_dir")"

container_id="$(docker compose ps -q api)"
if [ -z "$container_id" ]; then
  echo "API container is not running" >&2
  exit 1
fi

docker cp "$data_dir/." "$container_id:/tmp/journal-data"
docker compose exec -T api python -c '
import json
import os
import urllib.request

names = ("users", "areas", "sectors", "routes", "gear", "trainings")
body = json.dumps({
    name: json.load(open(f"/tmp/journal-data/{name}.json", encoding="utf-8"))
    for name in names
}).encode()
request = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/journal/snapshot",
    data=body,
    method="PUT",
    headers={"Content-Type": "application/json", "X-API-Key": os.environ["INTERNAL_API_KEY"]},
)
print(urllib.request.urlopen(request, timeout=30).read().decode())
'

echo "Backup: $backup_dir/$backup_name"
