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
    ├── tools/listing.py     (draft workflow, product mgmt, publish)
    ├── tools/pricing.py     (cross-platform price analysis)
    ├── tools/order.py       (order import, vouchers, shipping)
    ├── tools/accounting.py  (local vouchers + PDF export)
    ├── tools/analytics.py   (business reports, profitability, ROI)
    ├── tools/scout.py       (saved searches, dedup, digest)
    ├── tools/marketing.py   (listing performance, recommendations)
    ├── tools/postnord.py    (shipping labels)
    ├── tools/conversation.py(history persistence per chat)
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

`products`, `product_images`, `platform_listings`, `listing_snapshots`, `orders`, `vouchers`, `voucher_rows`, `agent_actions`, `notifications`, `conversation_messages`, `saved_searches`, `seen_items`

SQLAlchemy 2.0 declarative models in `src/storebot/db.py`. Schema managed via Alembic migrations (SQLite batch mode).

## External API Notes

- **Tradera:** SOAP/XML API, rate limit 100 calls/24h (extendable). Sandbox via `sandbox=1`. Register at Tradera Developer Program. **No messaging/Q&A support** — the SOAP API has no methods for reading or answering buyer questions. Customer communication will require email integration.
- **Blocket:** Unofficial, read-only. Bearer token extracted from browser session (expires, needs manual renewal).
- **PostNord:** REST API for shipping labels. Sandbox: `atapi2.postnord.com`, production: `api2.postnord.com`. API key as query parameter. Service codes: `19` (MyPack Collect), `17` (MyPack Home), `18` (Postpaket).

## Swedish Business Context

- BAS-kontoplan (standard chart of accounts) stored in `accounting.py` BAS_ACCOUNTS dict
- Moms (VAT): 25% on goods. Registration required if turnover > 80,000 kr/year
- Every transaction requires a verifikation (voucher) — the agent must ensure none are missed
- Vouchers exported as PDF for manual entry into external accounting system

## Implementation Status

### Done

- **Database layer** — SQLAlchemy 2.0 models for all core tables (`products`, `product_images`, `platform_listings`, `orders`, `vouchers`, `voucher_rows`, `agent_actions`, `notifications`, `conversation_messages`). Foreign keys, JSON columns.
- **Alembic migrations** — Versioned schema migrations with SQLite batch mode. Auto-runs on bot startup via `init_db()`. Falls back to `create_all()` when `alembic.ini` absent (tests). For existing databases: `alembic stamp head`.
- **Tradera search** — SOAP via zeep, `SearchAdvanced` with category/price filters, result parsing (bids, buy-now, images). `get_orders`, `get_item` for order/item details.
- **Blocket integration** — Unofficial REST API, read-only. `search` for price research/sourcing, `get_ad` for full ad details (description, images, seller, parameters). Agent tools: `search_blocket`, `get_blocket_ad`.
- **Pricing Agent** — `PricingService.price_check()` searches both Tradera + Blocket, computes stats (min/max/mean/median), suggests price range via quartiles, logs `AgentAction`.
- **Listing Agent** — `ListingService` with full draft workflow: `create_draft`, `list_drafts`, `get_draft`, `update_draft`, `approve_draft`, `reject_draft`, `search_products`, `relist_product` (copies ended/sold listings to new draft), `cancel_listing` (local cancellation with Tradera caveat). All with validation and `AgentAction` audit logging.
- **Product management** — `create_product` (with all optional fields: condition, materials, era, dimensions, source, acquisition_cost, weight_grams), `get_product` (full detail lookup with image/listing counts), `save_product_image` (with is_primary logic), and `delete_product_image` (with automatic primary promotion).
- **Image processing** — `resize_for_listing` (1200px), `resize_for_analysis` (800px), `optimize_for_upload` (JPEG compress), `encode_image_base64`. All handle EXIF rotation and RGBA conversion.
- **Accounting** — `AccountingService` with local voucher storage (SQLite), double-entry bookkeeping with BAS-kontoplan, PDF export (single + batch), debit/credit balance validation, `list_vouchers` (with date filtering).
- **Agent loop** — `agent.py` with Claude API tool loop, 52 tool definitions, vision support (base64 image content blocks), Swedish system prompt with image workflow guidance.
- **Telegram bot** — `handlers.py` with `/start`, `/help`, `/new`, `/orders`, `/scout`, `/marketing`, `/rapport`, text message handling, and photo handling (download, resize, forward to agent with vision).
- **Config** — Pydantic Settings from `.env`, all service credentials.
- **Deployment** — systemd service file, SQLite backup script with cron rotation.
- **Order Agent** — `OrderService` with full order workflow: `check_new_orders` (polls Tradera, imports orders, updates listings/products), `get_order`, `list_orders`, `create_sale_voucher` (automatic VAT/revenue/fee calculation), `mark_shipped` (with Tradera notification, persists tracking number), `create_shipping_label` (PostNord integration). Scheduled polling via Telegram `job_queue`.
- **Conversation history** — `ConversationService` persists messages in SQLite per `chat_id`, with configurable message limit and timeout. Stores image file paths (not base64), re-encodes on load. `/new` command to reset. `AgentResponse` dataclass returns full message history from agent.
- **Scout Agent** — `ScoutService` with saved search CRUD (`create_search`, `list_searches`, `update_search`, `delete_search`), per-search and batch execution (`run_search`, `run_all_searches`), deduplication via `SeenItem` table, Swedish digest formatting. Daily scheduled job via Telegram `job_queue` and `/scout` command for manual trigger.
- **Marketing Agent** — `MarketingService` with listing performance tracking (`refresh_listing_stats`, `analyze_listing`), aggregate reporting (`get_performance_report`), and rules-based recommendations (6 types: relist, reprice_lower, reprice_raise, improve_content, extend_duration, category_opportunity). `ListingSnapshot` model for historical tracking. Telegram `/marketing` command and daily scheduled stats refresh.
- **Analytics** — `AnalyticsService` with `business_summary` (revenue, costs, margin, items sold), `profitability_report` (net profit per product/category/source), `inventory_report` (stock value, aging analysis), `period_comparison` (side-by-side metrics), `sourcing_analysis` (ROI per channel). Telegram `/rapport` command and weekly comparison scheduled job (Sundays 18:00).
- **Tradera write operations** — `TraderaClient.create_listing()` via RestrictedService SOAP (supports structured `ShippingOptions` or flat `ShippingCost`), `upload_images()`, `get_categories()`, `get_shipping_options()`, `get_shipping_types()`. `ListingService.publish_listing()` orchestrates the full flow: validates approved listing, extracts shipping from details, optimizes/uploads images, creates Tradera listing, updates DB status to active. Agent tool integration with `publish_listing`, `get_categories`, `get_shipping_options`, `get_shipping_types`, and `get_tradera_item` tools.
- **Tradera authorization CLI** — `storebot-authorize-tradera` command for obtaining user tokens via consent flow. `TraderaClient.fetch_token()` calls `PublicService.FetchToken`. Saves credentials to `.env`.
- **PostNord shipping labels** — `PostNordClient` REST client: `create_shipment()`, `get_label()`, `save_label()`. `Address` dataclass for sender/recipient, `parse_buyer_address()` for parsing Swedish addresses. Sandbox/production URL switching. Integrated into `OrderService.create_shipping_label()` with validation (weight, address), PDF label storage, tracking number persistence, and `AgentAction` audit trail.
- **Resilience & observability** — Retry decorator with exponential backoff on transient errors (Tradera SOAP, Blocket REST, PostNord REST), structured JSON logging (`LOG_JSON` toggle), startup credential validation, admin alerts on scheduled job failures. SQLite WAL mode + busy timeout. Systemd restart limits, backup integrity checks with gzip compression.
- **Tests** — 592 tests across 18 modules covering db, tradera, blocket, pricing, listing, image, order, accounting, conversation, scout, marketing, analytics, postnord, CLI, retry, logging, handlers, and log_viewer.

### Not started

- MCP server wrappers for tool modules
- sqlite-vec embeddings for semantic product search
- Social media cross-posting
- Customer message handling (requires email/IMAP — Tradera API has no messaging support)
- Crop management, custom webshop, wishlist matching

## Build Phases

1. **Phase 1 (MVP):** SQLite schema + SQLAlchemy ORM, Tradera/Blocket search tools, Pricing Agent, Listing Agent — **DONE**
2. **Phase 2:** Telegram bot, Order Agent, local voucher/PDF export — **DONE**
3. **Phase 3:** Scout Agent (scheduled) — **DONE**, Marketing Agent — **DONE**, Analytics — **DONE**, MCP server wrappers, social media cross-posting
4. **Phase 4:** Crop management, custom webshop, wishlist matching

## Development Setup

```bash
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env  # fill in API keys
```

## Code Review Style

When reviewing PRs, provide detailed and thorough reviews:

- Explain **why** each finding matters, not just what the issue is
- Suggest concrete alternatives or fixes with code examples when applicable
- Call out positive patterns worth keeping, not only problems
- Consider architectural impact — does the change fit the project's design principles?
- Flag potential issues with SQLite concurrency, SQLAlchemy session lifecycle, and async Telegram handler patterns
- Check that new database changes have corresponding Alembic migrations
- Verify audit trail coverage — agent actions should be logged to `agent_actions`
- Ensure Swedish business rules (VAT, vouchers) are respected in financial code paths

## Pre-Push Checklist

Before pushing to GitHub, always run and verify:

1. `ruff check src/ tests/` — all lint checks must pass
2. `ruff format --check src/ tests/` — all files must be correctly formatted
3. `pytest` — all unit tests must pass

Do NOT push if any of these fail. Fix issues first.

## Commands

- **Run bot:** `storebot` (or `python -m storebot.bot.handlers`)
- **Authorize Tradera:** `storebot-authorize-tradera` (interactive token consent flow)
- **Audit log viewer:** `storebot-logs` (Textual TUI for reviewing agent_actions)
- **Run tests:** `pytest`
- **Run single test:** `pytest tests/test_db.py::test_name`
- **Lint:** `ruff check src/ tests/`
- **Format:** `ruff format src/ tests/`
- **Init database:** `python -c "from storebot.db import init_db; init_db()"`
- **Run migrations:** `alembic upgrade head`
- **Create migration:** `alembic revision --autogenerate -m "description"`
- **Stamp existing DB:** `alembic stamp head` (mark existing schema as current, no changes applied)
