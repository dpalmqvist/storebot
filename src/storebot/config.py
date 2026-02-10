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
    tradera_sandbox: bool = True
    tradera_user_id: str = ""
    tradera_user_token: str = ""

    # Blocket (unofficial, bearer token from browser session)
    blocket_bearer_token: str = ""

    # PostNord (shipping labels)
    postnord_api_key: str = ""
    postnord_sender_name: str = ""
    postnord_sender_address: str = ""

    # Order polling
    order_poll_interval_minutes: int = 30

    # Database
    database_path: str = "data/storebot.db"

    # Voucher PDF export
    voucher_export_path: str = "data/vouchers"

    # Logging
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
