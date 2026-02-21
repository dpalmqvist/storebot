Completed a thorough architecture and code quality review, plus tests/CI/usability assessment. Key findings and recommendations are consolidated below with file references.

Architecture & design
- Cohesive domain-oriented structure: core orchestration in [`src/storebot/agent.py`](../src/storebot/agent.py) and Telegram entrypoint in [`src/storebot/bot/handlers.py`](../src/storebot/bot/handlers.py), with domain services under [`src/storebot/tools/`](../src/storebot/tools/). Human-in-the-loop listing approvals are encapsulated in [`src/storebot/tools/listing.py`](../src/storebot/tools/listing.py).
- Strengths: modular service layout, SQLite + Alembic for low-ops deployment, operational scripts documented in [`docs/maintenance.md`](maintenance.md).
- Risks: synchronous agent flow can block Telegram handlers, SQLite contention under scheduled jobs, external API fragility, and PII retention policy gaps (see [`src/storebot/agent.py`](../src/storebot/agent.py), [`src/storebot/db.py`](../src/storebot/db.py), [`src/storebot/bot/handlers.py`](../src/storebot/bot/handlers.py)).

Code quality (maintainability, robustness, usability)
- Tool wiring duplication and monolithic schema list in [`src/storebot/agent.py`](../src/storebot/agent.py) increase drift risk; consolidate into a single registry.
- Error handling gaps: unguarded Claude API calls in [`src/storebot/agent.py`](../src/storebot/agent.py); assumptions about external API fields; image file handling without context managers in [`src/storebot/tools/image.py`](../src/storebot/tools/image.py); configuration casting risks in [`src/storebot/tools/tradera.py`](../src/storebot/tools/tradera.py).
- Data integrity: voucher numbers are derived from count (race condition risk) in [`src/storebot/tools/accounting.py`](../src/storebot/tools/accounting.py); marketing report N+1 querying in [`src/storebot/tools/marketing.py`](../src/storebot/tools/marketing.py); unmatched orders are dropped (manual reconciliation needed) in [`src/storebot/tools/order.py`](../src/storebot/tools/order.py).

Tests, CI, and usability
- CI triggers only on PRs to main; no push builds. `claude-review` fails on missing secrets; CI only on Python 3.13 despite requiring 3.11+ (see [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).
- Tests have potential flakiness: time-based assertions in [`tests/test_marketing.py`](../tests/test_marketing.py); filesystem writes to `data/photos` in [`tests/test_conversation.py`](../tests/test_conversation.py); compression-size ordering in [`tests/test_image.py`](../tests/test_image.py). Coverage gaps in handler flows and schema coverage in [`tests/test_handlers.py`](../tests/test_handlers.py) and [`tests/test_db.py`](../tests/test_db.py).

Top recommendations (prioritized)
1) Consolidate tool metadata/dispatch into a single registry to reduce duplication and drift (see [`src/storebot/agent.py`](../src/storebot/agent.py)).
2) Add robust error handling around external IO: Claude calls, API responses, and image file handling (see [`src/storebot/agent.py`](../src/storebot/agent.py), [`src/storebot/tools/image.py`](../src/storebot/tools/image.py)).
3) Strengthen data integrity: replace voucher number via count with a DB-safe sequence, and persist unmatched orders for manual reconciliation (see [`src/storebot/tools/accounting.py`](../src/storebot/tools/accounting.py), [`src/storebot/tools/order.py`](../src/storebot/tools/order.py)).
4) Improve CI realism and stability: add Python version matrix, guard `claude-review` on secret presence, consider coverage reporting (see [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).
5) Align documentation and setup: reconcile install instructions with CI lockfile flow (see [`docs/installation.md`](installation.md)).
6) Reduce flakiness in tests by controlling time and filesystem paths and avoiding compression-size ordering assumptions (see [`tests/test_marketing.py`](../tests/test_marketing.py), [`tests/test_conversation.py`](../tests/test_conversation.py), [`tests/test_image.py`](../tests/test_image.py)).
7) Document operational guardrails: data retention/PII policy, API token renewal cadence, and scaling limits of SQLite (see [`docs/maintenance.md`](maintenance.md), [`src/storebot/db.py`](../src/storebot/db.py)).

Overall assessment
- The repository is architecturally cohesive and well-suited to a single-operator deployment. The primary improvements are around operational resilience (external API failures, sync calls), data integrity under growth, and test/CI rigor. Addressing the recommendations above would materially improve code quality and usability without changing the core design.
