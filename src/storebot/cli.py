"""CLI commands for Storebot setup and administration."""

import re
import sys
import uuid
from pathlib import Path

from storebot.config import Settings
from storebot.tools.tradera import TraderaClient


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
    input("Press Enter after you have completed the login on Tradera...")

    client = TraderaClient(
        app_id=settings.tradera_app_id,
        app_key=settings.tradera_app_key,
        sandbox=settings.tradera_sandbox,
    )

    result = client.fetch_token(skey)

    if "error" in result:
        print(f"\nError fetching token: {result['error']}")
        if "sent_xml" in result:
            print(f"\nSent SOAP request:\n{result['sent_xml']}")
        if "response_repr" in result:
            print(f"\nParsed response object: {result['response_repr']}")
        sys.exit(1)

    print()
    print("Authorization successful!")
    print(f"  Token:   {result['token']}")
    print(f"  Expires: {result['expires']}")
    print()
    print("Note: TRADERA_USER_ID is not returned by FetchToken.")
    print("      Find your user ID in your Tradera profile and set it manually.")
    print()

    answer = input("Save token to .env? [Y/n] ").strip().lower()
    if answer in ("", "y", "yes"):
        env_path = Path(".env")
        _update_env_file(env_path, "TRADERA_USER_TOKEN", result["token"])
        print(f"Saved TRADERA_USER_TOKEN to {env_path}")
    else:
        print("Not saved. Add this to your .env manually:")
        print(f"  TRADERA_USER_TOKEN={result['token']}")
