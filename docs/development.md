# Development Guide

## Development Setup

```bash
# Clone and create environment
git clone <repo-url> && cd storebot
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — only CLAUDE_API_KEY and TELEGRAM_BOT_TOKEN are required for basic testing
```

See [installation.md](installation.md) for full configuration reference.

## Project Structure

```
src/storebot/
  agent.py             Claude API tool loop (45 tools, vision support)
  config.py            Pydantic Settings from .env
  db.py                SQLAlchemy 2.0 models (SQLite, 12 tables)
  cli.py               Tradera authorization CLI
  retry.py             Retry decorator with exponential backoff
  logging_config.py    JSON/human-readable logging config
  bot/
    handlers.py        Telegram bot entry point (7 commands, photo handling, scheduled jobs)
  tools/
    definitions.py     Tool schemas for Claude API (45 tool definitions)
    tradera.py         Tradera SOAP API (search, create, upload, orders, shipping)
    blocket.py         Blocket unofficial REST API (price research)
    accounting.py      Local voucher storage + PDF export (BAS-kontoplan)
    analytics.py       Business summaries, profitability, inventory, comparisons
    postnord.py        PostNord REST API (shipping labels)
    image.py           Pillow image processing + base64 encoding
    listing.py         Product & listing management (CRUD, drafts, publish)
    pricing.py         Combined price analysis (Tradera + Blocket)
    order.py           Order workflow (import, vouchers, shipping)
    conversation.py    Conversation history persistence
    scout.py           Saved searches + dedup + daily digest
    marketing.py       Listing performance tracking + recommendations
    helpers.py         Shared utilities (log_action, naive_now)
  tui/
    log_viewer.py      Textual TUI for agent_actions audit log
tests/                 pytest tests (18 modules)
deploy/
  storebot.service     systemd unit file
  backup.sh            SQLite backup script (cron, gzip, integrity check)
alembic/               Database migration scripts
```

## Architecture

### Data Flow

```
User (Telegram) → handlers.py → agent.py → Claude API
                                    ↕
                              Tool modules → External APIs (Tradera, Blocket, PostNord)
                                    ↕
                              SQLite (via SQLAlchemy)
```

### Agent Loop

The agent loop in `agent.py` works as follows:

1. Receives a user message (text and/or images) with conversation history
2. Sends to Claude API with the system prompt and 45 tool definitions
3. Claude responds with either text or tool-use requests
4. For each tool use request, the agent dispatches to the appropriate service method
5. Tool results are sent back to Claude for further processing
6. The loop continues until Claude responds with only text (no more tool calls)
7. Returns an `AgentResponse` with the final text, updated message history, and any display images

### Tool Dispatch

Tool definitions live in `tools/definitions.py`. The agent's `execute_tool` method maps tool names (via the `_DISPATCH` dict) to service method calls. Each service is initialized in the `Agent.__init__` method with the shared SQLAlchemy engine and settings.

### Sub-Agents

The system includes specialized service modules that act as sub-agents:

| Agent | Module | Responsibility |
|-------|--------|----------------|
| **Listing** | `tools/listing.py` | Draft workflow, product management, publishing to Tradera |
| **Order** | `tools/order.py` | Order import, voucher creation, shipping labels, status updates |
| **Pricing** | `tools/pricing.py` | Cross-platform price research and statistics |
| **Scout** | `tools/scout.py` | Saved searches, deduplication, digest formatting |
| **Marketing** | `tools/marketing.py` | Listing performance tracking, recommendations |
| **Analytics** | `tools/analytics.py` | Business summaries, profitability, inventory, comparisons |

## Design Principles

- **Human-in-the-loop by default** — All listings start as drafts. Shipping, feedback, and vouchers require explicit approval.
- **No LangChain** — Claude API used directly with tool definitions. Simpler debugging, less framework overhead.
- **Plain tools first, MCP later** — Tool modules as clean Python classes with self-contained interfaces, wrappable as MCP servers when needed.
- **SQLite = single source of truth** — Vouchers stored locally with double-entry bookkeeping. PDF export for manual entry into external accounting system.
- **Audit trail** — Every agent decision is logged to the `agent_actions` table with tool name, input, output, and timestamp.
- **JSON for flexibility** — Semi-structured data in `details` columns to avoid premature schema migrations.

## Database

### SQLAlchemy 2.0 Patterns

Models use the modern declarative style with `Mapped` type hints:

```python
class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
```

Key conventions:
- Use `datetime.now(UTC)` not `datetime.utcnow()` (deprecated in 3.12+)
- Use `sa.inspect(engine).get_table_names()` not `engine.dialect.get_inspector()` (SQLAlchemy 2.0)

### Tables

`products`, `product_images`, `platform_listings`, `listing_snapshots`, `orders`, `vouchers`, `voucher_rows`, `agent_actions`, `notifications`, `conversation_messages`, `saved_searches`, `seen_items`

### Alembic Migrations

Schema changes are managed via Alembic with SQLite batch mode (required because SQLite doesn't support most `ALTER TABLE` operations).

```bash
# Apply pending migrations (also runs automatically on bot startup)
alembic upgrade head

# Create a new migration after changing models in db.py
alembic revision --autogenerate -m "description of change"

# Mark an existing database as up-to-date
alembic stamp head
```

In tests, Alembic is bypassed and tables are created directly via `Base.metadata.create_all()`.

## Adding New Features

### New Agent Tool

1. Add the tool implementation to the relevant service in `src/storebot/tools/`
2. Add the tool definition to `src/storebot/tools/definitions.py` (name, description, input schema)
3. Add dispatch logic in `agent.py`'s `_DISPATCH` dict (used by `execute_tool`)
4. Add tests in `tests/`
5. Update the system prompt in `agent.py` if the tool needs specific usage instructions

### New Telegram Command

1. Add the handler function in `src/storebot/bot/handlers.py`
2. Register it with `app.add_handler(CommandHandler("name", handler_function))` in `main()`
3. Include `_check_access` for authorization and rate limiting
4. Update BotFather commands (see [installation.md](installation.md#telegram-bot))
5. Add tests in `tests/test_handlers.py`

### New Scheduled Job

1. Add the job function in `src/storebot/bot/handlers.py` (follow `poll_orders_job` pattern)
2. Register it in `main()` using `app.job_queue.run_repeating()` or `app.job_queue.run_daily()`
3. Include error handling with `_alert_admin` for failure notifications
4. Add a configurable setting in `src/storebot/config.py` if needed
5. Document the schedule in [usage.md](usage.md#scheduled-jobs)

### New Database Table

1. Add the model class in `src/storebot/db.py` using `Mapped` type hints
2. Create a migration: `alembic revision --autogenerate -m "add table_name table"`
3. Review the generated migration in `alembic/versions/`
4. Test with `alembic upgrade head`
5. Note: the `conftest.py` engine fixture handles `create_all()` for tests automatically — no extra setup needed

## Testing

### Fixtures

`tests/conftest.py` provides three shared fixtures:

- `engine` — In-memory SQLite with all tables created and foreign keys enabled
- `session` — SQLAlchemy session bound to the in-memory database
- `settings` — Test `Settings` instance with dummy API keys

### Running Tests

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_image.py

# Run a specific test
pytest tests/test_image.py::TestResizeForListing::test_shrinks_large_image

# Verbose output
pytest -v
```

### Test Modules

18 test modules covering all core functionality:

| Module | Coverage |
|--------|----------|
| `test_db.py` | SQLAlchemy models, relationships, constraints |
| `test_tradera.py` | SOAP client, search, orders, listing creation |
| `test_blocket.py` | REST client, search, ad details |
| `test_pricing.py` | Price check, statistics calculation |
| `test_listing.py` | Draft workflow, product management, publishing |
| `test_image.py` | Resize, optimize, base64 encoding |
| `test_order.py` | Order import, vouchers, shipping, status |
| `test_accounting.py` | Voucher creation, PDF export, balance validation |
| `test_conversation.py` | History persistence, timeout, clear |
| `test_scout.py` | Saved searches, dedup, digest |
| `test_marketing.py` | Stats refresh, analysis, recommendations |
| `test_analytics.py` | Business summary, profitability, inventory, comparisons |
| `test_postnord.py` | REST client, address parsing, label creation |
| `test_cli.py` | Tradera authorization flow |
| `test_retry.py` | Retry decorator, backoff behavior |
| `test_logging_config.py` | JSON/human formatter, file handler |
| `test_handlers.py` | Telegram command handlers, access control |
| `test_log_viewer.py` | Audit log TUI data queries, filtering, sorting |

### Writing New Tests

Follow existing patterns — use the `engine` and `session` fixtures from `conftest.py`, mock external APIs with `unittest.mock.patch`.

## Code Quality

### Ruff Configuration

From `pyproject.toml`:

```toml
[tool.ruff]
line-length = 99
target-version = "py310"
```

### Commands

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Auto-fix lint issues
ruff check --fix src/ tests/
```

## CI/CD

### GitHub Actions

**`ci.yml`** — Runs on pull requests to `main` with three jobs:

1. **`lint-and-test`** — Gate job that must pass before reviews run:
   - Installs Python 3.13 via uv
   - Installs dependencies with `uv sync --locked --extra dev`
   - Runs `ruff check` and `ruff format --check`
   - Runs `pytest -v`

2. **`claude-review`** — Claude Opus code review (runs after lint-and-test):
   - Uses `claude-code-action` with deep repo context
   - Posts detailed review comments on the PR
   - Requires `CLAUDE_CODE_OAUTH_TOKEN` secret

3. **`openai-review`** — GPT-5.2 Codex code review (runs in parallel with claude-review):
   - Custom stdlib-only Python script (`.github/scripts/openai_review.py`)
   - Fetches PR diff, filters lock files, sends to GPT-5.2 Codex for analysis
   - Posts structured review as PR comment (Summary + Findings with severity)
   - `continue-on-error: true` — API failures don't block merges
   - Requires `OPENAI_API_KEY` secret
   - Size controls: skips diffs > 500KB, truncates at 100KB

## Swedish Business Context

### BAS-kontoplan

The accounting system uses standard Swedish BAS account numbers, defined in `accounting.py`:

- **1930** — Bank account
- **2611** — Outgoing VAT (25%)
- **3001** — Revenue from goods
- **6590** — Marketplace fees

### VAT Rules

- 25% VAT on goods
- Registration required if annual turnover exceeds 80,000 kr
- Every transaction requires a verifikation (voucher)

### Vouchers

Vouchers are the audit trail for every financial transaction. Each voucher:
- Has a sequential number (e.g., `V001`)
- Contains debit and credit rows that must balance
- References the transaction date and optional order ID
- Can be exported as PDF for manual entry into an external accounting system

## Resilience Patterns

### Retry Decorator

`retry.py` provides a decorator for retrying transient errors with exponential backoff. Used on:
- Tradera SOAP API calls
- Blocket REST API calls
- PostNord REST API calls

### Credential Validation

`_validate_credentials()` in `handlers.py` checks API keys at startup and logs errors/warnings for missing ones. The bot still starts — features with missing credentials are simply disabled.

### Admin Alerts

Failures in scheduled jobs trigger Telegram messages to the owner. The `_alert_admin` function sends messages to the first chat that used `/start`.
