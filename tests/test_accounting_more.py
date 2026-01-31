import pytest

from app.handlers.accounting import handle_text_input
from tests.fakes import FakeMessage


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["0", "1001", "abc"])
async def test_accounting_invalid_count_edits_screen_message(
    config_admin,
    memory_state,
    recent_models,
    text,
):
    memory_state.set(
        111,
        {
            "flow": "accounting",
            "step": "add_files_custom",
            "screen_chat_id": 900,
            "screen_message_id": 901,
        },
    )
    message = FakeMessage(text=text, user_id=111)

    await handle_text_input(message, config_admin, memory_state, recent_models)

    assert message.bot.calls
    last_call = message.bot.calls[-1]
    assert last_call["text"] == "Invalid number. Please enter a number between 1 and 1000:"
    assert last_call["chat_id"] == 900
    assert last_call["message_id"] == 901
