#!/usr/bin/env bash
# Configure a remote host and age recipient explicitly. Run under a daily systemd timer.
set -euo pipefail
umask 077
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${PUBLIC_BACKUP_AGE_RECIPIENT:?Set the age encryption recipient}"
: "${PUBLIC_BACKUP_SSH_TARGET:?Set an off-server rsync destination}"
command -v age >/dev/null
command -v rsync >/dev/null
task_backup_root="${PUBLIC_BACKUP_ROOT:-./runtime/public-backups}"
mkdir -p "$task_backup_root"
task_stamp=$(date -u +%Y%m%dT%H%M%SZ)
task_dump="$task_backup_root/$task_stamp.dump.age"
task_ledger="$task_backup_root/$task_stamp.ledger.json.age"
# No plaintext journal dump or ledger is written to disk.
docker compose --env-file .env.public -f compose.public.yaml exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' | age -r "$PUBLIC_BACKUP_AGE_RECIPIENT" -o "$task_dump"
docker compose --env-file .env.public -f compose.public.yaml exec -T api \
  python -m app.deletion_ledger --export | age -r "$PUBLIC_BACKUP_AGE_RECIPIENT" -o "$task_ledger"
test -s "$task_dump"
test -s "$task_ledger"
rsync -e ssh -- "$task_dump" "$task_ledger" "$PUBLIC_BACKUP_SSH_TARGET"
printf '%s\n' "$task_stamp" > "$task_backup_root/last-offsite-success"
# Operator sets retention on the encrypted local/remote backup repositories to 30 days.
