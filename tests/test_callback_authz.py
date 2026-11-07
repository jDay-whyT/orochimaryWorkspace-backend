"""Owner-only authorization guard on wml/salary callback buttons.

These handlers perform Notion/Sheets writes and previously had no identity
check of their own — see app.utils.telegram.is_owner_callback. Non-owner
presses must be rejected before any side effect runs.
"""
import zoneinfo
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.handlers import salary_callbacks, wml_callbacks
from app.utils import locks as locks_module

OWNER_ID = 111
OTHER_ID = 222


@pytest.fixture(autouse=True)
def _clear_in_memory_locks():
    locks_module._in_flight_locks.clear()
    yield
    locks_module._in_flight_locks.clear()


def _make_config(owner_telegram_id: int = OWNER_ID):
    cfg = MagicMock()
    cfg.owner_telegram_id = owner_telegram_id
    cfg.timezone = zoneinfo.ZoneInfo("Europe/Brussels")
    return cfg


def _make_query(user_id: int, data: str):
    query = MagicMock()
    query.from_user = MagicMock()
    query.from_user.id = user_id
    query.data = data
    query.answer = AsyncMock()
    query.message = MagicMock()
    query.message.edit_text = AsyncMock()
    return query


@pytest.mark.asyncio
async def test_wml_add_rejects_non_owner():
    notion = MagicMock()
    notion.query_all_models = AsyncMock()
    query = _make_query(OTHER_ID, "wml_add:123")
    await wml_callbacks.cb_wml_add(query, _make_config(), notion)
    notion.query_all_models.assert_not_called()


@pytest.mark.asyncio
async def test_wml_reject_rejects_non_owner():
    query = _make_query(OTHER_ID, "wml_reject:123")
    await wml_callbacks.cb_wml_reject(query, _make_config())
    query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_salary_add_rejects_non_owner():
    notion = MagicMock()
    sheets = MagicMock()
    sheets.get_sheet_tabs = AsyncMock()
    query = _make_query(OTHER_ID, "salary_add:2026-07:abc")
    await salary_callbacks.cb_salary_add(query, _make_config(), notion, sheets)
    sheets.get_sheet_tabs.assert_not_called()


@pytest.mark.asyncio
async def test_salary_reject_rejects_non_owner():
    query = _make_query(OTHER_ID, "salary_reject:2026-07:abc")
    await salary_callbacks.cb_salary_reject(query, _make_config())
    query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_salary_add_malformed_data_answers_without_crash():
    notion = MagicMock()
    sheets = MagicMock()
    query = _make_query(OWNER_ID, "salary_add:onlyonepart")
    await salary_callbacks.cb_salary_add(query, _make_config(), notion, sheets)
    query.answer.assert_called()


@pytest.mark.asyncio
async def test_wml_add_second_concurrent_tap_is_blocked():
    """A second tap while the first is still holding the lock must not touch Notion."""
    assert await locks_module.try_acquire_write_lock(None, "wml_add_lock:123")

    notion = MagicMock()
    notion.query_all_models = AsyncMock()
    query = _make_query(OWNER_ID, "wml_add:123:0:di")
    await wml_callbacks.cb_wml_add(query, _make_config(), notion)

    notion.query_all_models.assert_not_called()
    query.answer.assert_any_call("⏳ Вже додається...", show_alert=True)


@pytest.mark.asyncio
async def test_salary_add_second_concurrent_tap_is_blocked():
    assert await locks_module.try_acquire_write_lock(None, "salary_add_lock:2026-07:abc")

    notion = MagicMock()
    sheets = MagicMock()
    sheets.get_sheet_tabs = AsyncMock()
    query = _make_query(OWNER_ID, "salary_add:2026-07:abc")
    await salary_callbacks.cb_salary_add(query, _make_config(), notion, sheets)

    sheets.get_sheet_tabs.assert_not_called()
    query.answer.assert_any_call("⏳ Уже добавляется...", show_alert=True)


@pytest.mark.asyncio
async def test_wml_add_lock_released_after_success_allows_retry():
    """Once a run completes, the lock must be released so a legitimate retry can proceed."""
    notion = MagicMock()
    notion.query_all_models = AsyncMock(return_value=[])
    notion.create_model_from_wml = AsyncMock(return_value="model-page")
    notion.create_new_model_accounting = AsyncMock()
    query = _make_query(OWNER_ID, "wml_add:123:0:di")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            wml_callbacks, "fetch_profile_by_id",
            lambda *a, **k: MagicMock(wml_name="Test Model", office=None, scout=None,
                                       language=None, location=None, comment=None,
                                       tg_content_manager=None, model_telegram=None),
        )
        await wml_callbacks.cb_wml_add(query, _make_config(), notion)

    # Lock released — a second, independent call for the same wml_id must proceed again.
    assert await locks_module.try_acquire_write_lock(None, "wml_add_lock:123")


def _profile():
    return MagicMock(wml_name="Test Model", office=None, scout=None, language=None,
                     location=None, comment=None, tg_content_manager=None, model_telegram=None)


@pytest.mark.asyncio
async def test_wml_add_card_button_shows_manager_picker_without_writes():
    notion = MagicMock()
    notion.get_select_options = AsyncMock(return_value=["caramel", "di"])
    notion.create_model_from_wml = AsyncMock()
    query = _make_query(OWNER_ID, "wml_add:123:1")
    await wml_callbacks.cb_wml_add(query, _make_config(), notion)

    notion.create_model_from_wml.assert_not_called()
    markup = query.message.edit_text.call_args.kwargs["reply_markup"]
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert data == ["wml_add:123:1:caramel", "wml_add:123:1:di", "wml_add:123:1:-", "wml_reject:123"]


@pytest.mark.asyncio
@pytest.mark.parametrize("picked, expected", [("di", "di"), ("-", None)])
async def test_wml_add_creates_model_and_accounting_with_manager(picked, expected):
    cfg = _make_config()
    notion = MagicMock()
    notion.query_all_models = AsyncMock(return_value=[])
    notion.create_model_from_wml = AsyncMock(return_value="model-page")
    notion.create_new_model_accounting = AsyncMock()
    query = _make_query(OWNER_ID, f"wml_add:123:0:{picked}")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wml_callbacks, "fetch_profile_by_id", lambda *a, **k: _profile())
        mp.setattr("app.handlers.models.invalidate", AsyncMock())
        await wml_callbacks.cb_wml_add(query, cfg, notion)

    args, kwargs = notion.create_new_model_accounting.call_args
    assert args[1:3] == ("model-page", "Test Model")
    assert kwargs["assist"] == expected
