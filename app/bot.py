import logging
from typing import Any

from aiogram import Bot, Dispatcher

from app.config import Config
from app.handlers import start, orders, summary, planner, accounting, reports, nlp_callbacks, notifications, group_manager
from app.services import NotionClient
from app.state import MemoryState, RecentModels

LOGGER = logging.getLogger(__name__)


def create_dispatcher(config: Config) -> tuple[Bot, Dispatcher, NotionClient, Any, Any]:
    """Create bot, dispatcher and services."""
    bot = Bot(token=config.telegram_bot_token)
    dp = Dispatcher()

    # Register handlers in priority order:
    # 1. Flow-specific routers with FlowFilter (only handle text when their flow is active)
    dp.include_router(notifications.router) # /shoots command
    dp.include_router(orders.router)       # FlowFilter({"search", "new_order", "view", "comment"})
    dp.include_router(summary.router)      # FlowFilter({"summary"})
    dp.include_router(planner.router)      # FlowFilter({"planner"})
    dp.include_router(accounting.router)   # FlowFilter({"accounting"})
    # NLP callback router (handles nlp: prefixed callbacks, including report detail)
    dp.include_router(nlp_callbacks.router)
    # Group manager triggers (must run before NLP fallback)
    dp.include_router(group_manager.router)
    # 2. Fallback router (NLP + /start) - handles all unmatched text messages
    dp.include_router(start.router)        # MUST BE LAST - catches all text via NLP

    # Create services
    notion = NotionClient(config.notion_token)
    if config.redis_url:
        from app.state.redis_recent import RedisRecentModels
        from app.state.redis_state import RedisMemoryState

        memory_state = RedisMemoryState(redis_url=config.redis_url)
        recent_models = RedisRecentModels(redis_url=config.redis_url)
    else:
        memory_state = MemoryState()
        recent_models = RecentModels()

    # Inject dependencies
    dp["config"] = config
    dp["notion"] = notion
    dp["memory_state"] = memory_state
    dp["recent_models"] = recent_models

    router_names = [r.name or r.__class__.__name__ for r in dp.sub_routers]
    LOGGER.info("Bot dispatcher created, routers=%s", router_names)

    # Log message handler count in the fallback (start) router
    msg_handlers = start.router.message.handlers
    LOGGER.info(
        "start.router message handlers: %d entries = %s",
        len(msg_handlers),
        [type(h.callback).__name__ if hasattr(h, 'callback') else str(h) for h in msg_handlers],
    )

    return bot, dp, notion, memory_state, recent_models
