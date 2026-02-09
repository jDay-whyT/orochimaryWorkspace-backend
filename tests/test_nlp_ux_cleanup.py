import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.state.memory import MemoryState
from app.handlers.nlp_callbacks import _handle_back_to_card, handle_nlp_callback
from app.router.dispatcher import _handle_custom_files_input, _handle_custom_date_input


def _make_query(user_id=1, data="nlp:bk:model-1"):
    query = MagicMock()
    query.from_user.id = user_id
    query.data = data
    query.answer = AsyncMock()
    query.message = MagicMock()
    query.message.chat.id = 100
    query.message.message_id = 200
    query.message.edit_text = AsyncMock(return_value=query.message)
    query.message.delete = AsyncMock()
    query.bot = AsyncMock()
    query.bot.edit_message_reply_markup = AsyncMock()
    query.bot.delete_message = AsyncMock()
    query.bot.edit_message_text = AsyncMock()
    return query


def _make_message(user_id=1, text="5"):
    message = MagicMock()
    message.from_user.id = user_id
    message.chat.id = 100
    message.text = text
    message.answer = AsyncMock(return_value=MagicMock(message_id=555))
    message.bot = AsyncMock()
    message.bot.edit_message_reply_markup = AsyncMock()
    message.bot.delete_message = AsyncMock()
    message.bot.edit_message_text = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_back_is_stateless():
    memory_state = MemoryState()
    query = _make_query()
    notion = AsyncMock()
    notion.get_model.return_value = MagicMock(title="Test Model")
    config = MagicMock()

    with patch("app.services.model_card.build_model_card", new=AsyncMock(return_value=("CARD", 0))):
        await _handle_back_to_card(query, config, notion, memory_state, "model-1")

    state = memory_state.get(query.message.chat.id, query.from_user.id)
    assert state["model_id"] == "model-1"
    query.message.edit_text.assert_called_once()
    assert query.message.edit_text.call_args.args[0] == "CARD"


@pytest.mark.asyncio
async def test_remove_keyboard_on_success():
    memory_state = MemoryState()
    message = _make_message(text="5")
    user_state = {
        "flow": "nlp_files",
        "step": "awaiting_count",
        "model_id": "model-1",
        "model_name": "Model",
        "screen_message_id": 111,
        "prompt_message_id": 222,
    }
    memory_state.set(message.chat.id, message.from_user.id, dict(user_state))

    from zoneinfo import ZoneInfo
    config = MagicMock()
    config.files_per_month = 200
    config.timezone = ZoneInfo("UTC")
    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(files=0, page_id="acc-1")

    await _handle_custom_files_input(message, "5", user_state, config, notion, memory_state)

    message.bot.edit_message_reply_markup.assert_called_with(
        chat_id=message.chat.id,
        message_id=111,
        reply_markup=None,
    )


@pytest.mark.asyncio
async def test_date_prompt_cleanup():
    memory_state = MemoryState()
    message = _make_message(text="05.02")
    user_state = {
        "flow": "nlp_order",
        "step": "awaiting_custom_date",
        "model_id": "model-1",
        "model_name": "Model",
        "order_type": "custom",
        "count": 1,
        "prompt_message_id": 333,
        "screen_message_id": 444,
    }
    memory_state.set(message.chat.id, message.from_user.id, dict(user_state))

    config = MagicMock()
    notion = AsyncMock()

    await _handle_custom_date_input(message, "05.02", user_state, config, notion, memory_state)

    message.bot.delete_message.assert_called_with(
        chat_id=message.chat.id,
        message_id=333,
    )
    assert memory_state.get(message.chat.id, message.from_user.id).get("prompt_message_id") is None


@pytest.mark.asyncio
async def test_reset_from_model_card():
    memory_state = MemoryState()
    query = _make_query(data="nlp:x:c")
    memory_state.set(query.message.chat.id, query.from_user.id, {
        "flow": "nlp_actions",
        "step": "menu",
        "model_id": "model-1",
        "prompt_message_id": 111,
        "screen_message_id": 222,
    })
    query.message.edit_text.side_effect = Exception("not editable")
    config = MagicMock()
    notion = AsyncMock()
    recent_models = MagicMock()

    await handle_nlp_callback(query, config, notion, memory_state, recent_models)

    assert memory_state.get(query.message.chat.id, query.from_user.id) is None
    query.bot.edit_message_reply_markup.assert_called_once_with(
        chat_id=query.message.chat.id,
        message_id=query.message.message_id,
        reply_markup=None,
    )
