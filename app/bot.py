import logging

from aiogram import Bot, Dispatcher

from app.config import Config
from app.handlers import orders
from app.notion import NotionClient
from app.state import MemoryState

LOGGER = logging.getLogger(__name__)


def create_dispatcher(config: Config) -> tuple[Bot, Dispatcher, NotionClient, MemoryState]:
    bot = Bot(token=config.telegram_bot_token, parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(orders.router)
    notion = NotionClient(config.notion_token)
    state = MemoryState()
    dp["config"] = config
    dp["notion"] = notion
    dp["memory_state"] = state
    return bot, dp, notion, state
