#!/usr/bin/env bash
#
# Epic 11 — "Daily Postgres backup + one tested restore" (locked AC).
#
# This script is the restore half: it takes a dump produced by
# backup.sh and restores it into a target database, with --clean
# --if-exists so it can run against a database that already has the
# schema in it (drops each object before recreating it) as well as a
# genuinely empty one.
#
# By design this REFUSES to run without an explicit --yes — restoring
# overwrites whatever is currently in the target database, and the whole
# point of "one tested restore" is proving the backup is actually usable,
# not risking a real venue's live data with a slipped keystroke.
#
# Usage:
#   ./scripts/restore.sh backups/mise_dev_20260917T000000Z.dump --yes \
#       --target postgresql://mise:mise_dev_pw@localhost:5432/mise_restore_check
#
# See docs/EPIC_11_BACKUP_RESTORE.md (referenced from the README) for the
# full tested-restore walkthrough this script was run through.

set -euo pipefail

usage() {
    echo "Usage: $0 <dump_file> --yes --target <DATABASE_URL>" >&2
    exit 1
}

dump_file=""
target_url=""
confirmed="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes)
            confirmed="true"
            shift
            ;;
        --target)
            target_url="$2"
            shift 2
            ;;
        *)
            if [[ -z "$dump_file" ]]; then
                dump_file="$1"
                shift
            else
                usage
            fi
            ;;
    esac
done

if [[ -z "$dump_file" || -z "$target_url" ]]; then
    usage
fi

if [[ "$confirmed" != "true" ]]; then
    echo "Refusing to restore without --yes — this OVERWRITES the target database." >&2
    usage
fi

if [[ ! -f "$dump_file" ]]; then
    echo "No such dump file: $dump_file" >&2
    exit 1
fi

echo "Restoring $dump_file into target database ..."
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$target_url" "$dump_file"
echo "Restore complete."
