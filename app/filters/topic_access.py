"""Filters for topic/thread access in group chats."""

import logging

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import Config

LOGGER = logging.getLogger(__name__)


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


class ManagersTopicFilter(BaseFilter):
    """Allow group messages only from the managers topic and allowed editors.

    If managers_topic_thread_id is 0 (not configured), passes nothing.
    """

    async def __call__(self, message: Message, config: Config) -> bool:
        if config.managers_topic_thread_id == 0:
            LOGGER.info("ManagersTopicFilter: thread_id=%s expected=%s user=%s",
                        message.message_thread_id, config.managers_topic_thread_id,
                        message.from_user.id if message.from_user else None)
            return False
        if message.chat.type not in {"group", "supergroup"}:
            LOGGER.info("ManagersTopicFilter: thread_id=%s expected=%s user=%s",
                        message.message_thread_id, config.managers_topic_thread_id,
                        message.from_user.id if message.from_user else None)
            return False
        if message.message_thread_id != config.managers_topic_thread_id:
            LOGGER.info("ManagersTopicFilter: thread_id=%s expected=%s user=%s",
                        message.message_thread_id, config.managers_topic_thread_id,
                        message.from_user.id if message.from_user else None)
            return False
        if not message.from_user:
            LOGGER.info("ManagersTopicFilter: thread_id=%s expected=%s user=%s",
                        message.message_thread_id, config.managers_topic_thread_id,
                        message.from_user.id if message.from_user else None)
            return False
        LOGGER.info("ManagersTopicFilter: thread_id=%s expected=%s user=%s",
                    message.message_thread_id, config.managers_topic_thread_id,
                    message.from_user.id if message.from_user else None)
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
