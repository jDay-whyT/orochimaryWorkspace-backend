"""Filters for topic/thread access in group chats."""

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import Config


class TopicAccessMessageFilter(BaseFilter):
    """Allow all private messages, restrict group messages to CRM topic and editors."""

    async def __call__(self, message: Message, config: Config) -> bool:
        if message.chat.type == "private":
            return True
        if message.chat.type not in {"group", "supergroup"}:
            return False
        if message.message_thread_id != config.crm_topic_thread_id:
            return False
        return message.from_user.id in config.allowed_editors


class TopicAccessCallbackFilter(BaseFilter):
    """Allow all private callbacks, restrict group callbacks to CRM topic and editors."""

    async def __call__(self, query: CallbackQuery, config: Config) -> bool:
        message = query.message
        if not message:
            return True
        if message.chat.type == "private":
            return True
        if message.chat.type not in {"group", "supergroup"}:
            return False
        if message.message_thread_id != config.crm_topic_thread_id:
            return False
        return query.from_user.id in config.allowed_editors


class ManagersTopicFilter(BaseFilter):
    """Allow only manager-topic messages from configured editors."""

    async def __call__(self, message: Message, config: Config) -> bool:
        if config.managers_topic_thread_id == 0:
            return False
        if message.chat.type not in {"group", "supergroup"}:
            return False
        if message.message_thread_id != config.managers_topic_thread_id:
            return False
        return message.from_user.id in config.allowed_editors
