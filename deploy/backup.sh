#!/usr/bin/env bash
# SQLite backup script — run via cron daily
# Example crontab: 0 3 * * * /opt/storebot/deploy/backup.sh

set -euo pipefail

DB_PATH="${DB_PATH:-/opt/storebot/data/storebot.db}"
BACKUP_DIR="${BACKUP_DIR:-/opt/storebot/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
BACKUP_KEY_FILE="${BACKUP_KEY_FILE:-/opt/storebot/.backup_key}"
STATUS_FILE="$BACKUP_DIR/.backup_status"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/storebot_$TIMESTAMP.db"

logger -t storebot-backup "Starting backup of $DB_PATH"

sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

# Verify backup integrity
if sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" | grep -q "^ok$"; then
    logger -t storebot-backup "Integrity check passed: $BACKUP_FILE"
else
    logger -t storebot-backup "ERROR: Integrity check failed, removing corrupt backup"
    rm -f "$BACKUP_FILE"
    echo "FAILED: integrity_check $(date -Iseconds)" > "$STATUS_FILE"
    exit 1
fi

# Compress backup
gzip "$BACKUP_FILE"
logger -t storebot-backup "Backup compressed: ${BACKUP_FILE}.gz"

# Encrypt backup if key file exists (contains PII and financial data)
if [ -f "$BACKUP_KEY_FILE" ]; then
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase-file "$BACKUP_KEY_FILE" \
        -o "${BACKUP_FILE}.gz.gpg" "${BACKUP_FILE}.gz"
    rm -f "${BACKUP_FILE}.gz"
    logger -t storebot-backup "Backup encrypted: ${BACKUP_FILE}.gz.gpg"
    echo "OK: ${BACKUP_FILE}.gz.gpg $(date -Iseconds)" > "$STATUS_FILE"
else
    logger -t storebot-backup "WARNING: No backup key file at $BACKUP_KEY_FILE — backup NOT encrypted"
    echo "OK (unencrypted): ${BACKUP_FILE}.gz $(date -Iseconds)" > "$STATUS_FILE"
fi

# Remove backups older than KEEP_DAYS
find "$BACKUP_DIR" -name "storebot_*.db" -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name "storebot_*.db.gz" -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name "storebot_*.db.gz.gpg" -mtime +"$KEEP_DAYS" -delete

logger -t storebot-backup "Cleanup done (kept last $KEEP_DAYS days)"
