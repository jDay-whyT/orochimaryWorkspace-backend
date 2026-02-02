"""Flow filter for text message routing."""

from typing import Set
from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.state import MemoryState


class FlowFilter(BaseFilter):
    """Filter that checks if user's current flow matches allowed flows."""

    def __init__(self, allowed_flows: Set[str]):
        """
        Initialize flow filter.

        Args:
            allowed_flows: Set of flow names that should pass this filter.
                          Example: {"search", "new_order", "view", "comment"}
        """
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
        data = memory_state.get(user_id)

        if not data:
            return False

        current_flow = data.get("flow")
        return current_flow in self.allowed_flows
