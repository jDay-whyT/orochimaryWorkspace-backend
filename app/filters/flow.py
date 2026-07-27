"""Flow filter for text message routing."""

from typing import Set
from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.state import MemoryState


class FlowFilter(BaseFilter):
    """Filter that checks if user's current flow matches allowed flows."""

    def __init__(self, allowed_flows: Set[str]):
        self.allowed_flows = allowed_flows

    async def __call__(self, message: Message, memory_state: MemoryState) -> bool:
        user_id = message.from_user.id
        chat_id = message.chat.id
        data = memory_state.get(chat_id, user_id)

        if not data:
            return False

        current_flow = data.get("flow")
        return current_flow in self.allowed_flows
