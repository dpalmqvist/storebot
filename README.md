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
                 ├── Analytics            - business reports, profitability
                 ├── Order                - sales, shipping, invoicing
                 ├── PostNord (REST)      - shipping labels
                 └── Image (Pillow)       - resize, optimize, vision
                       |
                 SQLite + sqlite-vec
```

Send a photo of an item in Telegram. The agent describes what it sees, creates a product record, searches Tradera and Blocket for comparable prices, drafts a listing for your approval, and logs everything to the database. All listings start as **drafts** requiring explicit approval before publishing.

## Quick start

```bash
git clone <repo-url> && cd storebot
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env  # fill in API keys
storebot
```

See [Installation & Setup](docs/installation.md) for full configuration and service setup.

## Documentation

| Document | Description |
|----------|-------------|
| [Installation & Setup](docs/installation.md) | Prerequisites, install, configuration, external service setup |
| [Usage Guide](docs/usage.md) | Telegram commands, workflows, agent tools, scheduled jobs |
| [Maintenance & Operations](docs/maintenance.md) | Deployment, systemd, backups, logging, troubleshooting |
| [Development Guide](docs/development.md) | Architecture, project structure, testing, adding features |
| [Code Review](docs/code-review.md) | Architecture and code quality review findings |

## Current Status

Phase 1 (MVP) and Phase 2 are complete. Phase 3 is partially done — Scout Agent, Marketing Agent, and Analytics are implemented. See [CLAUDE.md](CLAUDE.md) for full implementation status and build phases.

**Tech stack:** Python 3.10+, Claude API (direct, no LangChain), SQLite, Telegram, Tradera SOAP, PostNord REST, Pillow, SQLAlchemy 2.0, Alembic.

## License

Private repository. All rights reserved.
