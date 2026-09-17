#!/usr/bin/env bash
#
# Epic 11 — "Daily Postgres backup + one tested restore" (locked AC).
#
# This script is the backup half: it takes one pg_dump snapshot of the
# Mise database, in pg_restore's custom format (-Fc — compressed, and the
# only format pg_restore's --clean/--if-exists selective-restore flags
# work against), into $BACKUP_DIR, named with a UTC timestamp so nothing
# ever overwrites a previous backup.
#
# It reads connection details from DATABASE_URL (the same variable
# app/core/config.py's Settings.database_url reads), matching this
# project's convention of one connection string as the single source of
# truth rather than a second set of PG* variables to keep in sync. Running
# this daily (cron / a scheduled task in whatever's hosting the pilot
# venue's Postgres) is the "daily backup" half of the locked AC; actually
# running it on a schedule in production is a deployment/ops concern
# outside what this backend build can demonstrate — see restore.sh and the
# README's Epic 11 section for what IS demonstrated here.
#
# Usage:
#   DATABASE_URL=postgresql://user:pass@host:5432/dbname ./scripts/backup.sh
#   ./scripts/backup.sh                          # uses the dev default below
#   BACKUP_DIR=/some/other/path ./scripts/backup.sh

set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgresql://mise:mise_dev_pw@localhost:5432/mise_dev}"
BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backups}"

mkdir -p "$BACKUP_DIR"

# Extract the database name for the filename (pg_dump takes the full URL
# via -d, but a bare filename shouldn't embed the whole connection string,
# credentials included).
db_name="$(python3 -c "
import sys
from urllib.parse import urlsplit
print(urlsplit(sys.argv[1]).path.lstrip('/'))
" "$DATABASE_URL")"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_file="$BACKUP_DIR/${db_name}_${timestamp}.dump"

echo "Backing up '$db_name' to $out_file ..."
pg_dump --format=custom --file="$out_file" --dbname="$DATABASE_URL"
echo "Done. $(du -h "$out_file" | cut -f1) written."
