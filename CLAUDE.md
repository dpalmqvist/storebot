# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Storebot is an AI-powered agent system for managing a Swedish country shop ("Lantshop") that sells renovated furniture, décor, curiosities, antiques, and crops. The owner interacts with the system primarily through a Telegram bot. Planned launch: November 2026.

## Tech Stack

- **Language:** Python 3.10+
- **LLM:** Claude API (direct integration, no LangChain)
- **Database:** SQLite + sqlite-vec (single-user, simple deployment)
- **Accounting:** Fortnox REST API (financial source of truth — bokföring, moms, årsbokslut)
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
    ├── tools/fortnox.py     (REST, OAuth2)
    ├── tools/postnord.py    (shipping labels)
    └── tools/image.py       (Pillow: resize, optimize)
    ↓
SQLite + sqlite-vec (operational: inventory, listings, orders, agent state, embeddings)
Fortnox (financial: vouchers, invoices, VAT, BAS-kontoplan)
```

### Sub-Agents

- **Listing Agent** — Generates Swedish titles/descriptions, selects Tradera category, sets pricing, uploads images
- **Order Agent** — Monitors sales, updates inventory, generates shipping labels, creates Fortnox vouchers
- **Pricing Agent** — Searches Tradera + Blocket for comparables, suggests price ranges
- **Scout Agent** — Scheduled searches for sourcing opportunities, sends daily digests
- **Marketing Agent** — Tracks listing performance, suggests strategies

### Key Design Principles

- **Human-in-the-loop by default:** All listings start as drafts requiring approval. Auto-approve can be enabled per category over time.
- **No LangChain:** Use Claude API directly with tool definitions. Simpler debugging, less framework overhead.
- **Plain tools first, MCP later:** Build tool modules as clean Python classes with self-contained interfaces, wrappable as MCP servers when needed.
- **Fortnox = financial truth, SQLite = operational truth:** Never duplicate bookkeeping logic locally. Cross-reference via `fortnox_voucher_id`.
- **`agent_actions` table:** Full audit trail of every agent decision for safety and review.
- **JSON for flexibility:** Semi-structured data in `details` columns to avoid premature schema migrations.

## Database Schema (Core Tables)

`products`, `product_images`, `platform_listings`, `orders`, `agent_actions`, `notifications`

SQLAlchemy 2.0 declarative models in `src/storebot/db.py`. Using `create_all()` during early development (no Alembic yet).

## External API Notes

- **Tradera:** SOAP/XML API, rate limit 100 calls/24h (extendable). Sandbox via `sandbox=1`. Register at Tradera Developer Program.
- **Blocket:** Unofficial, read-only. Bearer token extracted from browser session (expires, needs manual renewal).
- **Fortnox:** REST API, OAuth2. Requires developer/partner account. Key endpoints: `/3/vouchers`, `/3/invoices`, `/3/supplierinvoices`, `/3/inbox` (receipt upload).
- **PostNord:** Shipping label generation API.

## Swedish Business Context

- BAS-kontoplan (standard chart of accounts) managed in Fortnox
- Moms (VAT): 25% on goods. Registration required if turnover > 80,000 kr/year
- Every transaction requires a verifikation (voucher) — the agent must ensure none are missed
- SIE file export for Skatteverket compliance handled by Fortnox

## Implementation Status

### Done

- **Database layer** — SQLAlchemy 2.0 models for all core tables (`products`, `product_images`, `platform_listings`, `orders`, `agent_actions`, `notifications`). Foreign keys, JSON columns, `create_all()` init.
- **Tradera search** — SOAP via zeep, `SearchAdvanced` with category/price filters, result parsing (bids, buy-now, images). `create_listing`, `get_orders`, `get_item` are stubbed.
- **Blocket search** — Unofficial REST API, read-only price research. `get_ad` is stubbed.
- **Pricing Agent** — `PricingService.price_check()` searches both Tradera + Blocket, computes stats (min/max/mean/median), suggests price range via quartiles, logs `AgentAction`.
- **Listing Agent** — `ListingService` with full draft workflow: `create_draft`, `list_drafts`, `get_draft`, `update_draft`, `approve_draft`, `reject_draft`, `search_products`. All with validation and `AgentAction` audit logging.
- **Product management** — `create_product` (with all optional fields: condition, materials, era, dimensions, source, acquisition_cost) and `save_product_image` (with is_primary logic).
- **Image processing** — `resize_for_listing` (1200px), `resize_for_analysis` (800px), `optimize_for_upload` (JPEG compress), `encode_image_base64`. All handle EXIF rotation and RGBA conversion.
- **Agent loop** — `agent.py` with Claude API tool loop, 14 tool definitions, vision support (base64 image content blocks), Swedish system prompt with image workflow guidance.
- **Telegram bot** — `handlers.py` with `/start`, `/help`, text message handling, and photo handling (download, resize, forward to agent with vision).
- **Config** — Pydantic Settings from `.env`, all service credentials.
- **Deployment** — systemd service file, SQLite backup script with cron rotation.
- **Tests** — 113 tests covering db, tradera, blocket, pricing, listing, and image modules.

### Stubbed (not yet implemented)

- **Fortnox** — `FortnoxClient` class exists but all methods (`create_voucher`, `get_vouchers`, `upload_receipt`, `create_customer`) raise `NotImplementedError`.
- **PostNord** — `PostNordClient` class exists but `create_shipment` and `get_label` raise `NotImplementedError`.
- **Tradera write operations** — `create_listing`, `get_orders`, `get_item` are stubbed.
- **Blocket ad detail** — `get_ad` is stubbed.

### Not started

- Order Agent (monitor sales, update inventory, shipping labels, Fortnox vouchers)
- Scout Agent (scheduled sourcing searches, daily digests)
- Marketing Agent (listing performance tracking, strategy suggestions)
- MCP server wrappers for tool modules
- Conversation history persistence (currently stateless per message)
- Alembic migrations (using `create_all()` during development)
- sqlite-vec embeddings for semantic product search
- Social media cross-posting
- Crop management, custom webshop, wishlist matching

## Build Phases

1. **Phase 1 (MVP):** SQLite schema + SQLAlchemy ORM, Tradera/Blocket search tools, Pricing Agent, Listing Agent — **DONE**
2. **Phase 2:** Telegram bot, Order Agent, Fortnox voucher automation, receipt capture — **IN PROGRESS** (bot done, Order Agent + Fortnox remaining)
3. **Phase 3:** Scout Agent (scheduled), Marketing Agent, MCP server wrappers, social media cross-posting
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
