#!/usr/bin/env python3
"""Ollama Qwen 3.5 9B PR code review script for GitHub Actions.

Uses only stdlib — no pip dependencies needed on CI runners.
Fetches PR diff via `gh`, sends to local Ollama for review, posts result as PR comment.
"""

import json
import os
import subprocess
import urllib.request

MAX_DIFF_BYTES = 500_000
TRUNCATE_BYTES = 100_000

SYSTEM_PROMPT = """\
You are an expert code reviewer for **Storebot**, a Python project.

Key context:
- Python 3.11+, SQLAlchemy 2.0 (SQLite), Pydantic Settings
- Claude API agent loop with 44+ tools (no LangChain)
- Telegram bot via python-telegram-bot v20+
- Swedish business rules: BAS-kontoplan, 25% VAT, voucher-based accounting
- External APIs: Tradera (SOAP/zeep), Blocket (unofficial REST), PostNord (REST)
- Deployment: Raspberry Pi 5, systemd, SQLite WAL mode

Review focus:
1. **Bugs & logic errors** — off-by-one, None handling, wrong comparisons
2. **Security** — injection, secret exposure, unsafe deserialization
3. **SQLite/SQLAlchemy** — session lifecycle, concurrency, missing commits/rollbacks
4. **Swedish business rules** — VAT calculation, voucher integrity, BAS accounts
5. **Python best practices** — type hints, datetime.now(UTC) not utcnow(), clean imports
"""

USER_PROMPT_TEMPLATE = """\
Review this pull request diff. For each finding, specify:
- **Severity**: critical / warning / suggestion
- **File** and **line number** (from the diff)
- **What** the issue is and **why** it matters
- **Suggested fix** (brief code snippet if applicable)

Structure your response as:

## Summary
One paragraph overview of the changes and overall assessment.

## Findings
List each finding with severity, file, line, description, and fix.
If no issues found, say "No issues found — looks good!"

---

Diff:
```diff
{diff}
```
"""


def run_gh(*args: str, **kwargs) -> str:
    return subprocess.check_output(["gh", *args], text=True, timeout=60, **kwargs)


def filter_lock_files(diff: str) -> str:
    lines: list[str] = []
    skip = False
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git"):
            filename = line.split()[-1].removeprefix("b/")
            skip = filename.endswith(".lock")
        if not skip:
            lines.append(line)
    return "".join(lines)


def truncate_diff(diff: str) -> str:
    if len(diff) <= TRUNCATE_BYTES:
        return diff
    truncated: list[str] = []
    size = 0
    for line in diff.splitlines(keepends=True):
        if size + len(line) > TRUNCATE_BYTES and line.startswith("diff --git"):
            break
        truncated.append(line)
        size += len(line)
    return "".join(truncated) + "\n\n[... diff truncated for token limit ...]\n"


def call_ollama(base_url: str, model: str, diff: str) -> str:
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps({
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(diff=diff)},
            ],
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
        return data.get("message", {}).get("content", "")


def main() -> None:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")
    pr_number = os.environ["PR_NUMBER"]
    repo = os.environ["REPO"]

    diff = run_gh("pr", "diff", pr_number, "--repo", repo)
    if not diff.strip():
        print("Empty diff — skipping review.")
        return

    diff = filter_lock_files(diff)
    if not diff.strip():
        print("Diff contains only lock files — skipping review.")
        return

    diff_size = len(diff)
    print(f"Diff size: {diff_size:,} chars")
    if diff_size > MAX_DIFF_BYTES:
        print(f"Diff exceeds {MAX_DIFF_BYTES:,} chars — skipping review.")
        return

    diff = truncate_diff(diff)

    print(f"Calling Ollama ({model})...")
    review = call_ollama(base_url, model, diff)

    print("Posting review comment...")
    comment = (
        f"## Qwen 3.5 9B (Ollama) Code Review\n\n{review}\n\n---\n"
        f"*Automated review by Qwen 3.5 9B via Ollama — complements the Claude Opus review.*"
    )
    run_gh("pr", "comment", pr_number, "--repo", repo, "--body", comment)
    print("Done.")


if __name__ == "__main__":
    main()
