import os
import sys
from dataclasses import dataclass
from zoneinfo import ZoneInfo


class ConfigValidationError(Exception):
    """Raised when configuration is invalid."""
    pass


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_webhook_secret: str
    notion_token: str
    
    # Database IDs (data source / collection IDs)
    db_models: str
    db_orders: str
    db_planner: str
    db_accounting: str
    
    # Roles
    admin_ids: set[int]
    editor_ids: set[int]
    viewer_ids: set[int]
    
    timezone: ZoneInfo
    files_per_month: int


def _parse_user_ids(value: str) -> set[int]:
    """Parse comma-separated user IDs from env variable."""
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


def _validate_config(config: Config) -> None:
    """Validate configuration and raise ConfigValidationError if invalid."""
    errors = []
    
    # Critical: Tokens must be present
    if not config.telegram_bot_token:
        errors.append("TELEGRAM_BOT_TOKEN is required")
    
    if not config.notion_token:
        errors.append("NOTION_TOKEN is required")
    
    # Critical: At least one admin must be configured
    if not config.admin_ids and not config.editor_ids and not config.viewer_ids:
        errors.append("At least one user ID must be configured (ADMIN_IDS, EDITOR_IDS, or VIEWER_IDS)")
    
    # Validate database IDs format (should be UUIDs)
    db_ids = {
        "DB_MODELS": config.db_models,
        "DB_ORDERS": config.db_orders,
        "DB_PLANNER": config.db_planner,
        "DB_ACCOUNTING": config.db_accounting,
    }
    
    for name, db_id in db_ids.items():
        if not db_id:
            errors.append(f"{name} is required")
        elif len(db_id.replace("-", "")) != 32:  # UUID without dashes should be 32 chars
            errors.append(f"{name} appears to be invalid (should be a UUID)")
    
    # Validate FILES_PER_MONTH
    if config.files_per_month <= 0:
        errors.append(f"FILES_PER_MONTH must be positive (got {config.files_per_month})")
    
    if errors:
        error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ConfigValidationError(error_msg)


def load_config(validate: bool = True) -> Config:
    """
    Load configuration from environment variables.
    
    Args:
        validate: If True, validate configuration and fail fast on errors
    
    Raises:
        ConfigValidationError: If validate=True and configuration is invalid
    """
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    
    # Database IDs
    db_models = os.getenv("DB_MODELS", "1fc32bee-e7a0-809f-8bbe-000be8182d4d").strip()
    db_orders = os.getenv("DB_ORDERS", "20b32bee-e7a0-81ab-b72b-000b78a1e78a").strip()
    db_planner = os.getenv("DB_PLANNER", "1fb32bee-e7a0-815f-ae1d-000ba6995a1a").strip()
    db_accounting = os.getenv("DB_ACCOUNTING", "1ff32bee-e7a0-8025-a26c-000bc7008ec8").strip()
    
    # Roles
    admin_ids = _parse_user_ids(os.getenv("ADMIN_IDS", ""))
    editor_ids = _parse_user_ids(os.getenv("EDITOR_IDS", ""))
    viewer_ids = _parse_user_ids(os.getenv("VIEWER_IDS", ""))
    
    timezone_name = os.getenv("TIMEZONE", "Europe/Brussels")  # Default to europe-west1 region
    
    try:
        files_per_month = int(os.getenv("FILES_PER_MONTH", "200"))
    except ValueError:
        print("ERROR: FILES_PER_MONTH must be an integer", file=sys.stderr)
        sys.exit(1)
    
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception as e:
        print(f"ERROR: Invalid TIMEZONE '{timezone_name}': {e}", file=sys.stderr)
        sys.exit(1)
    
    config = Config(
        telegram_bot_token=telegram_bot_token,
        telegram_webhook_secret=telegram_webhook_secret,
        notion_token=notion_token,
        db_models=db_models,
        db_orders=db_orders,
        db_planner=db_planner,
        db_accounting=db_accounting,
        admin_ids=admin_ids,
        editor_ids=editor_ids,
        viewer_ids=viewer_ids,
        timezone=timezone,
        files_per_month=files_per_month,
    )
    
    if validate:
        try:
            _validate_config(config)
        except ConfigValidationError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            print("\nPlease check your .env file and ensure all required variables are set.", file=sys.stderr)
            sys.exit(1)
    
    return config
