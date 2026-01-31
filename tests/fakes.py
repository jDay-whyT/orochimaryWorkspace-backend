from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeChat:
    id: int


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def edit_message_text(
        self,
        text: str,
        chat_id: int,
        message_id: int,
        reply_markup=None,
        **kwargs: Any,
    ) -> None:
        self.calls.append(
            {
                "type": "bot_edit",
                "text": text,
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
                "kwargs": kwargs,
            }
        )


class FakeMessage:
    def __init__(
        self,
        text: str = "",
        user_id: int = 111,
        chat_id: int = 100,
        message_id: int = 1,
        bot: FakeBot | None = None,
    ) -> None:
        self.text = text
        self.from_user = FakeUser(user_id)
        self.chat = FakeChat(chat_id)
        self.message_id = message_id
        self.bot = bot or FakeBot()
        self.answers: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.outgoing: list[dict[str, Any]] = []
        self.deleted = False

    async def answer(self, text: str, reply_markup=None, **kwargs: Any) -> None:
        entry = {
            "type": "answer",
            "text": text,
            "reply_markup": reply_markup,
            "kwargs": kwargs,
        }
        self.answers.append(entry)
        self.outgoing.append(entry)

    async def edit_text(self, text: str, reply_markup=None, **kwargs: Any) -> None:
        entry = {
            "type": "edit",
            "text": text,
            "reply_markup": reply_markup,
            "kwargs": kwargs,
        }
        self.edits.append(entry)
        self.outgoing.append(entry)

    async def delete(self) -> None:
        self.deleted = True


class FakeCallbackQuery:
    def __init__(self, data: str, message: FakeMessage, user_id: int = 111) -> None:
        self.data = data
        self.message = message
        self.from_user = FakeUser(user_id)
        self.callback_answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False, **kwargs: Any) -> None:
        self.callback_answers.append(
            {
                "type": "callback_answer",
                "text": text,
                "show_alert": show_alert,
                "kwargs": kwargs,
            }
        )
