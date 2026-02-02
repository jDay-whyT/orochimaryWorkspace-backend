import logging

from aiogram import Bot, Dispatcher

from app.config import Config
from app.handlers import start, orders, summary, planner, accounting, reports
from app.services import NotionClient
from app.state import MemoryState, RecentModels

LOGGER = logging.getLogger(__name__)


def create_dispatcher(config: Config) -> tuple[Bot, Dispatcher, NotionClient, MemoryState, RecentModels]:
    """Create bot, dispatcher and services."""
    bot = Bot(token=config.telegram_bot_token)
    dp = Dispatcher()

    # Register handlers in priority order:
    # 1. Flow-specific routers with FlowFilter (only handle text when their flow is active)
    dp.include_router(orders.router)       # FlowFilter({"search", "new_order", "view", "comment"})
    dp.include_router(summary.router)      # FlowFilter({"summary"})
    dp.include_router(planner.router)      # FlowFilter({"planner"})
    dp.include_router(accounting.router)   # FlowFilter({"accounting"})
    dp.include_router(reports.router)
    # 2. Fallback router (NLP + /start) - handles all unmatched text messages
    dp.include_router(start.router)        # MUST BE LAST - catches all text via NLP
    
    # Create services
    notion = NotionClient(config.notion_token)
    memory_state = MemoryState()
    recent_models = RecentModels()
    
    # Inject dependencies
    dp["config"] = config
    dp["notion"] = notion
    dp["memory_state"] = memory_state
    dp["recent_models"] = recent_models
    
    LOGGER.info("Bot dispatcher created")
    
    return bot, dp, notion, memory_state, recent_models
