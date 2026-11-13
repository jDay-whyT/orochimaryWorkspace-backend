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
async def test_custom_files_input_asks_confirmation_without_saving():
    """Typing the file count must only show the confirmation screen."""
    memory_state = MemoryState()
    message = _make_message(text="5")
    user_state = {
        "flow": "nlp_files",
        "step": "awaiting_count",
        "model_id": "model-1",
        "model_name": "Model",
        "content_type": "reddit",
        "k": "abc123",
    }
    memory_state.set(message.chat.id, message.from_user.id, dict(user_state))

    config = MagicMock()
    config.files_per_month = 200
    config.timezone = ZoneInfo("UTC")
    config.allowed_editors = {1}
    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(reddit_files=10, page_id="acc-1", status=None)
    recent_models = MagicMock()

    await _handle_custom_files_input(message, "5", user_state, config, notion, memory_state, recent_models)

    notion.update_accounting_files_by_type.assert_not_called()
    notion.create_accounting_record.assert_not_called()
    recent_models.add.assert_not_called()
    state = memory_state.get(message.chat.id, message.from_user.id)
    assert state["step"] == "awaiting_confirm"
    assert state["pending_count"] == 5
    kb = message.answer.call_args.kwargs["reply_markup"]
    assert [b.callback_data for b in kb.inline_keyboard[0]] == ["nlp:afc:yes:abc123", "nlp:afc:no:abc123"]


@pytest.mark.asyncio
async def test_files_confirm_yes_saves_and_updates_recent_models():
    """«Yes, add» writes the pending amount and updates the recent-models shortcut."""
    from app.handlers.nlp_callbacks import _handle_files_confirm

    memory_state = MemoryState()
    query = _make_query(data="nlp:afc:yes:abc123")
    memory_state.set(query.message.chat.id, query.from_user.id, {
        "flow": "nlp_files",
        "step": "awaiting_confirm",
        "model_id": "model-1",
        "model_name": "Model",
        "content_type": "reddit",
        "pending_count": 5,
        "k": "abc123",
    })
    config = MagicMock()
    config.timezone = ZoneInfo("UTC")
    config.allowed_editors = {1}
    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(page_id="acc-1", status=None)
    notion.get_page.return_value = {"properties": {"request_files": {"number": 0}, "of_files": {"number": 0}}}
    recent_models = MagicMock()

    await _handle_files_confirm(query, ["nlp", "afc", "yes", "abc123"], config, notion, memory_state, recent_models)

    notion.update_accounting_files_by_type.assert_called_once()
    assert notion.update_accounting_files_by_type.call_args.args[2] >= 5
    recent_models.add.assert_called_once_with(1, "model-1", "Model")
    assert memory_state.get(query.message.chat.id, query.from_user.id) in (None, {})


@pytest.mark.asyncio
async def test_files_confirm_no_does_not_save():
    """«Cancel» returns to the amount screen and writes nothing."""
    from app.handlers.nlp_callbacks import _handle_files_confirm

    memory_state = MemoryState()
    query = _make_query(data="nlp:afc:no:abc123")
    memory_state.set(query.message.chat.id, query.from_user.id, {
        "flow": "nlp_files",
        "step": "awaiting_confirm",
        "model_id": "model-1",
        "model_name": "Model",
        "content_type": "reddit",
        "pending_count": 5,
        "k": "abc123",
    })
    config = MagicMock()
    config.allowed_editors = {1}
    notion = AsyncMock()

    await _handle_files_confirm(query, ["nlp", "afc", "no", "abc123"], config, notion, memory_state, MagicMock())

    notion.update_accounting_files_by_type.assert_not_called()
    notion.create_accounting_record.assert_not_called()
    state = memory_state.get(query.message.chat.id, query.from_user.id)
    assert state["step"] == "awaiting_amount"


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
    notion.get_page.return_value = {"properties": {"request_files": {"number": 5}}}

    text = await nc.save_files(config, notion, _files_query("x").from_user, "m-1", "Model", 10, "pornhub")
    notion.update_accounting_files_by_type.assert_awaited_with("acc-1", "request_files", 15)
    notion.add_to_accounting_content.assert_awaited_with("acc-1", "pornhub")
    assert "+<b>10</b> Pornhub · Request total <b>15</b>" in text


@pytest.mark.asyncio
async def test_plain_of_adds_new_main_content_tag():
    from zoneinfo import ZoneInfo
    from app.handlers import nlp_callbacks as nc

    config = MagicMock()
    config.timezone = ZoneInfo("UTC")
    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(page_id="acc-1", of_files=40)
    notion.get_page.return_value = {"properties": {"of_files": {"number": 40}}}
    await nc.save_files(config, notion, _files_query("x").from_user, "m-1", "Model", 20, "of")
    notion.update_accounting_files_by_type.assert_awaited_with("acc-1", "of_files", 60)
    notion.add_to_accounting_content.assert_awaited_with("acc-1", "new_main")


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


# ---------- regression: lost updates, stale object buttons, datetime in_date ----------

def _cfg(editors=frozenset({1})):
    config = MagicMock()
    config.timezone = ZoneInfo("UTC")
    config.allowed_editors = set(editors)
    return config


class _FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)


@pytest.mark.asyncio
async def test_concurrent_file_adds_are_serialized_and_read_fresh_total():
    """Two adds at once: both land (5 -> 10) because the total is re-read inside the lock."""
    import asyncio
    from app.handlers import nlp_callbacks as nc

    page = {"properties": {"reddit_files": {"number": 5}}}

    async def get_page(_id):
        await asyncio.sleep(0.01)
        return {"properties": {"reddit_files": {"number": page["properties"]["reddit_files"]["number"]}}}

    async def update(_id, field, value):
        await asyncio.sleep(0.01)
        page["properties"][field] = {"number": value}

    notion = AsyncMock()
    notion.get_monthly_record.return_value = MagicMock(page_id="acc-1")
    notion.get_page.side_effect = get_page
    notion.update_accounting_files_by_type.side_effect = update
    user = MagicMock(id=1)
    for redis in (None, _FakeRedis()):
        page["properties"]["reddit_files"] = {"number": 5}
        await asyncio.gather(
            nc.save_files(_cfg(), notion, user, "m-1", "Model", 3, "reddit", redis=redis),
            nc.save_files(_cfg(), notion, user, "m-1", "Model", 2, "reddit", redis=redis),
        )
        assert page["properties"]["reddit_files"]["number"] == 10


@pytest.mark.asyncio
async def test_no_record_yet_creates_once_then_reuses_created_page():
    """The query lags: a second add right after the first must not create a second record."""
    from app.handlers import nlp_callbacks as nc

    redis = _FakeRedis()
    notion = AsyncMock()
    notion.get_monthly_record.return_value = None  # the lagging query never sees it
    notion.create_accounting_record.return_value = "new-page"
    notion.get_page.return_value = {"properties": {"reddit_files": {"number": 4}}}
    user = MagicMock(id=1)
    await nc.save_files(_cfg(), notion, user, "m-1", "Model", 4, "reddit", redis=redis)
    await nc.save_files(_cfg(), notion, user, "m-1", "Model", 1, "reddit", redis=redis)
    assert notion.create_accounting_record.await_count == 1
    notion.update_accounting_files_by_type.assert_awaited_with("new-page", "reddit_files", 5)


@pytest.mark.asyncio
async def test_model_lock_busy_raises_when_held():
    from app.utils.locks import ModelBusy, model_write_lock

    redis = _FakeRedis()
    redis.data["lock:model:m-busy"] = "someone"
    with pytest.raises(ModelBusy):
        async with model_write_lock(redis, "m-busy", wait=0.3):
            pass


@pytest.mark.asyncio
async def test_apply_received_reads_current_value_fresh():
    from app.handlers.nlp_callbacks import apply_received

    notion = AsyncMock()
    notion.get_page.return_value = {"properties": {"received": {"number": 6}}}
    state = {"order_id": "o1", "count": 10, "current_received": 1, "model_id": "m1", "model_name": "M"}
    text = await apply_received(_cfg(), notion, state, 2)
    notion.update_order_received.assert_awaited_with("o1", 8)
    assert "8/10" in text


@pytest.mark.asyncio
async def test_stale_shoot_close_confirm_does_not_close_other_shoot():
    from app.handlers import nlp_callbacks as nc

    memory = MemoryState()
    memory.set(100, 1, {"flow": "nlp_shoot_menu", "model_id": "m2", "model_name": "B",
                        "shoot_ids": ["s2"], "shoot_id": "s2"})
    notion = AsyncMock()
    query = _make_query(data="nlp:smn:closeok:s1")  # button of the previous model's shoot
    await nc._handle_shoot_menu_action(query, ["nlp", "smn", "closeok", "s1"], _cfg(), notion, memory, MagicMock())
    notion.update_shoot_status.assert_not_awaited()
    assert memory.get(100, 1) in (None, {})


def test_shoot_buttons_carry_object_ids_within_64_bytes():
    from app.keyboards.inline import (
        nlp_received_keyboard, nlp_shoot_done_confirm_keyboard, nlp_shoot_edit_keyboard, nlp_shoot_menu_keyboard,
    )
    nid = "12345678-1234-1234-1234-123456789012"
    kbs = [
        nlp_shoot_done_confirm_keyboard(nid), nlp_shoot_edit_keyboard(True, nid),
        nlp_shoot_menu_keyboard(True, nid, picks=["a", "b"]), nlp_received_keyboard(300, nid, nid),
    ]
    data = [b.callback_data for kb in kbs for row in kb.inline_keyboard for b in row]
    assert max(len(d.encode()) for d in data) <= 64
    assert f"nlp:smn:closeok:{nid}" in data and f"nlp:prq:300:{nid}" in data


@pytest.mark.asyncio
async def test_stale_add_part_tap_of_other_order_is_rejected():
    from app.handlers import nlp_callbacks as nc

    memory = MemoryState()
    memory.set(100, 1, {"flow": "nlp_received", "order_id": "o-new", "count": 8, "current_received": 0,
                        "model_id": "m1", "model_name": "M"})
    notion = AsyncMock()
    query = _make_query(data="nlp:prq:2:o-old")
    await nc._handle_received_quick(query, ["nlp", "prq", "2", "o-old"], _cfg(), notion, memory)
    notion.get_page.assert_not_awaited()
    notion.update_order_received.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_close_fully_tap_of_other_order_is_rejected():
    from app.handlers import nlp_callbacks as nc

    memory = MemoryState()
    memory.set(100, 1, {"flow": "nlp_close", "step": "short_options", "order_id": "o-new",
                        "order_type": "short", "count": 8, "model_id": "m1", "model_name": "M"})
    query = _make_query(data="nlp:cd:o-old")
    await nc._handle_close_date(query, ["nlp", "cd", "o-old"], _cfg(), AsyncMock(), memory)
    state = memory.get(100, 1)
    assert not state or state.get("order_id") != "o-old"


@pytest.mark.asyncio
async def test_close_order_with_datetime_in_date_still_confirms(monkeypatch):
    from app.handlers import nlp_callbacks as nc

    confirm = AsyncMock()
    monkeypatch.setattr(nc, "_safe_confirm", confirm)
    monkeypatch.setattr(nc, "_clear_previous_screen_keyboard", AsyncMock())
    monkeypatch.setattr(nc, "_cleanup_prompt_message", AsyncMock())
    memory = MemoryState()
    memory.set(100, 1, {"flow": "nlp_close", "step": "awaiting_date", "order_id": "o1", "order_type": "of",
                        "model_id": "m1", "model_name": "M", "in_date": "2026-10-01T10:00:00.000+03:00"})
    notion = AsyncMock()
    query = _make_query(data="nlp:cd:today")
    await nc._handle_close_date(query, ["nlp", "cd", "today"], _cfg(), notion, memory)
    notion.close_order.assert_awaited_once()
    assert "Order closed" in confirm.await_args.args[1]
    assert " d</b>" in confirm.await_args.args[1]
