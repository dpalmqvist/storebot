"""CLI commands for Storebot setup and administration."""

import re
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from storebot.config import Settings
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
