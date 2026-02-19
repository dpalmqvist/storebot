"""CLI commands for Storebot setup and administration."""

import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anthropic

from storebot.config import Settings
from storebot.db import init_db
from storebot.tools.tradera import TraderaClient


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """Append or update a key=value pair in a .env file."""
    line = f"{key}={value}"

    if not env_path.exists():
        env_path.write_text(f"{line}\n")
        env_path.chmod(0o600)
        return

    content = env_path.read_text()
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)

    if pattern.search(content):
        env_path.write_text(pattern.sub(lambda m: line, content))
    else:
        if not content.endswith("\n"):
            content += "\n"
        env_path.write_text(content + f"{line}\n")

    env_path.chmod(0o600)


def _parse_redirect_url(url: str) -> dict:
    """Parse userId, token and expiration from Tradera's redirect URL."""
    params = parse_qs(urlparse(url.strip()).query)

    result = {"user_id": params.get("userId", [None])[0]}
    token = params.get("token", [None])[0]
    if token:
        result["token"] = token
    expires = params.get("exp", [None])[0]
    if expires:
        result["expires"] = expires
    return result


def authorize_tradera() -> None:
    """Interactive CLI to obtain a Tradera user token via the consent flow.

    Tries FetchToken (Option 2) first, falls back to the token from the
    redirect URL (Option 3) if FetchToken fails.
    """
    settings = Settings()

    if not settings.tradera_app_id:
        print("Error: TRADERA_APP_ID is not set in .env")
        sys.exit(1)
    if not settings.tradera_public_key:
        print("Error: TRADERA_PUBLIC_KEY is not set in .env")
        sys.exit(1)

    skey = str(uuid.uuid4())

    url = (
        f"https://api.tradera.com/tokenlogin.aspx"
        f"?appId={settings.tradera_app_id}"
        f"&pkey={settings.tradera_public_key}"
        f"&skey={skey}"
    )

    print("Tradera Authorization")
    print("=" * 40)
    print(f"  App ID:  {settings.tradera_app_id}")
    print(f"  Sandbox: {settings.tradera_sandbox}")
    print()
    print("Open this URL in your browser and log in to grant access:")
    print()
    print(f"  {url}")
    print()
    print("After granting access, you will be redirected to a localhost URL.")
    print("Copy the FULL redirect URL from your browser's address bar and paste it below.")
    print()
    redirect_url = input("Redirect URL: ").strip()

    if not redirect_url:
        print("Error: No URL provided.")
        sys.exit(1)

    redirect_result = _parse_redirect_url(redirect_url)
    user_id = redirect_result.get("user_id")

    print()
    print("Fetching authorization token from Tradera...")
    tradera = TraderaClient(
        app_id=settings.tradera_app_id,
        app_key=settings.tradera_app_key,
        sandbox=settings.tradera_sandbox,
    )
    fetch_result = tradera.fetch_token(skey)

    if "error" not in fetch_result:
        token = fetch_result["token"]
        expires = fetch_result.get("expires")
        print("  Token obtained via FetchToken.")
    elif "token" in redirect_result:
        token = redirect_result["token"]
        expires = redirect_result.get("expires")
        print("  FetchToken unavailable, using token from redirect URL.")
    else:
        print(f"\nError: {fetch_result['error']}")
        if "response_repr" in fetch_result:
            print(f"  Response: {fetch_result['response_repr']}")
        sys.exit(1)

    token_masked = token[:8] + "..." if len(token) > 8 else "***"
    print()
    print("Authorization successful!")
    print(f"  User ID: {user_id or 'N/A'}")
    print(f"  Token:   {token_masked}")
    print(f"  Expires: {expires or 'N/A'}")
    print()

    answer = input("Save credentials to .env? [Y/n] ").strip().lower()
    if answer in ("", "y", "yes"):
        env_path = Path(".env")
        _update_env_file(env_path, "TRADERA_USER_TOKEN", token)
        if user_id:
            _update_env_file(env_path, "TRADERA_USER_ID", user_id)
            print(f"Saved TRADERA_USER_TOKEN and TRADERA_USER_ID to {env_path}")
        else:
            print(f"Saved TRADERA_USER_TOKEN to {env_path}")
    else:
        print("Not saved. Add these to your .env manually:")
        print(f"  TRADERA_USER_TOKEN={token}")
        if user_id:
            print(f"  TRADERA_USER_ID={user_id}")


def _extract_json_array(text: str) -> str:
    """Extract a JSON array from LLM output that may contain prose or markdown."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # If the model prefixed prose before the array, extract just the array
    match = re.search(r"\[.*\]", text, re.DOTALL)
    return match.group(0) if match else text


def generate_category_descriptions(engine, api_key: str, model: str) -> int:
    """Generate Swedish descriptions for categories missing them.

    Batches categories in groups of 50 and calls Claude to generate
    one-sentence descriptions. Returns the total count of descriptions
    generated.
    """
    from sqlalchemy.orm import Session

    from storebot.db import TraderaCategory

    with Session(engine, expire_on_commit=False) as session:
        missing = (
            session.query(TraderaCategory)
            .filter(TraderaCategory.description.is_(None))
            .order_by(TraderaCategory.depth, TraderaCategory.name)
            .all()
        )
        if not missing:
            return 0

        client = anthropic.Anthropic(api_key=api_key)
        total = 0
        batch_size = 50

        for i in range(0, len(missing), batch_size):
            batch = missing[i : i + batch_size]
            lines = [f'- ID {cat.tradera_id}, Path: "{cat.path}"' for cat in batch]

            prompt = (
                "For each Tradera category below, write a 1-sentence Swedish description "
                "explaining what types of products belong there. "
                'Return ONLY a JSON array: [{"tradera_id": ..., "description": "..."}]\n\n'
                "Categories:\n" + "\n".join(lines)
            )

            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            text = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text = getattr(block, "text", "")
                    break

            text = _extract_json_array(text)

            try:
                descriptions = json.loads(text)
            except json.JSONDecodeError:
                print(f"  Warning: Failed to parse JSON for batch {i // batch_size + 1}, skipping")
                continue

            by_id = {
                d["tradera_id"]: d["description"]
                for d in descriptions
                if isinstance(d, dict) and "tradera_id" in d and "description" in d
            }
            for cat in batch:
                desc = by_id.get(cat.tradera_id)
                if desc:
                    cat.description = desc
                    total += 1

            session.commit()
            print(f"  Batch {i // batch_size + 1}: {len(by_id)} descriptions generated")

    return total


def sync_categories() -> None:
    """Sync Tradera category hierarchy and generate LLM descriptions."""
    settings = Settings()

    if not settings.tradera_app_id:
        print("Error: TRADERA_APP_ID is not set in .env")
        sys.exit(1)
    if not settings.claude_api_key:
        print("Error: CLAUDE_API_KEY is not set in .env")
        sys.exit(1)

    print("Initializing database...")
    engine = init_db()

    tradera = TraderaClient(
        app_id=settings.tradera_app_id,
        app_key=settings.tradera_app_key,
        sandbox=settings.tradera_sandbox,
    )

    print("Fetching categories from Tradera API...")
    try:
        count = tradera.sync_categories_to_db(engine)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"  Synced {count} categories to database.")

    print("Generating descriptions for categories without one...")
    desc_model = (
        settings.claude_model_simple
        or settings.claude_model_compact
        or "claude-haiku-4-5-20251001"
    )
    desc_count = generate_category_descriptions(engine, settings.claude_api_key, desc_model)
    print(f"  Generated {desc_count} descriptions.")

    print()
    print(f"Done! {count} categories synced, {desc_count} descriptions generated.")
