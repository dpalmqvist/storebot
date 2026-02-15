# Maintenance & Operations

## Deployment to Raspberry Pi 5

### System Setup

```bash
# Install system dependencies
sudo apt install sqlite3

# Create a system user
sudo useradd -r -s /usr/sbin/nologin storebot

# Set up the application
sudo mkdir -p /opt/storebot
sudo cp -r . /opt/storebot/
sudo chown -R storebot:storebot /opt/storebot

# Create venv and install
cd /opt/storebot
sudo -u storebot uv venv --python 3.13
sudo -u storebot .venv/bin/uv pip install -e .

# Configure
sudo cp .env.example /opt/storebot/.env
sudo chmod 600 /opt/storebot/.env
sudo nano /opt/storebot/.env  # fill in API keys

# Authorize Tradera (if using write operations)
sudo -u storebot .venv/bin/storebot-authorize-tradera
```

### Directory Structure

```
/opt/storebot/
  .env                   Configuration (chmod 600)
  .venv/                 Python virtual environment
  src/storebot/          Application code
  deploy/                Service + backup scripts
  data/
    storebot.db          SQLite database
    photos/              Downloaded Telegram photos
    vouchers/            Exported voucher PDFs
    labels/              Exported shipping label PDFs
  backups/               Daily database backups
```

## systemd Service

Install and manage the service:

```bash
# Install
sudo cp deploy/storebot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now storebot

# Manage
sudo systemctl status storebot
sudo systemctl restart storebot
sudo systemctl stop storebot

# View logs
sudo journalctl -u storebot -f
sudo journalctl -u storebot --since "1 hour ago"
```

### Service Configuration

The service file (`deploy/storebot.service`) includes:

| Directive | Value | Purpose |
|-----------|-------|---------|
| `User` | `storebot` | Runs as dedicated system user |
| `WorkingDirectory` | `/opt/storebot` | Application root |
| `EnvironmentFile` | `/opt/storebot/.env` | Loads configuration |
| `Restart` | `on-failure` | Auto-restart on crash |
| `RestartSec` | `10` | Wait 10 seconds between restarts |
| `StartLimitBurst` | `5` | Max 5 restarts per 5 minutes |
| `TimeoutStopSec` | `30` | Graceful shutdown timeout |

### Security Hardening

The systemd unit includes these security directives:

| Directive | Effect |
|-----------|--------|
| `PrivateTmp=yes` | Isolates `/tmp` from other services |
| `NoNewPrivileges=yes` | Prevents privilege escalation |
| `ProtectSystem=strict` | Makes filesystem read-only except allowed paths |
| `ProtectHome=yes` | Blocks access to home directories |
| `ReadWritePaths` | Only `/opt/storebot/data` and `/opt/storebot/backups` are writable |
| `RestrictAddressFamilies` | Only UNIX, IPv4, and IPv6 sockets allowed |
| `MemoryMax=512M` | Hard memory limit |

## Backups

### Setup

```bash
# Set up daily backups via cron
sudo crontab -u storebot -e
# Add: 0 3 * * * /opt/storebot/deploy/backup.sh
```

### What the Backup Script Does

1. Creates a SQLite backup using `.backup` (safe, consistent snapshot)
2. Runs `PRAGMA integrity_check` on the backup to verify it
3. Compresses with gzip
4. Encrypts with GPG (AES-256) if a key file exists at `/opt/storebot/.backup_key`
5. Removes backups older than 30 days
6. Writes status to `/opt/storebot/backups/.backup_status`

### Encryption Setup

```bash
# Create a backup encryption key
sudo -u storebot bash -c 'openssl rand -base64 32 > /opt/storebot/.backup_key'
sudo chmod 600 /opt/storebot/.backup_key
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `/opt/storebot/data/storebot.db` | Database to back up |
| `BACKUP_DIR` | `/opt/storebot/backups` | Backup destination |
| `KEEP_DAYS` | `30` | Retention period in days |
| `BACKUP_KEY_FILE` | `/opt/storebot/.backup_key` | GPG encryption key file |

### Manual Backup

```bash
sudo -u storebot /opt/storebot/deploy/backup.sh
```

### Verify Backup

```bash
# Check status
cat /opt/storebot/backups/.backup_status

# Test restore (encrypted)
gpg --batch --passphrase-file /opt/storebot/.backup_key \
    -d /opt/storebot/backups/storebot_YYYYMMDD_HHMMSS.db.gz.gpg | \
    gunzip > /tmp/storebot_restore_test.db
sqlite3 /tmp/storebot_restore_test.db "PRAGMA integrity_check;"

# Test restore (unencrypted)
gunzip -k /opt/storebot/backups/storebot_YYYYMMDD_HHMMSS.db.gz
sqlite3 /opt/storebot/backups/storebot_YYYYMMDD_HHMMSS.db "PRAGMA integrity_check;"
```

## Database Maintenance

### WAL Mode and Busy Timeout

SQLite is configured with WAL mode and a 5-second busy timeout on startup (`_configure_sqlite` in `db.py`). This allows concurrent reads during writes and prevents immediate lock errors.

### Integrity Check

```bash
sqlite3 /opt/storebot/data/storebot.db "PRAGMA integrity_check;"
```

### Migration Workflow

Schema changes are managed via Alembic with SQLite batch mode:

```bash
# Apply pending migrations (also runs automatically on bot startup)
alembic upgrade head

# Create a new migration after changing models in db.py
alembic revision --autogenerate -m "description of change"

# Mark an existing database as up-to-date (no changes applied)
alembic stamp head
```

In tests, Alembic is bypassed and tables are created directly via `create_all()`.

## Logging & Monitoring

### Log Formats

- **JSON** (default, `LOG_JSON=true`): Machine-readable, single-line JSON objects — ideal for production and `journalctl`
- **Human-readable** (`LOG_JSON=false`): Traditional `timestamp - logger - level - message` format for development

### Structured Fields

JSON logs include these extra fields when available: `chat_id`, `order_id`, `listing_id`, `tool_name`, `job_name`.

### File Logging

Set `LOG_FILE` to enable a rotating file handler (10 MB max, 3 backups) alongside stdout.

### Viewing Logs

```bash
# Follow live logs
sudo journalctl -u storebot -f

# Last hour
sudo journalctl -u storebot --since "1 hour ago"

# Filter errors
sudo journalctl -u storebot -p err

# JSON parsing with jq
sudo journalctl -u storebot -o cat | jq 'select(.level == "ERROR")'
```

### Admin Alerts

Failures in scheduled jobs (order polling, scout digest, marketing refresh, weekly comparison) trigger Telegram messages to the owner chat ID. These are sent automatically — no configuration needed beyond having sent `/start` at least once.

## Troubleshooting

### Bot Not Responding

1. Check service status: `sudo systemctl status storebot`
2. Check logs: `sudo journalctl -u storebot --since "10 minutes ago"`
3. Verify `TELEGRAM_BOT_TOKEN` is correct
4. Verify `CLAUDE_API_KEY` is valid and has billing
5. Restart: `sudo systemctl restart storebot`

### Blocket Token Expired

The Blocket bearer token expires periodically. Symptoms: Blocket searches return errors or empty results.

1. Log in to Blocket in your browser
2. Extract a fresh token from DevTools (see [installation](installation.md#blocket))
3. Update `BLOCKET_BEARER_TOKEN` in `.env`
4. Restart the service

The bot functions without Blocket — only Blocket price research is affected.

### Tradera Rate Limits

Tradera allows 100 API calls per 24 hours by default. If you hit the limit:

1. Check logs for rate limit errors
2. Increase `ORDER_POLL_INTERVAL_MINUTES` to poll less frequently
3. Request a rate limit increase by emailing [apiadmin@tradera.com](mailto:apiadmin@tradera.com)

### SQLite Lock Contention

Symptoms: "database is locked" errors in logs.

WAL mode and a 5-second busy timeout should handle normal concurrency. If you see persistent lock errors:

1. Check for long-running queries or external tools holding the database open
2. Ensure only one instance of the bot is running
3. Check disk space — WAL mode needs write access

### Missing Credentials at Startup

The bot validates credentials on startup and logs warnings for missing ones:

- `TELEGRAM_BOT_TOKEN` — **Error**: Bot cannot start
- `CLAUDE_API_KEY` — **Error**: Agent will not work
- `TRADERA_APP_ID`/`TRADERA_APP_KEY` — **Warning**: Tradera features disabled
- `BLOCKET_BEARER_TOKEN` — **Warning**: Blocket search disabled
- `POSTNORD_API_KEY` — **Warning**: Shipping labels disabled

## Update Procedure

```bash
cd /opt/storebot

# Pull latest code
sudo -u storebot git pull

# Install updated dependencies
sudo -u storebot .venv/bin/uv pip install -e .

# Apply database migrations (if any)
sudo -u storebot .venv/bin/alembic upgrade head

# Restart the service
sudo systemctl restart storebot

# Verify
sudo systemctl status storebot
sudo journalctl -u storebot --since "1 minute ago"
```

## Security

### File Permissions

```bash
# .env contains API keys — restrict access
sudo chmod 600 /opt/storebot/.env
sudo chown storebot:storebot /opt/storebot/.env

# Backup key — restrict access
sudo chmod 600 /opt/storebot/.backup_key

# Backup directory
sudo chmod 700 /opt/storebot/backups
```

### Access Control

Set `ALLOWED_CHAT_IDS` to a comma-separated list of Telegram user IDs to restrict bot access. When empty (default), all users are allowed — suitable for development only.

```bash
# Find your chat ID: send /start and check the logs
ALLOWED_CHAT_IDS=123456789
```

### Rate Limiting

Per-chat rate limiting prevents abuse: max 30 messages per 60 seconds by default. Configure with `RATE_LIMIT_MESSAGES` and `RATE_LIMIT_WINDOW_SECONDS`.
