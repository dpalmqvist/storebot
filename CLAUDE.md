# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Storebot is an AI-powered agent system for managing a Swedish country shop ("Lantshop") that sells renovated furniture, décor, curiosities, antiques, and crops. The owner interacts with the system primarily through a Telegram bot. Planned launch: November 2026.

## Tech Stack

- **Language:** Python 3.10+
- **LLM:** Claude API (direct integration, no LangChain)
- **Database:** SQLite + sqlite-vec (single-user, simple deployment)
- **Accounting:** Local SQLite vouchers + PDF export (double-entry bookkeeping, BAS-kontoplan)
- **Chat interface:** Telegram via `python-telegram-bot` v20+
- **Marketplace APIs:** Tradera (SOAP via `zeep`), Blocket (unofficial REST via `blocket-api`)
- **Deployment:** Native systemd on Raspberry Pi 5

## Architecture

```
Telegram Bot → Claude API (direct tool use, no framework)
    ↓
Agent Tool Modules (plain Python, MCP-wrappable later)
    ├── tools/tradera.py     (SOAP via zeep)
    ├── tools/blocket.py     (REST, read-only/research)
    ├── tools/accounting.py  (local vouchers + PDF export)
    ├── tools/scout.py       (saved searches, dedup, digest)
    ├── tools/postnord.py    (shipping labels)
    └── tools/image.py       (Pillow: resize, optimize)
    ↓
SQLite + sqlite-vec (operational + financial: inventory, listings, orders, vouchers, agent state, embeddings)
```

### Sub-Agents

- **Listing Agent** — Generates Swedish titles/descriptions, selects Tradera category, sets pricing, uploads images
- **Order Agent** — Monitors sales, updates inventory, generates shipping labels, creates vouchers
- **Pricing Agent** — Searches Tradera + Blocket for comparables, suggests price ranges
- **Scout Agent** — Scheduled searches for sourcing opportunities, sends daily digests
- **Marketing Agent** — Tracks listing performance, suggests strategies

### Key Design Principles

- **Human-in-the-loop by default:** All listings start as drafts requiring approval. Auto-approve can be enabled per category over time.
- **No LangChain:** Use Claude API directly with tool definitions. Simpler debugging, less framework overhead.
- **Plain tools first, MCP later:** Build tool modules as clean Python classes with self-contained interfaces, wrappable as MCP servers when needed.
- **SQLite = single source of truth:** Vouchers stored locally with double-entry bookkeeping. PDF export for manual entry into external accounting system.
- **`agent_actions` table:** Full audit trail of every agent decision for safety and review.
- **JSON for flexibility:** Semi-structured data in `details` columns to avoid premature schema migrations.

## Database Schema (Core Tables)

`products`, `product_images`, `platform_listings`, `orders`, `vouchers`, `voucher_rows`, `agent_actions`, `notifications`, `conversation_messages`, `saved_searches`, `seen_items`

SQLAlchemy 2.0 declarative models in `src/storebot/db.py`. Schema managed via Alembic migrations (SQLite batch mode).

## External API Notes

- **Tradera:** SOAP/XML API, rate limit 100 calls/24h (extendable). Sandbox via `sandbox=1`. Register at Tradera Developer Program.
- **Blocket:** Unofficial, read-only. Bearer token extracted from browser session (expires, needs manual renewal).
- **PostNord:** Shipping label generation API.

## Swedish Business Context

- BAS-kontoplan (standard chart of accounts) stored in `accounting.py` BAS_ACCOUNTS dict
- Moms (VAT): 25% on goods. Registration required if turnover > 80,000 kr/year
- Every transaction requires a verifikation (voucher) — the agent must ensure none are missed
- Vouchers exported as PDF for manual entry into external accounting system

## Implementation Status

### Done

- **Database layer** — SQLAlchemy 2.0 models for all core tables (`products`, `product_images`, `platform_listings`, `orders`, `vouchers`, `voucher_rows`, `agent_actions`, `notifications`, `conversation_messages`). Foreign keys, JSON columns.
- **Alembic migrations** — Versioned schema migrations with SQLite batch mode. Auto-runs on bot startup via `init_db()`. Falls back to `create_all()` when `alembic.ini` absent (tests). For existing databases: `alembic stamp head`.
- **Tradera search** — SOAP via zeep, `SearchAdvanced` with category/price filters, result parsing (bids, buy-now, images). `create_listing`, `get_orders`, `get_item` are stubbed.
- **Blocket search** — Unofficial REST API, read-only price research. `get_ad` is stubbed.
- **Pricing Agent** — `PricingService.price_check()` searches both Tradera + Blocket, computes stats (min/max/mean/median), suggests price range via quartiles, logs `AgentAction`.
- **Listing Agent** — `ListingService` with full draft workflow: `create_draft`, `list_drafts`, `get_draft`, `update_draft`, `approve_draft`, `reject_draft`, `search_products`. All with validation and `AgentAction` audit logging.
- **Product management** — `create_product` (with all optional fields: condition, materials, era, dimensions, source, acquisition_cost) and `save_product_image` (with is_primary logic).
- **Image processing** — `resize_for_listing` (1200px), `resize_for_analysis` (800px), `optimize_for_upload` (JPEG compress), `encode_image_base64`. All handle EXIF rotation and RGBA conversion.
- **Accounting** — `AccountingService` with local voucher storage (SQLite), double-entry bookkeeping with BAS-kontoplan, PDF export (single + batch), debit/credit balance validation.
- **Agent loop** — `agent.py` with Claude API tool loop, 21 tool definitions, vision support (base64 image content blocks), Swedish system prompt with image workflow guidance.
- **Telegram bot** — `handlers.py` with `/start`, `/help`, `/scout`, text message handling, and photo handling (download, resize, forward to agent with vision).
- **Config** — Pydantic Settings from `.env`, all service credentials.
- **Deployment** — systemd service file, SQLite backup script with cron rotation.
- **Order Agent** — `OrderService` with full order workflow: `check_new_orders` (polls Tradera, imports orders, updates listings/products), `get_order`, `list_orders`, `create_sale_voucher` (automatic VAT/revenue/fee calculation), `mark_shipped` (with Tradera notification). Scheduled polling via Telegram `job_queue`.
- **Conversation history** — `ConversationService` persists messages in SQLite per `chat_id`, with configurable message limit and timeout. Stores image file paths (not base64), re-encodes on load. `/new` command to reset. `AgentResponse` dataclass returns full message history from agent.
- **Scout Agent** — `ScoutService` with saved search CRUD (`create_search`, `list_searches`, `update_search`, `delete_search`), per-search and batch execution (`run_search`, `run_all_searches`), deduplication via `SeenItem` table, Swedish digest formatting. Daily scheduled job via Telegram `job_queue` and `/scout` command for manual trigger.
- **Tests** — 232 tests covering db, tradera, blocket, pricing, listing, image, order, accounting, conversation, and scout modules.

### Stubbed (not yet implemented)

- **PostNord** — `PostNordClient` class exists but `create_shipment` and `get_label` raise `NotImplementedError`.
- **Tradera write operations** — `create_listing` is stubbed.
- **Blocket ad detail** — `get_ad` is stubbed.

### Not started

- Marketing Agent (listing performance tracking, strategy suggestions)
- MCP server wrappers for tool modules
- sqlite-vec embeddings for semantic product search
- Social media cross-posting
- Crop management, custom webshop, wishlist matching

## Build Phases

1. **Phase 1 (MVP):** SQLite schema + SQLAlchemy ORM, Tradera/Blocket search tools, Pricing Agent, Listing Agent — **DONE**
2. **Phase 2:** Telegram bot, Order Agent, local voucher/PDF export — **DONE**
3. **Phase 3:** Scout Agent (scheduled) — **DONE**, Marketing Agent, MCP server wrappers, social media cross-posting
4. **Phase 4:** Crop management, custom webshop, wishlist matching, advanced analytics

## Development Setup

```bash
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env  # fill in API keys
```

## Commands

- **Run bot:** `storebot` (or `python -m storebot.bot.handlers`)
- **Run tests:** `pytest`
- **Run single test:** `pytest tests/test_db.py::test_name`
- **Lint:** `ruff check src/ tests/`
- **Format:** `ruff format src/ tests/`
- **Init database:** `python -c "from storebot.db import init_db; init_db()"`
- **Run migrations:** `alembic upgrade head`
- **Create migration:** `alembic revision --autogenerate -m "description"`
- **Stamp existing DB:** `alembic stamp head` (mark existing schema as current, no changes applied)
