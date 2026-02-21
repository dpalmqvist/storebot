# Installation & Setup

## Prerequisites

- **Python 3.10+** (developed and tested with 3.13)
- **[uv](https://docs.astral.sh/uv/)** package manager
- **sqlite3** CLI tool (`sudo apt install sqlite3` on Debian/Ubuntu) — required by the backup script
- API keys for the services below

## Clone and Install

```bash
git clone <repo-url> && cd storebot

# Create virtual environment and install
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Configuration

All configuration is via environment variables, loaded from `.env` by default.

```bash
cp .env.example .env
# Edit .env with your API keys
```

### Required Variables

| Variable | Description |
|----------|-------------|
| `CLAUDE_API_KEY` | Anthropic API key for Claude |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TRADERA_APP_ID` | Tradera developer application ID |
| `TRADERA_APP_KEY` | Tradera developer application key |

### Tradera Seller Authorization

These are set automatically by the `storebot-authorize-tradera` CLI command (see [Tradera setup](#tradera) below).

| Variable | Description |
|----------|-------------|
| `TRADERA_PUBLIC_KEY` | Public key for token login URL |
| `TRADERA_USER_ID` | Seller user ID (from consent flow) |
| `TRADERA_USER_TOKEN` | Seller token (from consent flow) |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| **Claude** | | |
| `CLAUDE_MODEL` | `claude-sonnet-4-5-20250929` | Claude model for the agent loop |
| **Tradera** | | |
| `TRADERA_SANDBOX` | `true` | Use Tradera sandbox environment |
| **PostNord** | | |
| `POSTNORD_API_KEY` | *(empty)* | PostNord API key for shipping labels |
| `POSTNORD_SANDBOX` | `true` | Use PostNord sandbox (`atapi2.postnord.com` instead of `api2.postnord.com`) |
| `POSTNORD_SENDER_NAME` | *(empty)* | Sender name on shipping labels |
| `POSTNORD_SENDER_STREET` | *(empty)* | Sender street address |
| `POSTNORD_SENDER_POSTAL_CODE` | *(empty)* | Sender postal code |
| `POSTNORD_SENDER_CITY` | *(empty)* | Sender city |
| `POSTNORD_SENDER_COUNTRY_CODE` | `SE` | Sender country code |
| `POSTNORD_SENDER_PHONE` | *(empty)* | Sender phone number |
| `POSTNORD_SENDER_EMAIL` | *(empty)* | Sender email address |
| `LABEL_EXPORT_PATH` | `data/labels` | Directory for exported shipping label PDFs |
| **Scheduling** | | |
| `ORDER_POLL_INTERVAL_MINUTES` | `30` | How often to poll Tradera for new orders |
| `SCOUT_DIGEST_HOUR` | `8` | Hour (0-23) for daily scout digest |
| `MARKETING_REFRESH_HOUR` | `7` | Hour (0-23) for daily marketing stats refresh |
| **Conversation** | | |
| `MAX_HISTORY_MESSAGES` | `20` | Conversation history length per chat |
| `CONVERSATION_TIMEOUT_MINUTES` | `60` | Auto-reset conversation after inactivity |
| **Database** | | |
| `DATABASE_PATH` | `data/storebot.db` | SQLite database file path |
| `VOUCHER_EXPORT_PATH` | `data/vouchers` | Directory for exported voucher PDFs |
| **Security** | | |
| `ALLOWED_CHAT_IDS` | *(empty)* | Comma-separated Telegram user/chat IDs. Empty = all allowed (dev mode) |
| `RATE_LIMIT_MESSAGES` | `30` | Max messages per rate limit window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window duration in seconds |
| **Logging** | | |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `LOG_JSON` | `true` | JSON structured logging. Set `false` for human-readable format |
| `LOG_FILE` | *(empty)* | Optional log file path. When set, adds a rotating file handler (10 MB, 3 backups) |

## External Service Setup

### Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. Copy the bot token and set `TELEGRAM_BOT_TOKEN` in `.env`
4. Optionally send `/setdescription` and `/setabouttext` to configure the bot profile
5. Send `/setcommands` and paste:
   ```
   start - Starta boten
   help - Visa hjälp
   new - Ny konversation
   orders - Visa ordrar
   scout - Kör scouting nu
   marketing - Visa marknadsföringsrapport
   rapport - Affärsrapport
   ```

### Claude API (Anthropic)

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account and add billing
3. Go to **API Keys** and create a new key
4. Set `CLAUDE_API_KEY` in `.env`

The bot uses Claude Sonnet for the agent loop, including vision for photo analysis.

### Tradera

Tradera uses a SOAP/XML API for searching and listing items.

1. Register at the [Tradera Developer Program](https://developer.tradera.com/)
2. Create an application to get your `AppId` and `AppKey`
3. **Request access to restricted APIs** by emailing [apiadmin@tradera.com](mailto:apiadmin@tradera.com) — this is required for creating listings, managing orders, and uploading images (RestrictedService and OrderService)
4. Set `TRADERA_APP_ID` and `TRADERA_APP_KEY` in `.env`
5. Keep `TRADERA_SANDBOX=true` during development

**Rate limits:** 100 API calls per 24 hours (can request an increase from Tradera via [apiadmin@tradera.com](mailto:apiadmin@tradera.com)).

**Customer messaging:** The Tradera SOAP API does not expose any methods for reading or answering buyer questions/messages. Customer communication handling will require email integration (parsing Tradera notification emails via IMAP).

WSDL endpoints:
- SearchService: `https://api.tradera.com/v3/searchservice.asmx?WSDL`
- PublicService: `https://api.tradera.com/v3/publicservice.asmx?WSDL`
- RestrictedService: `https://api.tradera.com/v3/restrictedservice.asmx?WSDL`
- OrderService: `https://api.tradera.com/v3/orderservice.asmx?WSDL`

#### Tradera Authorization

To create listings and manage orders on Tradera, the bot needs seller authorization. A CLI tool handles the consent flow:

```bash
storebot-authorize-tradera
```

This will:
1. Generate a login URL for the Tradera consent flow
2. Prompt you to visit the URL and authorize the application
3. After authorization, you'll be redirected to a localhost URL — copy the **full redirect URL** from your browser's address bar and paste it into the CLI
4. The CLI saves `TRADERA_USER_ID` and `TRADERA_USER_TOKEN` to your `.env` file

**Prerequisites:** `TRADERA_APP_ID`, `TRADERA_APP_KEY`, and `TRADERA_PUBLIC_KEY` must be set before running this command.

### Blocket

Blocket has no official public API. Storebot uses an unofficial REST endpoint for **read-only** price research.

**No configuration needed.** Blocket search works out of the box — no API key or bearer token required. Ad details are retrieved via HTML scraping.

### PostNord

PostNord integration for generating shipping labels.

1. Register at [PostNord Developer Portal](https://developer.postnord.com/)
2. Create an application and get an API key
3. Set `POSTNORD_API_KEY` and sender details in `.env`:
   - `POSTNORD_SENDER_NAME`, `POSTNORD_SENDER_STREET`, `POSTNORD_SENDER_POSTAL_CODE`, `POSTNORD_SENDER_CITY`
   - Optional: `POSTNORD_SENDER_PHONE`, `POSTNORD_SENDER_EMAIL`, `POSTNORD_SENDER_COUNTRY_CODE`
4. Keep `POSTNORD_SANDBOX=true` during development (uses `atapi2.postnord.com` instead of `api2.postnord.com`)

**Service codes:** `19` (MyPack Collect), `17` (MyPack Home), `18` (Postpaket).

## Database Initialization

The database is created automatically on first run via Alembic migrations. No manual initialization needed.

For an existing database that already has the current schema, mark it as up-to-date:

```bash
alembic stamp head
```

## Verification

Run the tests to confirm everything is set up correctly:

```bash
pytest
```

Start the bot:

```bash
storebot
```

Send `/start` in Telegram to verify the bot responds.

## Next Steps

See [Usage Guide](usage.md) for how to use the bot day-to-day.
