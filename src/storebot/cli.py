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
    """Parse userId from Tradera's redirect URL after consent.

    Expected format:
      http://localhost:8080/auth/accept?userId=123&token=abc-def&exp=2027-...
    """
    parsed = urlparse(url.strip())
    params = parse_qs(parsed.query)

    user_id = params.get("userId", [None])[0]

    return {"user_id": user_id}


def authorize_tradera() -> None:
    """Interactive CLI to obtain a Tradera user token via the consent flow.

    Uses Option 2 from Tradera's authorization docs: after the user grants
    consent and is redirected, we call FetchToken with the secret key to
    retrieve the real authorization token.
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

    # Parse userId from redirect URL
    redirect_result = _parse_redirect_url(redirect_url)

    # Call FetchToken with the secret key to get the real auth token
    print()
    print("Fetching authorization token from Tradera...")
    tradera = TraderaClient(
        app_id=settings.tradera_app_id,
        app_key=settings.tradera_app_key,
        sandbox=settings.tradera_sandbox,
    )
    result = tradera.fetch_token(skey)

    if "error" in result:
        print(f"\nError: {result['error']}")
        if "response_repr" in result:
            print(f"  Response: {result['response_repr']}")
        sys.exit(1)

    token = result["token"]
    expires = result.get("expires")
    user_id = redirect_result.get("user_id")

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
