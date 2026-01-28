import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_webhook_secret: str
    notion_token: str
    notion_orders_db_id: str
    notion_models_db_id: str
    allowed_editors: set[int]
    timezone: ZoneInfo


def _parse_allowed_editors(value: str) -> set[int]:
    if not value:
        return set()
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


def load_config() -> Config:
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    notion_orders_db_id = os.getenv("NOTION_ORDERS_DB_ID", "").strip()
    notion_models_db_id = os.getenv("NOTION_MODELS_DB_ID", "").strip()
    allowed_editors = _parse_allowed_editors(os.getenv("ALLOWED_EDITORS", ""))
    timezone_name = os.getenv("TIMEZONE", "UTC")
    return Config(
        telegram_bot_token=telegram_bot_token,
        telegram_webhook_secret=telegram_webhook_secret,
        notion_token=notion_token,
        notion_orders_db_id=notion_orders_db_id,
        notion_models_db_id=notion_models_db_id,
        allowed_editors=allowed_editors,
        timezone=ZoneInfo(timezone_name),
    )
