"""Filters for topic/thread access in group chats."""

import logging

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import Config

LOGGER = logging.getLogger(__name__)


class TopicAccessMessageFilter(BaseFilter):
    """Restrict access by topic/chat and user role."""

    async def __call__(self, message: Message, config: Config) -> bool:
        if not message.from_user:
            LOGGER.info("TopicAccessFilter: no from_user")
            return False
        user_id = message.from_user.id
        LOGGER.info(
            "TopicAccessFilter: chat_type=%s thread_id=%s user=%s crm_thread=%s",
            message.chat.type,
            message.message_thread_id,
            user_id,
            config.crm_topic_thread_id,
        )

        if message.chat.type == "private":
            result = user_id in config.allowed_editors
            LOGGER.info("TopicAccessFilter: private chat result=%s", result)
            return result
        if message.chat.type not in {"group", "supergroup"}:
            LOGGER.info("TopicAccessFilter: unsupported chat type")
            return False
        if config.scouts_chat_id and message.chat.id == config.scouts_chat_id:
            result = user_id in (config.allowed_editors | config.report_viewers)
            LOGGER.info("TopicAccessFilter: scouts chat result=%s", result)
            return result
        if message.message_thread_id != config.crm_topic_thread_id:
            LOGGER.info("TopicAccessFilter: wrong thread")
            return False
        result = user_id in config.allowed_editors
        LOGGER.info("TopicAccessFilter: crm topic result=%s", result)
        return result


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


class RentTopicFilter(BaseFilter):
    """Allow group messages only from the rent topic.

    If rent_topic_thread_id is 0 (not configured), passes nothing.
    Allows any user (not restricted to allowed_editors) to use rent search.
    """

    async def __call__(self, message: Message, config: Config) -> bool:
        if message.chat.type == "private":
            return True
        if config.rent_topic_thread_id == 0:
            return False
        if message.chat.type not in {"group", "supergroup"}:
            return False
        if message.message_thread_id != config.rent_topic_thread_id:
            return False
        if not message.from_user:
            return False
        return True


class RentTopicCallbackFilter(BaseFilter):
    """Allow callbacks only from the rent topic (or private chats).

    If rent_topic_thread_id is 0 (not configured), passes nothing in groups.
    """

    async def __call__(self, query: CallbackQuery, config: Config) -> bool:
        message = query.message
        if not message:
            return True
        if message.chat.type == "private":
            return True
        if message.chat.type not in {"group", "supergroup"}:
            return False
        if config.rent_topic_thread_id == 0:
            return False
        if message.message_thread_id != config.rent_topic_thread_id:
            return False
        return True


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
