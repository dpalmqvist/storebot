Completed a thorough architecture and code quality review, plus tests/CI/usability assessment. Key findings and recommendations are consolidated below with file references.

Architecture & design
- Cohesive domain-oriented structure: core orchestration in [`src/storebot/agent.py`](src/storebot/agent.py:28) and Telegram entrypoint in [`src/storebot/bot/handlers.py`](src/storebot/bot/handlers.py:269), with domain services under [`src/storebot/tools/`](src/storebot/tools/__init__.py:1). Human-in-the-loop listing approvals are encapsulated in [`src/storebot/tools/listing.py`](src/storebot/tools/listing.py:216).
- Strengths: modular service layout, SQLite + Alembic for low-ops deployment, operational scripts documented in [`README.md`](README.md:298).
- Risks: synchronous agent flow can block Telegram handlers, SQLite contention under scheduled jobs, external API fragility, and PII retention policy gaps (see [`src/storebot/agent.py`](src/storebot/agent.py:712), [`src/storebot/db.py`](src/storebot/db.py:97), [`src/storebot/bot/handlers.py`](src/storebot/bot/handlers.py:296)).

Code quality (maintainability, robustness, usability)
- Tool wiring duplication and monolithic schema list in [`src/storebot/agent.py`](src/storebot/agent.py:28) and dispatch logic in [`src/storebot/agent.py`](src/storebot/agent.py:802) increase drift risk; consolidate into a single registry.
- Error handling gaps: unguarded Claude API calls in [`src/storebot/agent.py`](src/storebot/agent.py:735); assumptions about external API fields in [`src/storebot/agent.py`](src/storebot/agent.py:850); image file handling without context managers in [`src/storebot/tools/image.py`](src/storebot/tools/image.py:21); configuration casting risks in [`src/storebot/tools/tradera.py`](src/storebot/tools/tradera.py:86).
- Data integrity: voucher numbers are derived from count (race condition risk) in [`src/storebot/tools/accounting.py`](src/storebot/tools/accounting.py:33); marketing report N+1 querying in [`src/storebot/tools/marketing.py`](src/storebot/tools/marketing.py:160); unmatched orders are dropped (manual reconciliation needed) in [`src/storebot/tools/order.py`](src/storebot/tools/order.py:30).

Tests, CI, and usability
- CI triggers only on PRs to main; no push builds. `claude-review` fails on missing secrets; CI only on Python 3.13 despite README 3.10+ (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml:3), [`.github/workflows/ci.yml`](.github/workflows/ci.yml:41), [`README.md`](README.md:27)).
- README inconsistencies: PostNord env var naming mismatch between [`README.md`](README.md:78) and [`README.md`](README.md:173); install flow differs from CI (`uv pip install -e` vs `uv sync --locked`).
- Tests have potential flakiness: time-based assertions in [`tests/test_marketing.py`](tests/test_marketing.py:224); filesystem writes to `data/photos` in [`tests/test_conversation.py`](tests/test_conversation.py:105); compression-size ordering in [`tests/test_image.py`](tests/test_image.py:88). Coverage gaps in handler flows and schema coverage in [`tests/test_handlers.py`](tests/test_handlers.py:10) and [`tests/test_db.py`](tests/test_db.py:6).

Top recommendations (prioritized)
1) Consolidate tool metadata/dispatch into a single registry to reduce duplication and drift (see [`src/storebot/agent.py`](src/storebot/agent.py:28), [`src/storebot/agent.py`](src/storebot/agent.py:802)).
2) Add robust error handling around external IO: Claude calls, API responses, and image file handling (see [`src/storebot/agent.py`](src/storebot/agent.py:735), [`src/storebot/tools/image.py`](src/storebot/tools/image.py:21)).
3) Strengthen data integrity: replace voucher number via count with a DB-safe sequence, and persist unmatched orders for manual reconciliation (see [`src/storebot/tools/accounting.py`](src/storebot/tools/accounting.py:33), [`src/storebot/tools/order.py`](src/storebot/tools/order.py:30)).
4) Improve CI realism and stability: add Python version matrix, guard `claude-review` on secret presence, consider coverage reporting (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml:3)).
5) Align documentation and setup: reconcile PostNord env var names and align README install instructions with CI lockfile flow (see [`README.md`](README.md:78), [`README.md`](README.md:173)).
6) Reduce flakiness in tests by controlling time and filesystem paths and avoiding compression-size ordering assumptions (see [`tests/test_marketing.py`](tests/test_marketing.py:224), [`tests/test_conversation.py`](tests/test_conversation.py:105), [`tests/test_image.py`](tests/test_image.py:88)).
7) Document operational guardrails: data retention/PII policy, API token renewal cadence, and scaling limits of SQLite (see [`README.md`](README.md:5), [`src/storebot/db.py`](src/storebot/db.py:236)).

Overall assessment
- The repository is architecturally cohesive and well-suited to a single-operator deployment. The primary improvements are around operational resilience (external API failures, sync calls), data integrity under growth, and test/CI rigor. Addressing the recommendations above would materially improve code quality and usability without changing the core design.