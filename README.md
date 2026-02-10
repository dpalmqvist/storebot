# Storebot

AI-powered agent for managing a Swedish country shop ("Lanthandel") that sells renovated furniture, decor, curiosities, antiques, and crops. The owner interacts with the system through a Telegram bot backed by Claude.

## How it works

```
Telegram Bot  -->  Claude API (tool use)
                        |
                  Agent Tool Modules
                  ├── Tradera (SOAP)     - search & list auctions
                  ├── Blocket (REST)     - price research
                  ├── Fortnox (REST)     - bookkeeping & VAT
                  ├── PostNord (REST)    - shipping labels
                  └── Image (Pillow)     - resize, optimize, vision
                        |
                  SQLite + sqlite-vec
```

Send a photo of an item in Telegram. The agent describes what it sees, creates a product record, searches Tradera and Blocket for comparable prices, drafts a listing for your approval, and logs everything to the database.

All listings start as **drafts** requiring explicit approval before publishing.

## Prerequisites

- Python 3.10+ (developed with 3.13)
- [uv](https://docs.astral.sh/uv/) package manager
- API keys for the services below

## Quick start

```bash
git clone <repo-url> && cd storebot

# Create virtual environment and install
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your API keys (see below)

# Initialize the database
python -c "from storebot.db import init_db; init_db()"

# Run the bot
storebot
```

## Configuration

All configuration is via environment variables, loaded from `.env` by default.

| Variable | Required | Description |
|----------|----------|-------------|
| `CLAUDE_API_KEY` | Yes | Anthropic API key for Claude |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `TRADERA_APP_ID` | Yes | Tradera developer app ID |
| `TRADERA_APP_KEY` | Yes | Tradera developer app key |
| `TRADERA_SANDBOX` | No | Use Tradera sandbox (default: `true`) |
| `FORTNOX_CLIENT_ID` | For bookkeeping | Fortnox OAuth2 client ID |
| `FORTNOX_CLIENT_SECRET` | For bookkeeping | Fortnox OAuth2 client secret |
| `FORTNOX_ACCESS_TOKEN` | For bookkeeping | Fortnox OAuth2 access token |
| `BLOCKET_BEARER_TOKEN` | For price research | Blocket bearer token (from browser session) |
| `DATABASE_PATH` | No | SQLite database path (default: `data/storebot.db`) |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |

## Setting up peripheral services

### Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. Copy the bot token and set `TELEGRAM_BOT_TOKEN` in `.env`
4. Optionally send `/setdescription` and `/setabouttext` to configure the bot profile
5. Send `/setcommands` and paste:
   ```
   start - Starta boten
   help - Visa hjälp
   ```

### Claude API (Anthropic)

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account and add billing
3. Go to **API Keys** and create a new key
4. Set `CLAUDE_API_KEY` in `.env`

The bot uses `claude-sonnet-4-5-20250929` for the agent loop, including vision for photo analysis.

### Tradera

Tradera uses a SOAP/XML API for searching and listing items.

1. Register at the [Tradera Developer Program](https://developer.tradera.com/)
2. Create an application to get your `AppId` and `AppKey`
3. Set `TRADERA_APP_ID` and `TRADERA_APP_KEY` in `.env`
4. Keep `TRADERA_SANDBOX=true` during development

**Rate limits:** 100 API calls per 24 hours (can request an increase from Tradera).

WSDL endpoints:
- SearchService: `https://api.tradera.com/v3/searchservice.asmx?WSDL`
- PublicService: `https://api.tradera.com/v3/publicservice.asmx?WSDL`
- RestrictedService: `https://api.tradera.com/v3/restrictedservice.asmx?WSDL`
- OrderService: `https://api.tradera.com/v3/orderservice.asmx?WSDL`

### Blocket

Blocket has no official public API. Storebot uses an unofficial REST endpoint for **read-only** price research.

1. Log in to Blocket in your browser
2. Open DevTools (F12) > Network tab
3. Search for something on Blocket and find a request to `blocket.se/recommerce/forsale/search/api/search`
4. Copy the `Authorization: Bearer <token>` header value
5. Set `BLOCKET_BEARER_TOKEN` in `.env`

**Note:** The token expires periodically and must be manually renewed. The bot works without it but search results may be limited.

### Fortnox

Fortnox handles all bookkeeping (vouchers, invoices, VAT). It is the financial source of truth.

1. Apply for a [Fortnox developer account](https://developer.fortnox.se/)
2. Create an application and configure OAuth2 redirect URIs
3. Complete the OAuth2 authorization flow to obtain tokens
4. Set `FORTNOX_CLIENT_ID`, `FORTNOX_CLIENT_SECRET`, and `FORTNOX_ACCESS_TOKEN` in `.env`

**Swedish business context:**
- Uses BAS-kontoplan (standard Swedish chart of accounts)
- Every transaction requires a verifikation (voucher)
- Moms (VAT) at 25% on goods; registration required if turnover > 80,000 kr/year
- SIE file export for Skatteverket compliance is handled by Fortnox

### PostNord (planned)

Shipping label generation is stubbed out for future implementation.

1. Register at [PostNord Developer Portal](https://developer.postnord.com/)
2. Create an application and get an API key
3. A `POSTNORD_API_KEY` setting will be added when this integration is implemented

## Database

Storebot uses SQLite with the [sqlite-vec](https://github.com/asg017/sqlite-vec) extension for vector search (optional, loaded if available).

Tables: `products`, `product_images`, `platform_listings`, `orders`, `agent_actions`, `notifications`

The database is created automatically on first run. No migration tool is used yet (early development uses `create_all()`).

### Backup

A backup script is included for production use:

```bash
# Manual backup
./deploy/backup.sh

# Automated via cron (daily at 03:00)
0 3 * * * /opt/storebot/deploy/backup.sh
```

Backups are stored in `/opt/storebot/backups/` and rotated after 30 days.

## Deployment (Raspberry Pi 5)

A systemd service file is provided for production deployment.

```bash
# Create a system user
sudo useradd -r -s /usr/sbin/nologin storebot

# Set up the application
sudo mkdir -p /opt/storebot
sudo cp -r . /opt/storebot/
sudo chown -R storebot:storebot /opt/storebot

# Create venv and install
cd /opt/storebot
sudo -u storebot uv venv --python 3.13
sudo -u storebot .venv/bin/python -m pip install -e .

# Configure
sudo cp .env.example /opt/storebot/.env
sudo chmod 600 /opt/storebot/.env
sudo nano /opt/storebot/.env  # fill in API keys

# Install and start the service
sudo cp deploy/storebot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now storebot

# Check status
sudo systemctl status storebot
sudo journalctl -u storebot -f
```

## Development

```bash
# Run tests
pytest

# Run a single test
pytest tests/test_image.py::TestResizeForListing::test_shrinks_large_image

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## Project structure

```
src/storebot/
  agent.py             Claude API tool loop with vision support
  config.py            Pydantic Settings from .env
  db.py                SQLAlchemy 2.0 models (SQLite)
  bot/
    handlers.py        Telegram bot entry point
  tools/
    tradera.py         Tradera SOAP API (search, listings)
    blocket.py         Blocket unofficial REST API (price research)
    fortnox.py         Fortnox REST API (bookkeeping)
    postnord.py        PostNord API (shipping labels, stubbed)
    image.py           Pillow image processing + base64 encoding
    listing.py         Product & listing management (CRUD, drafts)
    pricing.py         Combined price analysis (Tradera + Blocket)
tests/                 pytest test suite
deploy/
  storebot.service     systemd unit file
  backup.sh            SQLite backup script (cron)
```

## License

Private repository. All rights reserved.
