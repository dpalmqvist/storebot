"""CLI commands for Storebot setup and administration."""

import re
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from storebot.config import Settings


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """Append or update a key=value pair in a .env file."""
    line = f"{key}={value}"

    if not env_path.exists():
        env_path.write_text(f"{line}\n")
        return

    content = env_path.read_text()
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)

    if pattern.search(content):
        env_path.write_text(pattern.sub(lambda m: line, content))
        return

    if not content.endswith("\n"):
        content += "\n"
    env_path.write_text(content + f"{line}\n")


def _parse_redirect_url(url: str) -> dict:
    """Parse token, userId and expiration from Tradera's redirect URL.

    Expected format:
      http://localhost:8080/auth/accept?userId=123&token=abc-def&exp=2027-...
    """
    parsed = urlparse(url.strip())
    params = parse_qs(parsed.query)

    token = params.get("token", [None])[0]
    user_id = params.get("userId", [None])[0]
    expires = params.get("exp", [None])[0]

    if not token:
        return {"error": "No 'token' parameter found in the redirect URL."}

    result = {"token": token}
    if user_id:
        result["user_id"] = user_id
    if expires:
        result["expires"] = expires
    return result


def authorize_tradera() -> None:
    """Interactive CLI to obtain a Tradera user token via the consent flow."""
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

    result = _parse_redirect_url(redirect_url)

    if "error" in result:
        print(f"\nError: {result['error']}")
        sys.exit(1)

    print()
    print("Authorization successful!")
    print(f"  User ID: {result.get('user_id', 'N/A')}")
    print(f"  Token:   {result['token']}")
    print(f"  Expires: {result.get('expires', 'N/A')}")
    print()

    answer = input("Save credentials to .env? [Y/n] ").strip().lower()
    if answer in ("", "y", "yes"):
        env_path = Path(".env")
        _update_env_file(env_path, "TRADERA_USER_TOKEN", result["token"])
        if result.get("user_id"):
            _update_env_file(env_path, "TRADERA_USER_ID", result["user_id"])
        print(f"Saved TRADERA_USER_TOKEN and TRADERA_USER_ID to {env_path}")
    else:
        print("Not saved. Add these to your .env manually:")
        print(f"  TRADERA_USER_TOKEN={result['token']}")
        if result.get("user_id"):
            print(f"  TRADERA_USER_ID={result['user_id']}")
