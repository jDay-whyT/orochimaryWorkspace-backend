"""Flow filter for text message routing."""

import logging
from typing import Set
from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.state import MemoryState

LOGGER = logging.getLogger(__name__)


class FlowFilter(BaseFilter):
    """Filter that checks if user's current flow matches allowed flows."""

    def __init__(self, allowed_flows: Set[str]):
        """
        Initialize flow filter.

        Args:
            allowed_flows: Set of flow names that should pass this filter.
                          All flow names must start with 'nlp_' prefix.
                          Example: {"nlp_search", "nlp_new_order", "nlp_view", "nlp_comment"}
        """
        # Validate that all flows have nlp_ prefix
        invalid_flows = {f for f in allowed_flows if not f.startswith("nlp_")}
        if invalid_flows:
            raise ValueError(
                f"Invalid flow names detected: {invalid_flows}. "
                f"All flows must start with 'nlp_' prefix."
            )
        self.allowed_flows = allowed_flows

    async def __call__(self, message: Message, memory_state: MemoryState) -> bool:
        """
        Check if user's current flow is in allowed flows.

        Args:
            message: Incoming message
            memory_state: Memory state dependency

        Returns:
            True if current flow is in allowed_flows, False otherwise
        """
        user_id = message.from_user.id
        chat_id = message.chat.id
        data = memory_state.get(chat_id, user_id)

        if not data:
            return False

        current_flow = data.get("flow")
        return current_flow in self.allowed_flows
