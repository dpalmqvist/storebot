# Storebot

AI-powered agent for managing a Swedish country shop ("Lanthandel") that sells renovated furniture, decor, curiosities, antiques, and crops. The owner interacts with the system through a Telegram bot backed by Claude.

## How it works

```
Telegram Bot  →  Claude API (tool use, vision)
                       |
                 Agent Tool Modules
                 ├── Tradera (SOAP)       - search, list, sell
                 ├── Blocket (REST)       - price research
                 ├── Accounting           - vouchers + PDF export
                 ├── Scout                - saved searches, daily digests
                 ├── Marketing            - performance tracking
                 ├── Order                - sales, shipping, invoicing
                 ├── PostNord (REST)      - shipping labels
                 └── Image (Pillow)       - resize, optimize, vision
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
# Edit .env with your API keys (see Configuration below)

# Run the bot
storebot
```

The database is created automatically on first run via Alembic migrations. No manual initialization needed.

## Configuration

All configuration is via environment variables, loaded from `.env` by default.

### Required

| Variable | Description |
|----------|-------------|
| `CLAUDE_API_KEY` | Anthropic API key for Claude |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TRADERA_APP_ID` | Tradera developer app ID |
| `TRADERA_APP_KEY` | Tradera developer app key |

### Tradera seller authorization

These are set automatically by the `storebot-authorize-tradera` CLI command (see [Tradera authorization](#tradera-authorization) below).

| Variable | Description |
|----------|-------------|
| `TRADERA_PUBLIC_KEY` | Public key for token login URL |
| `TRADERA_USER_ID` | Seller user ID (from consent flow) |
| `TRADERA_USER_TOKEN` | Seller token (from consent flow) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_MODEL` | `claude-sonnet-4-5-20250929` | Claude model for the agent loop |
| `TRADERA_SANDBOX` | `true` | Use Tradera sandbox environment |
| `BLOCKET_BEARER_TOKEN` | | Blocket bearer token for price research |
| `POSTNORD_API_KEY` | | PostNord API key for shipping labels |
| `POSTNORD_SENDER_NAME` | | Sender name for shipping labels |
| `POSTNORD_SENDER_ADDRESS` | | Sender address for shipping labels |
| `ORDER_POLL_INTERVAL_MINUTES` | `30` | How often to poll Tradera for new orders |
| `MAX_HISTORY_MESSAGES` | `20` | Conversation history length per chat |
| `CONVERSATION_TIMEOUT_MINUTES` | `60` | Auto-reset conversation after inactivity |
| `SCOUT_DIGEST_HOUR` | `8` | Hour (0-23) for daily scout digest |
| `MARKETING_REFRESH_HOUR` | `7` | Hour (0-23) for daily marketing stats refresh |
| `DATABASE_PATH` | `data/storebot.db` | SQLite database path |
| `VOUCHER_EXPORT_PATH` | `data/vouchers` | Directory for exported voucher PDFs |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_JSON` | `true` | JSON structured logging (set `false` for human-readable) |

## Setting up services

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
3. Set `TRADERA_APP_ID` and `TRADERA_APP_KEY` in `.env`
4. Keep `TRADERA_SANDBOX=true` during development

**Rate limits:** 100 API calls per 24 hours (can request an increase from Tradera).

WSDL endpoints:
- SearchService: `https://api.tradera.com/v3/searchservice.asmx?WSDL`
- PublicService: `https://api.tradera.com/v3/publicservice.asmx?WSDL`
- RestrictedService: `https://api.tradera.com/v3/restrictedservice.asmx?WSDL`
- OrderService: `https://api.tradera.com/v3/orderservice.asmx?WSDL`

#### Tradera authorization

To create listings and manage orders on Tradera, the bot needs seller authorization. A CLI tool handles the consent flow:

```bash
storebot-authorize-tradera
```

This will:
1. Generate a login URL for the Tradera consent flow
2. Prompt you to visit the URL and authorize the application
3. Fetch and save `TRADERA_USER_ID` and `TRADERA_USER_TOKEN` to your `.env` file

You need `TRADERA_APP_ID`, `TRADERA_APP_KEY`, and `TRADERA_PUBLIC_KEY` set before running this command.

### Blocket

Blocket has no official public API. Storebot uses an unofficial REST endpoint for **read-only** price research.

1. Log in to Blocket in your browser
2. Open DevTools (F12) > Network tab
3. Search for something on Blocket and find a request to `blocket.se/recommerce/forsale/search/api/search`
4. Copy the `Authorization: Bearer <token>` header value
5. Set `BLOCKET_BEARER_TOKEN` in `.env`

**Note:** The token expires periodically and must be manually renewed. The bot works without it but Blocket price research will be unavailable.

### PostNord

PostNord integration for generating shipping labels.

1. Register at [PostNord Developer Portal](https://developer.postnord.com/)
2. Create an application and get an API key
3. Set `POSTNORD_API_KEY` and sender details (`POSTNORD_SENDER_NAME`, `POSTNORD_SENDER_STREET`, `POSTNORD_SENDER_POSTAL_CODE`, `POSTNORD_SENDER_CITY`) in `.env`
4. Keep `POSTNORD_SANDBOX=true` during development (uses `atapi2.postnord.com` instead of `api2.postnord.com`)

**Service codes:** `19` (MyPack Collect), `17` (MyPack Home), `18` (Postpaket).

## Telegram commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and introduction |
| `/help` | Show available commands |
| `/new` | Start a new conversation (resets history) |
| `/orders` | Check for and display new orders |
| `/scout` | Manually trigger saved search scouting |
| `/marketing` | Show listing performance report |

Send any **text message** to chat with the agent. Send a **photo** and the agent will analyze it with vision, describe what it sees, and offer to create a product listing.

## Features

### Listing workflow

1. **Create product** — Send a photo or describe an item. The agent creates a product record with details (condition, materials, era, dimensions, source, acquisition cost).
2. **Price check** — The agent searches Tradera and Blocket for comparable items and suggests a price range based on market data (min/max/mean/median/quartiles).
3. **Draft listing** — The agent generates a Swedish title and description, selects a Tradera category, looks up shipping options based on product weight, and creates a draft listing for review.
4. **Review & approve** — You review the draft and approve or reject it. Rejected drafts can be edited and re-submitted.
5. **Publish** — Approved listings are published to Tradera: images are optimized and uploaded, the listing is created via the SOAP API, and the database is updated.

### Order management

The bot automatically polls Tradera for new orders (configurable interval, default 30 minutes). When a sale is detected:

- The order is imported into the local database
- Product status is updated to "sold"
- Listing status is updated to "sold"
- You can create a sale voucher (automatic VAT/revenue/fee calculation)
- You can generate a PostNord shipping label (requires product weight)
- You can mark orders as shipped (with Tradera notification and tracking number)

Use `/orders` to manually check for new orders.

### Accounting

Storebot includes a local double-entry bookkeeping system using the Swedish BAS-kontoplan (standard chart of accounts).

- **Vouchers** — Every financial transaction creates a voucher with debit/credit rows that must balance
- **Sale vouchers** — Automatically calculated with revenue (3001), VAT (2611), and marketplace fees (6590)
- **Manual vouchers** — Create vouchers for any transaction (purchases, expenses, etc.)
- **PDF export** — Export individual or batch voucher PDFs for manual entry into your external accounting system
- **VAT handling** — Moms at 25% on goods; registration required if turnover > 80,000 kr/year

### Scout Agent

The Scout Agent monitors marketplaces for sourcing opportunities:

- **Saved searches** — Create, update, and delete saved searches with keywords, categories, and price filters
- **Deduplication** — Tracks seen items to avoid showing duplicates
- **Daily digests** — Automatic daily digest at a configurable hour (default 08:00) with new finds
- **Manual trigger** — Use `/scout` to run all saved searches immediately

### Marketing Agent

The Marketing Agent tracks listing performance and suggests optimization strategies:

- **Performance tracking** — Monitors views, bids, watchers, and price changes via `ListingSnapshot` history
- **Listing analysis** — Analyzes individual listings with recommendations
- **Aggregate reports** — Overall performance report across all active listings
- **Recommendations** — Rules-based suggestions: relist, reprice (up/down), improve content, extend duration, category opportunities
- **Daily refresh** — Automatic stats refresh at a configurable hour (default 07:00)
- **Manual trigger** — Use `/marketing` to view the current performance report

### Conversation history

- Messages are persisted per chat in SQLite
- Configurable history length (default: 20 messages) and timeout (default: 60 minutes)
- Image file paths are stored (not base64) and re-encoded when loading history
- Use `/new` to manually reset the conversation

### Image processing

- **Listing images** — Resized to 1200px for marketplace uploads
- **Analysis images** — Resized to 800px for Claude vision
- **Upload optimization** — JPEG compression for bandwidth-efficient uploads
- **Base64 encoding** — For sending images to Claude API
- Handles EXIF rotation and RGBA-to-RGB conversion automatically

## Agent tools

The Claude agent has access to 29 tools organized by domain:

| Domain | Tools |
|--------|-------|
| **Search** | `search_tradera`, `search_blocket`, `price_check` |
| **Products** | `create_product`, `save_product_image`, `search_products` |
| **Listings** | `create_draft_listing`, `list_draft_listings`, `get_draft_listing`, `update_draft_listing`, `approve_draft_listing`, `reject_draft_listing`, `publish_listing`, `get_categories`, `get_shipping_options` |
| **Orders** | `check_new_orders`, `list_orders`, `get_order`, `create_sale_voucher`, `mark_order_shipped`, `create_shipping_label` |
| **Accounting** | `create_voucher`, `export_vouchers` |
| **Scout** | `create_saved_search`, `list_saved_searches`, `update_saved_search`, `delete_saved_search`, `run_saved_search`, `run_all_saved_searches` |
| **Marketing** | `refresh_listing_stats`, `analyze_listing`, `get_performance_report`, `get_recommendations` |

All agent actions are logged to the `agent_actions` table for full audit trail.

## Database

Storebot uses SQLite with WAL mode and busy timeout (5000ms) for concurrent access safety.

**Tables:** `products`, `product_images`, `platform_listings`, `listing_snapshots`, `orders`, `vouchers`, `voucher_rows`, `agent_actions`, `notifications`, `conversation_messages`, `saved_searches`, `seen_items`

### Migrations

Schema changes are managed via [Alembic](https://alembic.sqlalchemy.org/) with SQLite batch mode:

```bash
# Apply pending migrations (also runs automatically on bot startup)
alembic upgrade head

# Create a new migration after changing models in db.py
alembic revision --autogenerate -m "description of change"

# Mark an existing database as up-to-date (no changes applied)
alembic stamp head
```

In tests, Alembic is bypassed and tables are created directly via `create_all()`.

### Backup

A backup script is included for production use:

```bash
# Manual backup
./deploy/backup.sh

# Automated via cron (daily at 03:00)
0 3 * * * /opt/storebot/deploy/backup.sh
```

Backups include integrity verification, gzip compression, and automatic rotation after 30 days. Stored in `/opt/storebot/backups/`.

## Resilience

- **Retry with backoff** — Transient errors from Tradera SOAP, Blocket REST, and PostNord REST are retried with exponential backoff
- **Structured logging** — JSON logging by default (`LOG_JSON=true`), toggle to human-readable for development
- **Credential validation** — API credentials are validated at startup
- **Admin alerts** — Failures in scheduled jobs (order polling, scout digest, marketing refresh) trigger admin notifications
- **SQLite safety** — WAL mode + busy timeout prevent lock contention
- **Systemd restart** — Automatic restart on failure with rate limiting (max 5 restarts per 5 minutes)

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
sudo -u storebot .venv/bin/uv pip install -e .

# Configure
sudo cp .env.example /opt/storebot/.env
sudo chmod 600 /opt/storebot/.env
sudo nano /opt/storebot/.env  # fill in API keys

# Authorize Tradera (if using write operations)
sudo -u storebot .venv/bin/storebot-authorize-tradera

# Install and start the service
sudo cp deploy/storebot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now storebot

# Check status
sudo systemctl status storebot
sudo journalctl -u storebot -f

# Set up daily backups
sudo crontab -u storebot -e
# Add: 0 3 * * * /opt/storebot/deploy/backup.sh
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
  agent.py             Claude API tool loop (29 tools, vision support)
  config.py            Pydantic Settings from .env
  db.py                SQLAlchemy 2.0 models (SQLite, 12 tables)
  cli.py               Tradera authorization CLI
  retry.py             Retry decorator with exponential backoff
  logging_config.py    JSON/human-readable logging config
  bot/
    handlers.py        Telegram bot entry point (6 commands, photo handling)
  tools/
    tradera.py         Tradera SOAP API (search, create, upload, orders, shipping)
    blocket.py         Blocket unofficial REST API (price research)
    accounting.py      Local voucher storage + PDF export (BAS-kontoplan)
    postnord.py        PostNord REST API (shipping labels)
    image.py           Pillow image processing + base64 encoding
    listing.py         Product & listing management (CRUD, drafts, publish)
    pricing.py         Combined price analysis (Tradera + Blocket)
    order.py           Order workflow (import, vouchers, shipping)
    conversation.py    Conversation history persistence
    scout.py           Saved searches + dedup + daily digest
    marketing.py       Listing performance tracking + recommendations
tests/                 404 pytest tests
deploy/
  storebot.service     systemd unit file
  backup.sh            SQLite backup script (cron, gzip, integrity check)
alembic/               Database migration scripts
```

## License

Private repository. All rights reserved.
