from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Claude API
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5-20250929"

    # Telegram
    telegram_bot_token: str = ""

    # Tradera
    tradera_app_id: str = ""
    tradera_app_key: str = ""
    tradera_public_key: str = ""
    tradera_sandbox: bool = True
    tradera_user_id: str = ""
    tradera_user_token: str = ""

    # Blocket (unofficial, bearer token from browser session)
    blocket_bearer_token: str = ""

    # PostNord (shipping labels)
    postnord_api_key: str = ""
    postnord_sandbox: bool = True
    postnord_sender_name: str = ""
    postnord_sender_street: str = ""
    postnord_sender_postal_code: str = ""
    postnord_sender_city: str = ""
    postnord_sender_country_code: str = "SE"
    postnord_sender_phone: str = ""
    postnord_sender_email: str = ""

    # Product images
    product_image_dir: str = "data/images"

    # Shipping label export
    label_export_path: str = "data/labels"

    # Order polling
    order_poll_interval_minutes: int = 30

    # Conversation history
    max_history_messages: int = 20
    conversation_timeout_minutes: int = 60

    # Extended thinking
    claude_thinking_budget: int = 0  # 0 = disabled, >= 1024 to enable
    claude_max_tokens: int = 16000  # max output tokens per API call

    # Context compaction
    claude_model_compact: str = "claude-haiku-3-5-20241022"
    compact_threshold: int = 20  # trigger compaction above this many messages
    compact_keep_recent: int = 6  # keep this many recent messages verbatim

    # Scout
    scout_digest_hour: int = 8  # Hour (0-23) for daily scout digest

    # Marketing
    marketing_refresh_hour: int = 7  # Hour (0-23) for daily stats refresh

    # Database
    database_path: str = "data/storebot.db"

    # Voucher PDF export
    voucher_export_path: str = "data/vouchers"

    # Access control
    allowed_chat_ids: str = ""  # comma-separated Telegram user/chat IDs

    # Rate limiting
    rate_limit_messages: int = 30  # max messages per window
    rate_limit_window_seconds: int = 60

    # Logging
    log_level: str = "INFO"
    log_json: bool = True
    log_file: str = ""


def get_settings() -> Settings:
    return Settings()
