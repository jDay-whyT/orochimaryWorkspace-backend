import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

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
        "content_type": "reddit",
        "screen_message_id": 111,
        "prompt_message_id": 222,
    }
    memory_state.set(message.chat.id, message.from_user.id, dict(user_state))

    from zoneinfo import ZoneInfo
    config = MagicMock()
    config.files_per_month = 200
    config.timezone = ZoneInfo("UTC")
    config.allowed_editors = {1}
    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(files=0, page_id="acc-1", status=None)

    await _handle_custom_files_input(message, "5", user_state, config, notion, memory_state)

    message.bot.edit_message_reply_markup.assert_called_with(
        chat_id=message.chat.id,
        message_id=111,
        reply_markup=None,
    )


@pytest.mark.asyncio
async def test_custom_files_input_updates_recent_models():
    """Typing the file count (instead of tapping a quick-count button) must
    still update the recent-models shortcut, same as the button path."""
    memory_state = MemoryState()
    message = _make_message(text="5")
    user_state = {
        "flow": "nlp_files",
        "step": "awaiting_count",
        "model_id": "model-1",
        "model_name": "Model",
        "content_type": "reddit",
    }
    memory_state.set(message.chat.id, message.from_user.id, dict(user_state))

    from zoneinfo import ZoneInfo
    config = MagicMock()
    config.files_per_month = 200
    config.timezone = ZoneInfo("UTC")
    config.allowed_editors = {1}
    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(files=0, page_id="acc-1", status=None)
    recent_models = MagicMock()

    await _handle_custom_files_input(message, "5", user_state, config, notion, memory_state, recent_models)

    recent_models.add.assert_called_once_with(1, "model-1", "Model")


@pytest.mark.asyncio
async def test_new_shoot_comment_input_updates_recent_models():
    """Typing a comment (instead of tapping Skip) must still update the
    recent-models shortcut, same as the Skip path."""
    from app.router import dispatcher
    from zoneinfo import ZoneInfo

    memory_state = MemoryState()
    message = _make_message(text="bring lights")
    user_state = {
        "flow": "nlp_shoot",
        "step": "awaiting_new_shoot_comment",
        "model_id": "model-1",
        "model_name": "Model",
        "shoot_date": None,
        "content_types": [],
        "location": "home",
    }
    memory_state.set(message.chat.id, message.from_user.id, dict(user_state))
    config = MagicMock()
    config.allowed_editors = {1}
    config.timezone = ZoneInfo("UTC")
    notion = AsyncMock()
    recent_models = MagicMock()

    await dispatcher._handle_new_shoot_comment_input(
        message, "bring lights", user_state, config, notion, memory_state, recent_models,
    )

    recent_models.add.assert_called_once_with(1, "model-1", "Model")


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
    config.allowed_editors = {1}
    config.timezone = ZoneInfo("Europe/Brussels")
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


@pytest.mark.asyncio
async def test_more_actions_double_tap_sends_only_one_card():
    """"Ещё действие" sends a NEW message instead of editing the current
    screen, so it isn't naturally idempotent like other buttons — a double
    tap (two distinct callback queries on the same rendered message, as
    Telegram delivers a real double tap) must still produce only one model
    card, not two.
    """
    from app.handlers import nlp_callbacks
    nlp_callbacks._recently_advanced.clear()
    nlp_callbacks._callback_dedup.clear()

    # The one real Telegram message both taps land on.
    message = MagicMock()
    message.chat.id = 100
    message.message_id = 200
    message.edit_reply_markup = AsyncMock()
    message.answer = AsyncMock(return_value=MagicMock(message_id=999))

    def _tap(cb_id):
        query = MagicMock()
        query.id = cb_id
        query.from_user.id = 1
        query.data = "nlp:more_actions:model-1"
        query.answer = AsyncMock()
        query.message = message
        query.bot = AsyncMock()
        return query

    memory_state = MemoryState()
    memory_state.set(100, 1, {
        "flow": "nlp_actions",
        "model_id": "model-1",
        "model_name": "Model",
    })
    config = MagicMock()
    notion = AsyncMock()
    notion.get_model.return_value = MagicMock(title="Model")
    recent_models = MagicMock()

    with patch("app.services.model_card.build_model_card", new=AsyncMock(return_value=("CARD", 0))):
        await handle_nlp_callback(_tap("cbq-1"), config, notion, memory_state, recent_models)
        await handle_nlp_callback(_tap("cbq-2"), config, notion, memory_state, recent_models)

    assert message.answer.call_count == 1, \
        "a double tap on 'more_actions' must not send a second model card"


# ---------- add files: type first, then amount ----------

def _files_query(data, user_id=1):
    from types import SimpleNamespace
    q = MagicMock()
    q.data = data
    q.from_user = SimpleNamespace(id=user_id, username="m", full_name="M")
    q.message = MagicMock()
    q.message.chat.id = 100
    q.message.message_id = 111
    q.answer = AsyncMock()
    return q


@pytest.mark.asyncio
async def test_request_kind_counts_in_request_files_and_tags_the_kind(monkeypatch):
    from zoneinfo import ZoneInfo
    from app.handlers import nlp_callbacks as nc

    config = MagicMock()
    config.timezone = ZoneInfo("UTC")
    config.allowed_editors = {1}
    notion = AsyncMock()
    record = MagicMock(page_id="acc-1", request_files=5)
    notion.get_monthly_record.return_value = record

    text = await nc.save_files(config, notion, _files_query("x").from_user, "m-1", "Model", 10, "pornhub")
    notion.update_accounting_files_by_type.assert_awaited_with("acc-1", "request_files", 15)
    notion.add_to_accounting_content.assert_awaited_with("acc-1", "pornhub")
    assert "+<b>10</b> Pornhub · Request total <b>15</b>" in text


@pytest.mark.asyncio
async def test_plain_of_adds_no_content_tag():
    from zoneinfo import ZoneInfo
    from app.handlers import nlp_callbacks as nc

    config = MagicMock()
    config.timezone = ZoneInfo("UTC")
    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(page_id="acc-1", of_files=40)
    await nc.save_files(config, notion, _files_query("x").from_user, "m-1", "Model", 20, "of")
    notion.update_accounting_files_by_type.assert_awaited_with("acc-1", "of_files", 60)
    notion.add_to_accounting_content.assert_not_awaited()


def test_files_type_menu_matches_notion_columns():
    from app.keyboards.inline import nlp_files_content_type_keyboard, nlp_files_request_type_keyboard
    from app.utils.content_mapping import get_field_for_content_type

    top = [b.callback_data.split(":")[2] for row in nlp_files_content_type_keyboard("m").inline_keyboard for b in row
           if b.callback_data.startswith("nlp:fct:")]
    assert top == ["of", "reddit", "twitter", "fansly", "req"]
    kinds = [b.callback_data.split(":")[2] for row in nlp_files_request_type_keyboard().inline_keyboard for b in row
             if b.callback_data not in ("nlp:fct:back",)]
    assert kinds == ["pornhub", "instagram", "snapchat", "event", "sfs", "request"]
    assert all(get_field_for_content_type(k) == "request_files" for k in kinds)
