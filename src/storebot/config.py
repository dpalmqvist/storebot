from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Claude API
    claude_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""

    # Tradera
    tradera_app_id: str = ""
    tradera_app_key: str = ""

    # Fortnox (OAuth2)
    fortnox_client_id: str = ""
    fortnox_client_secret: str = ""
    fortnox_access_token: str = ""

    # Blocket (unofficial, bearer token from browser session)
    blocket_bearer_token: str = ""

    # Database
    database_path: str = "data/storebot.db"

    # Logging
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
