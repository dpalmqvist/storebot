#!/usr/bin/env python3
"""Post-release codebase review via Ollama (Qwen 3.5 9B).

Triggered by version tag pushes. Reviews the entire src/storebot/ codebase
in module chunks, ranks findings by severity, and creates GitHub issues
for the top 5 improvements. Uses only stdlib — no pip dependencies.
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

LABEL = "ai-codebase-review"
MAX_ISSUES = 5
MAX_CHUNK_CHARS = 200_000  # ~50K tokens
OLLAMA_TIMEOUT = 600  # 10 minutes per chunk

# Module chunks — logical groupings of related files
MODULE_CHUNKS: dict[str, list[str]] = {
    "Core": [
        "agent.py",
        "config.py",
        "db.py",
        "retry.py",
        "logging_config.py",
    ],
    "Bot": [
        "bot/formatting.py",
        "bot/handlers.py",
    ],
    "Marketplace integrations": [
        "tools/tradera.py",
        "tools/blocket.py",
        "tools/postnord.py",
    ],
    "Business logic": [
        "tools/listing.py",
        "tools/order.py",
        "tools/pricing.py",
        "tools/accounting.py",
    ],
    "Intelligence agents": [
        "tools/scout.py",
        "tools/marketing.py",
        "tools/analytics.py",
    ],
    "Tool infrastructure": [
        "tools/definitions.py",
        "tools/dispatch.py",
        "tools/schemas.py",
        "tools/helpers.py",
        "tools/image.py",
        "tools/conversation.py",
    ],
    "Services": [
        "mcp_server.py",
        "cli.py",
        "tui/log_viewer.py",
    ],
}

SYSTEM_PROMPT = """\
You are an expert Python code reviewer performing a periodic whole-codebase \
review of **Storebot**, an AI-powered marketplace agent system.

Key context:
- Python 3.11+, SQLAlchemy 2.0 (SQLite), Pydantic Settings
- Claude API agent loop with 57 tools (no LangChain)
- Telegram bot via python-telegram-bot v20+
- Swedish business rules: BAS-kontoplan, 25% VAT, voucher-based accounting
- External APIs: Tradera (SOAP/zeep), Blocket (unofficial REST), PostNord (REST)
- Deployment: Raspberry Pi 5, systemd, SQLite WAL mode
- MCP server exposing all tools via stdio and streamable-http

Review focus:
1. **Code smells** — duplicated logic, overly complex functions, dead code
2. **Bugs & logic errors** — off-by-one, None handling, wrong comparisons
3. **Security** — injection, secret exposure, unsafe deserialization
4. **Inconsistencies** — different patterns for the same thing across modules
5. **Performance** — unnecessary allocations, N+1 queries, missing indexes
6. **Missing error handling** — unhandled exceptions, silent failures
7. **Python best practices** — type hints, datetime.now(UTC), clean imports

Do NOT flag:
- Minor style preferences (formatting, naming conventions that are consistent)
- Missing docstrings or comments on internal functions
- Test coverage gaps (this review is for production code only)
"""

CHUNK_PROMPT_PREFIX = """\
Review the following module chunk: **$CHUNK_NAME$**

Return your findings as a JSON array. Each finding must have these fields:
- "severity": "critical", "warning", or "suggestion"
- "file": relative path from repo root (e.g. "src/storebot/tools/tradera.py")
- "title": short issue title (max 80 chars)
- "description": what the issue is and why it matters (1-3 sentences)
- "suggestion": how to fix it (1-3 sentences, with brief code snippet if helpful)

Return ONLY the JSON array, no markdown fences, no extra text.
If no issues found, return an empty array: []

---

"""

RANKING_PROMPT_PREFIX = """\
Below are code review findings from a whole-codebase review. Select the top \
$N$ most impactful findings — prioritize critical bugs and security issues, \
then warnings, then suggestions. Prefer findings that affect correctness or \
security over style improvements.

Return ONLY a JSON array of the top $N$ findings (same schema as input), \
ranked from most to least impactful. No markdown fences, no extra text.

Findings:
"""


def run_gh(*args: str) -> str:
    """Run a gh CLI command and return stdout."""
    return subprocess.check_output(["gh", *args], text=True, timeout=60)


def call_ollama(base_url: str, model: str, system: str, user: str) -> str:
    """Send a chat request to Ollama and return the response content."""
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(
            {
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
        data = json.loads(resp.read())
        return data.get("message", {}).get("content", "")


def read_module_chunk(base_dir: Path, chunk_name: str, files: list[str]) -> str:
    """Read and concatenate files with header separators."""
    parts: list[str] = []
    for relpath in files:
        full = base_dir / relpath
        if not full.is_file():
            continue
        content = full.read_text(encoding="utf-8", errors="replace")
        parts.append(f"# --- file: src/storebot/{relpath} ---\n{content}")
    combined = "\n\n".join(parts)
    if len(combined) > MAX_CHUNK_CHARS:
        print(f"  WARNING: {chunk_name} is {len(combined):,} chars, may exceed context window")
    return combined


def parse_json_findings(text: str) -> list[dict]:
    """Extract a JSON array from LLM response, tolerating markdown fences."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # Strip </think> tags from reasoning models
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    try:
        result = json.loads(text)
        if isinstance(result, list) and all(isinstance(f, dict) for f in result):
            return result
    except json.JSONDecodeError:
        pass
    # Try to find a JSON array in the text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, list) and all(isinstance(f, dict) for f in result):
                return result
        except json.JSONDecodeError:
            pass
    return []


def review_chunk(base_url: str, model: str, chunk_name: str, code: str) -> list[dict]:
    """Review a single module chunk and return findings."""
    print(f"  Reviewing chunk: {chunk_name}...")
    user_prompt = CHUNK_PROMPT_PREFIX.replace("$CHUNK_NAME$", chunk_name) + code
    try:
        response = call_ollama(base_url, model, SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        print(f"  WARNING: Ollama call failed for {chunk_name}: {exc}")
        return []
    findings = parse_json_findings(response)
    print(f"  Found {len(findings)} finding(s) in {chunk_name}")
    return findings


def rank_findings(base_url: str, model: str, findings: list[dict]) -> list[dict]:
    """Rank all findings and return the top N most impactful."""
    if len(findings) <= MAX_ISSUES:
        return findings
    print(f"Ranking {len(findings)} findings to select top {MAX_ISSUES}...")
    user_prompt = RANKING_PROMPT_PREFIX.replace("$N$", str(MAX_ISSUES)) + json.dumps(
        findings, indent=2
    )
    try:
        response = call_ollama(base_url, model, SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        print(f"WARNING: Ranking call failed: {exc}")
        # Fallback: take first MAX_ISSUES sorted by severity
        severity_order = {"critical": 0, "warning": 1, "suggestion": 2}
        findings.sort(key=lambda f: severity_order.get(f.get("severity", ""), 2))
        return findings[:MAX_ISSUES]
    ranked = parse_json_findings(response)
    return ranked[:MAX_ISSUES] if ranked else findings[:MAX_ISSUES]


def find_duplicate_titles(repo: str) -> set[str]:
    """Get titles of existing open issues with the review label."""
    try:
        output = run_gh(
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            LABEL,
            "--state",
            "open",
            "--json",
            "title",
            "--limit",
            "500",
        )
        issues = json.loads(output)
        return {issue["title"] for issue in issues}
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return set()


def ensure_label(repo: str) -> None:
    """Create the review label if it doesn't exist."""
    try:
        run_gh(
            "label",
            "create",
            LABEL,
            "--repo",
            repo,
            "--description",
            "Automated codebase review findings",
            "--color",
            "C5DEF5",
        )
        print(f"Created label: {LABEL}")
    except subprocess.CalledProcessError:
        # Label already exists
        pass


def create_issue(repo: str, finding: dict) -> None:
    """Create a GitHub issue for a finding."""
    title = f"[AI Review] {finding.get('title', 'Untitled finding')}"
    severity = finding.get("severity", "suggestion")
    file_path = finding.get("file", "unknown")
    description = finding.get("description", "No description provided.")
    suggestion = finding.get("suggestion", "No suggestion provided.")

    body = (
        f"**File:** `{file_path}`\n"
        f"**Severity:** {severity}\n\n"
        f"## Description\n{description}\n\n"
        f"## Suggested Fix\n{suggestion}\n\n"
        f"---\n"
        f"*Automated codebase review by Qwen 3.5 9B via Ollama (post-release).*\n\n"
        f"@claude Please review this suggestion and implement it if appropriate. "
        f"Create a PR with the fix."
    )
    run_gh(
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
        "--label",
        LABEL,
    )
    print(f"Created issue: {title}")


def main() -> None:
    base_url = os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
    model = os.environ.get("OLLAMA_MODEL") or "qwen3.5:9b"
    repo = os.environ.get("REPO", "")
    if not repo:
        print("ERROR: REPO environment variable not set.")
        sys.exit(1)

    src_dir = Path("src/storebot")
    if not src_dir.is_dir():
        print(f"ERROR: {src_dir} not found.")
        sys.exit(1)

    # Discover and review module chunks
    tag = os.environ.get("GITHUB_REF_NAME", "unknown")
    print(f"Starting codebase review for {tag} with {model}...")
    all_findings: list[dict] = []
    for chunk_name, files in MODULE_CHUNKS.items():
        code = read_module_chunk(src_dir, chunk_name, files)
        if not code.strip():
            print(f"  Skipping empty chunk: {chunk_name}")
            continue
        findings = review_chunk(base_url, model, chunk_name, code)
        all_findings.extend(findings)

    if not all_findings:
        print("No findings — codebase looks good!")
        return

    print(f"\nTotal findings: {len(all_findings)}")

    # Rank and select top findings
    top_findings = rank_findings(base_url, model, all_findings)
    print(f"Selected top {len(top_findings)} finding(s)")

    # Create issues, skipping duplicates
    ensure_label(repo)
    existing_titles = find_duplicate_titles(repo)
    created = 0
    for finding in top_findings:
        title = f"[AI Review] {finding.get('title', 'Untitled finding')}"
        if title in existing_titles:
            print(f"Skipping duplicate: {title}")
            continue
        create_issue(repo, finding)
        created += 1

    print(f"\nDone. Created {created} issue(s).")


if __name__ == "__main__":
    main()
