#!/usr/bin/env bash
# SQLite backup script — run via cron daily
# Example crontab: 0 3 * * * /opt/storebot/deploy/backup.sh

set -euo pipefail

DB_PATH="${DB_PATH:-/opt/storebot/data/storebot.db}"
BACKUP_DIR="${BACKUP_DIR:-/opt/storebot/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/storebot_$TIMESTAMP.db"

sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

echo "Backup created: $BACKUP_FILE"

# Remove backups older than KEEP_DAYS
find "$BACKUP_DIR" -name "storebot_*.db" -mtime +"$KEEP_DAYS" -delete

echo "Cleanup done (kept last $KEEP_DAYS days)"
