# CHANGELOG


## v0.13.1 (2026-03-03)

### Bug Fixes

- **ci**: Allow claude[bot] in Claude Code workflow
  ([`2858047`](https://github.com/dpalmqvist/storebot/commit/285804755e50ef48e365251b227779a77a76736b))

The codebase review creates issues mentioning @claude, which triggers the Claude Code workflow.
  Without allowed_bots, the action rejects bot-initiated events.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.13.0 (2026-03-03)

### Documentation

- Update CI/CD section and fix test module counts
  ([#124](https://github.com/dpalmqvist/storebot/pull/124),
  [`ffc3a28`](https://github.com/dpalmqvist/storebot/commit/ffc3a2892afdab009946f2cf6dfdff0b8d5562f5))

- Document release.yml workflow and SEMANTIC_RELEASE_TOKEN requirement - Add repository secrets
  reference table - Fix test module count (18 → 30 in structure, 26 → 30 in table) - Add 4 missing
  test modules (agent, dispatch, formatting, mcp_server)

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Add post-release codebase review via Ollama
  ([#125](https://github.com/dpalmqvist/storebot/pull/125),
  [`8507232`](https://github.com/dpalmqvist/storebot/commit/85072324275fd0470f252c4a79fc0a3ac90f20de))

* feat: add post-release codebase review via Ollama

Add a new GitHub Actions workflow triggered by version tag pushes (v*) that reviews the entire
  src/storebot/ codebase using Ollama (Qwen 3.5 9B). The script groups files into 7 module chunks,
  reviews each chunk, ranks findings by severity, and creates up to 5 GitHub issues with @claude
  mentions to trigger automated fixes.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* fix: address review feedback on codebase review script

- Replace str.format() with str.replace() + concatenation to avoid KeyError from curly braces in
  Python source code and JSON output - Validate that parsed JSON items are dicts before downstream
  use - Add chunk size warning when code exceeds 200K chars (context window) - Bump dedup issue
  search limit from 100 to 500 - Log triggering tag name for easier CI log correlation

* fix: address second round of review feedback

- Truncate oversized chunks instead of just warning (prevents context window overflow) - Guard issue
  title length to 80 chars - Move @claude trigger before LLM-generated content in issue body - Add
  timeout-minutes: 90 to workflow job - Log uncovered files not in any MODULE_CHUNKS group

* fix: address third round of review feedback

- Fix title truncation mismatch between main() and create_issue() that broke duplicate detection for
  long titles - Wrap create_issue() calls in try/except so one failure doesn't abort remaining
  issues - Truncate oversized chunks on line boundary instead of mid-character - Filter structurally
  invalid findings (missing required fields or invalid severity) before issue creation - Map
  GITHUB_REF_NAME explicitly in workflow env block

* fix: capture original length before truncation in warning message

The truncation warning was printing the post-truncation length for both values since combined was
  reassigned before the print statement.

* fix: require human triage before triggering @claude on AI review issues

Remove @claude auto-trigger from issue body to break the unlimited autonomous chain (Qwen -> issue
  -> Claude -> PR). Issues now include a note to comment @claude after reviewing the finding. This
  preserves the human-in-the-loop principle while keeping the review automation.

Also fix rank_findings() to use sorted() instead of in-place .sort() to avoid mutating the input
  list.

* fix: avoid literal @claude in issue body to prevent auto-trigger

The claude.yml workflow uses contains(body, '@claude') substring match, so even the instruction text
  would trigger it. Use 'tag Claude' instead.

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>


## v0.12.0 (2026-03-02)

### Bug Fixes

- Use PAT for semantic-release to bypass branch protection
  ([#123](https://github.com/dpalmqvist/storebot/pull/123),
  [`10d15c5`](https://github.com/dpalmqvist/storebot/commit/10d15c591571ef99563b9d2013f58f1274912a03))

The release workflow fails because GITHUB_TOKEN cannot push directly to main when branch protection
  requires pull requests. Switch to a fine-grained PAT (SEMANTIC_RELEASE_TOKEN) for both git push
  and GitHub release creation.

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

### Chores

- Remove sqlite-vec dependency and all references
  ([#120](https://github.com/dpalmqvist/storebot/pull/120),
  [`5445d59`](https://github.com/dpalmqvist/storebot/commit/5445d59ff51490a2b7353dd52258a5d6cd87fa08))

sqlite-vec and embeddings will never be implemented. Remove the dependency, the _load_sqlite_vec
  connection hook, its test, and all references from CLAUDE.md, README.md and pyproject.toml.

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

- Replace OpenAI code review with Ollama (qwen3.5:9b)
  ([#122](https://github.com/dpalmqvist/storebot/pull/122),
  [`13f1b83`](https://github.com/dpalmqvist/storebot/commit/13f1b837967ce29331bda05488e649e8fdbb235c))

* chore: replace OpenAI code review with Ollama (qwen3.5:9b)

Replace the OpenAI GPT-5.2 Codex CI review job with local Ollama inference using qwen3.5:9b on the
  self-hosted runner. Removes the OPENAI_API_KEY dependency and eliminates external API calls for
  code review.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* fix: handle empty OLLAMA_BASE_URL/OLLAMA_MODEL env vars

GitHub Actions sets vars to empty string (not unset) when repository variables don't exist, so
  `os.environ.get(key, default)` returns "" instead of the default. Use `or` to fall back on empty
  strings too.

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Add expired listing detection and notification
  ([#121](https://github.com/dpalmqvist/storebot/pull/121),
  [`10cab73`](https://github.com/dpalmqvist/storebot/commit/10cab732672c5c65932c06cfe7c69a01dc993113))

* feat: add expired listing detection and notification

Active listings past their ends_at timestamp are now automatically transitioned to "ended" status,
  with product status reset to "draft" when no other active listings remain. A scheduled job checks
  every 60 minutes (configurable) and sends Swedish Telegram notifications.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* fix: address code review feedback on expired listing detection

- Fix stale product_status in result dict when multiple listings for the same product expire in one
  batch (two-pass: mutate first, then snapshot final states) - Remove hardcoded "varje timme" from
  tool description (interval is configurable) - Strengthen test_multiple_expired_all_transitioned to
  assert per-item product_status values

* fix: handle null listing_title in notification and add autoflush comment

- Add fallback for nullable listing_title in expired listings notification to avoid rendering "None"
  literally - Add comment explaining autoflush dependency for sibling count queries

* refactor: hoist repeated datetime imports to module level in test_listing

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

- Add MCP server exposing all storebot tools
  ([#119](https://github.com/dpalmqvist/storebot/pull/119),
  [`c51e35d`](https://github.com/dpalmqvist/storebot/commit/c51e35d72beb368cc20e724f2454cd50530854e5))

* build: add mcp SDK dependency

* refactor: extract shared dispatch module from agent.py

* feat: add MCP server exposing all storebot tools

* feat: add storebot-mcp CLI entry point

* test: improve mcp_server coverage for main() stdio and http paths

* docs: add MCP server to implementation status

* fix: address code review findings in MCP server

- Add get_categories to DISPATCH so MCP clients can call it - Add uvicorn as optional [http]
  dependency with helpful ImportError - Add structured logging extra={"tool_name"} to dispatch log
  calls - Change HTTP default host from 0.0.0.0 to 127.0.0.1, add --host arg - Filter request_tools
  from MCP tool list (agent-internal only)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* build: update uv.lock for mcp and http dependencies

* fix: address automated review findings in MCP server

* fix: use get_running_loop, remove redundant http extra, warn on non-localhost

- asyncio.get_event_loop() -> get_running_loop() (deprecated in async context) - Remove [http]
  optional extra — mcp already depends on uvicorn - Add security warning when HTTP transport binds
  to non-localhost address

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

### Testing

- Achieve 100% line coverage and 99% branch coverage
  ([#118](https://github.com/dpalmqvist/storebot/pull/118),
  [`60a5fc6`](https://github.com/dpalmqvist/storebot/commit/60a5fc6b23db9bdcfcdfdad5fc26228a41583793))

* test: achieve 100% test coverage with simplified test helpers

Add pytest-cov tooling, ~180 new tests across 21 files covering all previously-missed branches
  (agent dispatch, TUI screens, handler access denial, CLI edge cases, etc.). Extract shared helpers
  (_make_api_response, _make_tool_block, _make_category) to eliminate mock boilerplate in
  test_agent.py, parametrize 9 identical access-denied tests in test_handlers.py, and move imports
  to module level in test_log_viewer.py.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* fix: update uv.lock for pytest-cov dependency

* style: format test_agent.py

* fix: address review — enable branch coverage, rename misleading test

- Enable `branch = true` in coverage config for stronger guarantees - Set fail_under=99 (100% line,
  99% branch — 49 partial branches remain) - Rename TestAgingBucketFallback →
  TestAgingBucketEdgeCases (the test exercises the 30+ bucket inside the loop, not the unreachable
  fallback)

* fix: address review — remove dead code, add try/finally guards

- Remove unreachable `if not old: return` guard in compact_history (line 749 already returns when
  keep >= len(messages), guaranteeing old is non-empty — eliminates the pragma: no cover) - Add
  try/finally to _rate_limit_buckets cleanup in rate-limit tests and _DISPATCH mutation in
  TestExecuteToolServiceNotInDb to prevent state leaks on assertion failure - Document why
  fail_under=99 (branch coverage partial branches)

* fix: improve test assertions per review feedback

- TestMain: assert on job function names instead of fragile call count -
  test_load_sqlite_vec_failure: verify warning is logged via caplog

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>


## v0.11.0 (2026-02-22)

### Bug Fixes

- Address PR review findings for Telegram HTML formatting
  ([`f6c3ac9`](https://github.com/dpalmqvist/storebot/commit/f6c3ac9d331941d1a162c553ca834606507c773e))

- Log BadRequest fallback in _reply/_send so formatting regressions are visible - Escape quotes in
  link URLs to prevent broken href attributes - Reserve space for closing tags at split boundaries
  to stay within max_length - Use regex for _close_tags instead of fragile string manipulation - Add
  comment explaining &gt; usage in _BLOCKQUOTE_RE - Add tests for blockquote with special chars,
  link URL quoting, tag overhead

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Cast zeep enum types to str in Tradera SOAP response parsers
  ([#111](https://github.com/dpalmqvist/storebot/pull/111),
  [`2a0e064`](https://github.com/dpalmqvist/storebot/commit/2a0e064df77dc6f48050239ac6a4585d0103c31e))

Zeep deserializes SOAP enum fields (ItemStatus, ItemType) as custom objects rather than plain
  strings. When agent.py serializes tool results via json.dumps, _json_default only handles Decimal
  — causing a TypeError crash in production on get_tradera_item calls.

Cast Status and ItemType to str() following the existing end_date pattern. Add regression tests with
  non-serializable mock enum objects.

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

- Handle parentheses in Markdown link URLs
  ([`afa7a25`](https://github.com/dpalmqvist/storebot/commit/afa7a2536d3add64728cf843935e4ab8a0cc569b))

_LINK_RE used [^)]+ which stopped at the first ), truncating Wikipedia-style URLs like
  https://en.wikipedia.org/wiki/Foo_(bar). New pattern allows one level of balanced parentheses
  inside URLs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Harden italic regex and link URL scheme validation
  ([`7ca94b1`](https://github.com/dpalmqvist/storebot/commit/7ca94b1f0e2e25c0de80622750bc898aa0198cf1))

- Fix _ITALIC_STAR_RE to require no whitespace after opening * — prevents false italicization of *
  bullet lists (e.g. "* bold*" was italicised) - Validate link URL scheme (http/https only) to
  prevent javascript: URIs - Clarify html_escape docstring re: quote=False - Add tests: star bullet
  lists, empty input, nested bold+italic, non-http links

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Log sqlite_vec load status instead of silently swallowing exceptions
  ([#110](https://github.com/dpalmqvist/storebot/pull/110),
  [`982c102`](https://github.com/dpalmqvist/storebot/commit/982c102910579edade44dfbb1f984902112114de))

* fix: log sqlite_vec load status instead of silently swallowing exceptions

Add module-level logger to db.py and update _load_sqlite_vec to emit DEBUG messages on both success
  and failure, replacing a bare `pass` that made extension load failures completely invisible.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* refactor: ensure enable_load_extension disabled via finally block

If sqlite_vec.load() fails, the previous code left extension loading enabled on the connection. Use
  a finally block (guarded by `enabled` flag) to guarantee disable runs only when
  enable_load_extension(True) succeeded.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Prevent infinite recursion in split_html_message at digit boundary
  ([`8299b82`](https://github.com/dpalmqvist/storebot/commit/8299b82910f133906899ac328d43a79295acf9d7))

Replace recursive call (which passed same max_length causing infinite loop) with two-pass approach
  matching the original _split_message pattern. Add regression test at the 9-to-10 chunk boundary
  (~35950 chars). Fix CLAUDE.md test count (841, not 842).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Tag matching, fallback tag stripping, and split_limit guard
  ([`2a2e755`](https://github.com/dpalmqvist/storebot/commit/2a2e755d7a73723e6bd3361ac92c6d55dffe65d4))

- Fix _get_open_tags startswith mismatch: "<blockquote>".startswith("<b") was True, causing
  incorrect tag-stack pops. Use exact match + space check. - Strip HTML tags on BadRequest fallback
  so users don't see raw <b> etc. - Guard split_limit against negative values with max(1, ...) - Add
  strip_html_tags helper, tests for tag stripping

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Use uv run for semantic-release in CI workflow
  ([#113](https://github.com/dpalmqvist/storebot/pull/113),
  [`0cf6f86`](https://github.com/dpalmqvist/storebot/commit/0cf6f86181a070229c6318bb31906411791feaf9))

The release workflow installed python-semantic-release into the uv venv but invoked the binary
  without `uv run`, causing "command not found".

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

### Chores

- Bump version to 0.11.0
  ([`71e8e8b`](https://github.com/dpalmqvist/storebot/commit/71e8e8be75920eb620c50e7febb878c7a1a8f74a))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Documentation

- Emphasize Tradera as the selling platform and API access requirement
  ([`a884f14`](https://github.com/dpalmqvist/storebot/commit/a884f14376d69acd082163e7173dfe9dd0e403a6))

Clarify that Storebot sells exclusively on Tradera, with Blocket used only for market research. Add
  a Prerequisites section to README with Tradera API registration details. Simplify CLAUDE.md
  roadmap section.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Refresh README, add Apache 2.0 license, remove code-review.md
  ([`f38c426`](https://github.com/dpalmqvist/storebot/commit/f38c4263dfe0d154b9b3e2e25874c81aee82fd07))

- Rewrite README with capabilities table, use cases, tech stack, design principles, and roadmap
  section - Remove country shop / lanthandel references for broader applicability - Replace
  phase-based status with roadmap of upcoming features - Add Apache 2.0 LICENSE file - Add license
  field to pyproject.toml and update description - Remove obsolete docs/code-review.md - Fix test
  count in CLAUDE.md (853 → 857)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Add automatic semantic versioning ([#109](https://github.com/dpalmqvist/storebot/pull/109),
  [`96ede74`](https://github.com/dpalmqvist/storebot/commit/96ede74433132a49ec1fb97dd7e5041d411aeaf9))

* feat: add automatic semantic versioning with conventional commits

- Replace hardcoded version in pyproject.toml with dynamic version from src/storebot/__init__.py via
  hatch - Add python-semantic-release config for automatic version bumps - Add GitHub Actions
  release workflow that runs on push to main - Add pre-commit hook for conventional commit message
  validation - Show version in /new command reply (Storebot v{version}) - Add test for version
  display in new_conversation handler - Document commit message convention in CLAUDE.md

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* fix: address PR review feedback on semantic versioning

- Pin python-semantic-release to 9.x to prevent breaking changes - Add lint + test gate before
  release step in workflow - Add NOTE about branch protection and PAT requirement - Document
  `pre-commit install` in Development Setup - Assert Swedish text preserved in new_conversation test

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>

- Convert Telegram messages to HTML with Markdown rendering
  ([`cc604bb`](https://github.com/dpalmqvist/storebot/commit/cc604bb788690e050d19d3f51a3dac1abe25279c))

Agent responses are now converted from Markdown to Telegram HTML (bold, italic, code, links,
  headers, blockquotes) via a new formatting module. Service reports and alerts are HTML-escaped for
  safety. Both _reply and _send fall back to plain text on BadRequest.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Performance Improvements

- Fix N+1 query patterns in marketing.py ([#114](https://github.com/dpalmqvist/storebot/pull/114),
  [`e29a900`](https://github.com/dpalmqvist/storebot/commit/e29a9002b45307edefec336bc909e1937047ea8f))

* perf: fix N+1 query patterns in marketing.py

Replace per-listing database queries with bulk operations in get_performance_report,
  get_recommendations, and get_listing_dashboard:

- Eager-load product relationships via selectinload - Bulk-load orders for sold listings with single
  IN query - Single aggregate query for bid-check instead of per-listing snapshot queries -
  Bulk-load latest snapshots via subquery for recommendations - Eager-load snapshots relationship
  for listing dashboard

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

* fix: address PR review findings for N+1 query fix

- Replace max(id) with ROW_NUMBER() OVER (ORDER BY snapshot_at DESC) in snapshot bulk-loading —
  fixes incorrect "latest" when IDs are non-chronological - Generalize _bulk_latest_snapshots into
  _bulk_recent_snapshots(limit) so dashboard uses limit=3 instead of selectinload(all snapshots),
  fixing the memory regression on long-running shops - Add ORDER BY to bulk order query for
  deterministic selection - Deduplicate sold_product_ids via set() - Eager-load product in
  single-listing get_recommendations path - Add test for dashboard with >3 snapshots confirming old
  ones are excluded from delta calculations

* fix: use setdefault for first-order-wins semantics in order_by_product

The dict comprehension kept the last order per product (highest id), reversing the original .first()
  behavior. Use setdefault to preserve the first order, matching original semantics.

Also add SQLite >= 3.25 version note on _bulk_recent_snapshots.

* fix: add id tiebreaker to ROW_NUMBER() window function

Ensures deterministic snapshot selection when two snapshots share the same snapshot_at timestamp.

---------

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>
