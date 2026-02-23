# Storebot

**Your AI-powered business partner for selling on Tradera.**

Storebot is an autonomous agent system that handles the entire lifecycle of selling goods on [Tradera](https://www.tradera.com) — from sourcing and pricing to listing, order management, shipping, and bookkeeping. It also searches Blocket for market research and sourcing leads, but all selling happens through Tradera. You interact with it through Telegram, and it takes care of the rest.

Whether you sell vintage furniture, electronics, clothing, collectibles, or anything in between — Storebot manages the tedious parts so you can focus on finding great items.

## What It Does

**Snap a photo, get a listing.** Send a picture of an item in Telegram. Storebot describes what it sees, creates a product record, searches Tradera and Blocket for comparable prices, drafts a listing in Swedish, and waits for your approval before publishing. Every decision is logged for full auditability.

### Key Capabilities

| Capability | What happens |
|---|---|
| **Product Listing** | Vision-based item description, Swedish title/description generation, Tradera category selection, image optimization and upload |
| **Pricing Intelligence** | Cross-platform price research on Tradera and Blocket (read-only), statistical analysis (min/max/mean/median), quartile-based price suggestions |
| **Order Management** | Automatic Tradera order polling, inventory updates, PostNord shipping label generation, shipment tracking |
| **Bookkeeping** | Double-entry vouchers following BAS-kontoplan, automatic VAT calculation, PDF export for your accountant |
| **Sourcing (Scout)** | Saved searches with daily digest notifications, deduplication of already-seen items, find deals before anyone else |
| **Marketing** | Listing performance tracking (views, watchers, bids), trend analysis, actionable recommendations (reprice, relist, improve) |
| **Analytics** | Revenue and margin reports, profitability per product/category/source, inventory aging, period comparisons, sourcing ROI |

### How It Works

```
You (Telegram)
  │
  ▼
Claude API ─── tool use + vision ─── Agent Loop
  │
  ├── Tradera (SOAP)      search, list, sell, ship, categories
  ├── Blocket (REST)       price research, sourcing (read-only)
  ├── Accounting           vouchers, VAT, PDF export
  ├── Scout                saved searches, daily digests
  ├── Marketing            performance tracking, recommendations
  ├── Analytics            business reports, profitability
  ├── Orders               sales, shipping labels, invoicing
  ├── PostNord (REST)      shipping labels
  └── Image (Pillow)       resize, optimize, vision prep
  │
  ▼
SQLite ── single file, zero maintenance
```

## Use Cases

### Daily Workflow
1. **Morning** — Review the daily listing dashboard and scout digest that arrived automatically
2. **Sourcing** — Spot a deal at a flea market? Snap a photo, ask "what's this worth?", get instant price research
3. **Listing** — "List this oak chair for auction starting at 200 kr" — the agent drafts everything, you approve
4. **Shipping** — An item sold? The agent imports the order, generates a PostNord label, and creates the accounting voucher
5. **Evening** — Ask for a business summary: revenue, margins, what's selling, what isn't

### Telegram Commands

| Command | Purpose |
|---|---|
| `/start` | Welcome message and introduction |
| `/help` | Available commands and capabilities |
| `/new` | Start a fresh conversation |
| `/orders` | Check for new Tradera orders |
| `/scout` | Run saved searches now |
| `/marketing` | Refresh listing performance stats |
| `/rapport` | Generate a business report |

Beyond commands, Storebot understands natural language in Swedish and English. Send text, photos, or voice your requests — the agent figures out which tools to use.

## Prerequisites

- **Tradera API access** — Register at the [Tradera Developer Program](https://api.tradera.com) and contact Tradera (`apiadmin@tradera.com`) to enable API access for your account. This is required for all listing and selling functionality. You will also need to request access to the `RestrictedService` and `OrderService` for full write operations.
- **Claude API key** — For the AI agent ([console.anthropic.com](https://console.anthropic.com))
- **Telegram Bot Token** — Create a bot via [@BotFather](https://t.me/BotFather)
- **PostNord API key** (optional) — For shipping label generation

## Quick Start

```bash
git clone <repo-url> && cd storebot
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env   # fill in API keys
storebot               # start the bot
```

See the [Installation Guide](docs/installation.md) for the full setup walkthrough.

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.13 |
| LLM | Claude API (direct tool use, no framework overhead) |
| Database | SQLite (zero-maintenance, single-file) |
| Chat | Telegram via python-telegram-bot v20+ |
| Marketplace | Tradera (SOAP/zeep) — selling; Blocket (REST) — research only |
| Shipping | PostNord REST API |
| ORM | SQLAlchemy 2.0 + Alembic migrations |
| Accounting | Local double-entry bookkeeping, PDF via ReportLab |
| Deployment | systemd on Raspberry Pi 5 |

## Documentation

| Document | Description |
|---|---|
| [Installation & Setup](docs/installation.md) | Prerequisites, environment variables, external service configuration, systemd setup |
| [Usage Guide](docs/usage.md) | Telegram commands, agent workflows, tool reference, scheduled jobs |
| [Maintenance & Operations](docs/maintenance.md) | Deployment, backups, logging, troubleshooting |
| [Development Guide](docs/development.md) | Architecture deep-dive, project structure, testing patterns, extending the system |

## Project Status

The core system is fully operational: listing, pricing, orders, shipping, accounting, scouting, marketing, and analytics all work end-to-end.

- 57 agent tools across 15 modules
- 857 tests passing
- 14 database tables
- 7 Telegram commands
- Full audit trail via `agent_actions` table

### Roadmap

- **Social media cross-posting** — Publish listings to Instagram, Facebook Marketplace, etc.
- **Customer messaging** — Email/IMAP integration for handling buyer questions
- **Custom webshop** — Standalone storefront beyond marketplace platforms

## Design Principles

- **Human-in-the-loop** — All listings start as drafts. Nothing is published without your approval.
- **Full audit trail** — Every agent decision is logged to the database for review.
- **No framework lock-in** — Direct Claude API integration. No LangChain, no abstractions you can't debug.
- **Single-file database** — SQLite means zero maintenance, easy backups, runs anywhere.
- **Swedish business rules built in** — BAS-kontoplan, moms (VAT) at 25%, proper verifikationer (vouchers).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
