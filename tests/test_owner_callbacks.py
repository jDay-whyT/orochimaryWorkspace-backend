"""Owner-only wml/salary callback buttons: authorization guard, double-tap lock, success and error paths.

These handlers perform Notion/Sheets writes and previously had no identity
check of their own — see app.utils.telegram.is_owner_callback. Non-owner
presses must be rejected before any side effect runs.
"""
import zoneinfo
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.handlers import salary_callbacks, wml_callbacks
from app.services.salary_report import ModelSalaryRow
from app.utils import locks as locks_module

OWNER_ID = 111
OTHER_ID = 222


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


# ---------- success / error paths of the same callbacks ----------

def _config(**overrides):
    cfg = MagicMock()
    cfg.owner_telegram_id = OWNER_ID
    cfg.wml_username = "wml_user"
    cfg.wml_password = "wml_pass"
    cfg.db_models = "db_models_id"
    cfg.timezone = zoneinfo.ZoneInfo("Europe/Brussels")
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _query(data: str):
    query = MagicMock()
    query.from_user = MagicMock()
    query.from_user.id = OWNER_ID
    query.data = data
    query.answer = AsyncMock()
    query.message = MagicMock()
    query.message.edit_text = AsyncMock()
    return query


def _wml_detail(**overrides):
    detail = MagicMock()
    detail.wml_name = "Test Model"
    detail.office = None
    detail.scout = None
    detail.language = None
    detail.location = None
    detail.comment = None
    detail.tg_content_manager = None
    detail.model_telegram = None
    for k, v in overrides.items():
        setattr(detail, k, v)
    return detail


def _last_message_text(query) -> str:
    return query.message.edit_text.call_args[0][0]


class TestWmlAdd:
    @pytest.mark.asyncio
    async def test_missing_wml_credentials(self):
        notion = MagicMock()
        query = _query("wml_add:123:0:di")
        await wml_callbacks.cb_wml_add(query, _config(wml_username=""), notion)
        assert "не налаштовані" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_wml_fetch_error_reported_to_user(self, monkeypatch):
        def _raise(*a, **k):
            raise RuntimeError("connection refused")
        monkeypatch.setattr(wml_callbacks, "fetch_profile_by_id", _raise)
        notion = MagicMock()
        query = _query("wml_add:123:0:di")
        await wml_callbacks.cb_wml_add(query, _config(), notion)
        assert "Не вдалось отримати дані" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_profile_not_found_on_wml(self, monkeypatch):
        monkeypatch.setattr(wml_callbacks, "fetch_profile_by_id", lambda *a, **k: _wml_detail(wml_name=""))
        notion = MagicMock()
        query = _query("wml_add:123:0:di")
        await wml_callbacks.cb_wml_add(query, _config(), notion)
        assert "не знайдено на WML" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_excluded_profile_ii_suffix(self, monkeypatch):
        monkeypatch.setattr(wml_callbacks, "fetch_profile_by_id", lambda *a, **k: _wml_detail(wml_name="Test ИИ_1234"))
        notion = MagicMock()
        query = _query("wml_add:123:0:di")
        await wml_callbacks.cb_wml_add(query, _config(), notion)
        assert "виключено" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_already_in_notion(self, monkeypatch):
        monkeypatch.setattr(wml_callbacks, "fetch_profile_by_id", lambda *a, **k: _wml_detail())
        notion = MagicMock()
        existing = MagicMock(title="Test Model")
        notion.query_all_models = AsyncMock(return_value=[existing])
        notion.create_model_from_wml = AsyncMock()
        query = _query("wml_add:123:0:di")
        await wml_callbacks.cb_wml_add(query, _config(), notion)
        assert "вже є в Notion" in _last_message_text(query)
        notion.create_model_from_wml.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_add_with_tango_date_defaults_project(self, monkeypatch):
        monkeypatch.setattr(
            wml_callbacks, "fetch_profile_by_id",
            lambda *a, **k: _wml_detail(scout="Scout1", tg_content_manager="@cm", model_telegram="@model"),
        )
        notion = MagicMock()
        notion.query_all_models = AsyncMock(return_value=[])
        notion.create_model_from_wml = AsyncMock()
        notion.create_new_model_accounting = AsyncMock()
        query = _query("wml_add:123:1:di")  # has_tango_date=True
        await wml_callbacks.cb_wml_add(query, _config(), notion)

        notion.create_model_from_wml.assert_awaited_once()
        _, kwargs = notion.create_model_from_wml.call_args
        assert kwargs["project"] == "TANGO"
        assert kwargs["scoutname"] == "scout1"
        text = _last_message_text(query)
        assert "додано в Notion" in text
        assert "@cm" in text and "@model" in text

    @pytest.mark.asyncio
    async def test_lock_released_even_on_exception(self, monkeypatch):
        monkeypatch.setattr(wml_callbacks, "fetch_profile_by_id", lambda *a, **k: _wml_detail())
        notion = MagicMock()
        notion.query_all_models = AsyncMock(side_effect=RuntimeError("notion down"))
        query = _query("wml_add:999:0:di")
        with pytest.raises(RuntimeError):
            await wml_callbacks.cb_wml_add(query, _config(), notion)
        # Lock must be released in `finally` despite the uncaught exception.
        assert await locks_module.try_acquire_write_lock(None, "wml_add_lock:999")


class TestWmlReject:
    @pytest.mark.asyncio
    async def test_reject_edits_message(self):
        query = _query("wml_reject:123")
        await wml_callbacks.cb_wml_reject(query, _config())
        assert "Відхилено" in _last_message_text(query)


def _redis_mock(cached_row: ModelSalaryRow | None = None):
    """A Redis mock whose `.set` (used by the write lock) always succeeds."""
    import dataclasses as _dc
    import json as _json
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock()
    redis.get = AsyncMock(return_value=_json.dumps(_dc.asdict(cached_row)) if cached_row else None)
    return redis


def _row(model_id="id-1", manager="Рони", model_name="Модель", orders_pay=0):
    return ModelSalaryRow(
        model_id=model_id, model_name=model_name, manager=manager,
        status="work", content=[], total_files=0, custom_count=0,
        other_count=0, orders_pay=orders_pay,
    )


class TestSalaryAdd:
    @pytest.mark.asyncio
    async def test_sheets_not_configured(self):
        notion = MagicMock()
        query = _query("salary_add:2026-07:id-1")
        await salary_callbacks.cb_salary_add(query, _config(salary_sheet_id=""), notion, None)
        assert "не настроен" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_load_row_failure_reported(self):
        notion = MagicMock()
        notion.query_all_accounting = AsyncMock(side_effect=RuntimeError("notion timeout"))
        sheets = MagicMock()
        query = _query("salary_add:2026-07:id-1")
        await salary_callbacks.cb_salary_add(query, _config(salary_sheet_id="sid"), notion, sheets)
        assert "Не удалось получить данные" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_row_no_longer_in_report(self):
        redis = _redis_mock()
        notion = MagicMock()
        notion.query_all_accounting = AsyncMock(return_value=[])
        notion.query_orders_closed_in_month = AsyncMock(return_value=[])
        notion.query_all_models = AsyncMock(return_value=[])
        sheets = MagicMock()
        query = _query("salary_add:2026-07:id-1")
        await salary_callbacks.cb_salary_add(query, _config(salary_sheet_id="sid"), notion, sheets, redis)
        assert "больше не найдена" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_sheets_insert_failure_reported(self):
        redis = _redis_mock(cached_row=_row())
        notion = MagicMock()
        sheets = MagicMock()
        sheets.get_sheet_tabs = AsyncMock(side_effect=RuntimeError("sheets down"))
        query = _query("salary_add:2026-07:id-1")
        await salary_callbacks.cb_salary_add(query, _config(salary_sheet_id="sid"), notion, sheets, redis)
        assert "Не удалось записать" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_manager_block_missing_reports_manual_add(self):
        redis = _redis_mock(cached_row=_row(manager="НетТакого"))
        notion = MagicMock()
        sheets = MagicMock()
        sheets.get_sheet_tabs = AsyncMock(return_value={"ИЮЛЬ": 999})
        sheets.get_tab_grid = AsyncMock(return_value=[["Модель"], ["Рони"]])
        query = _query("salary_add:2026-07:id-1")
        await salary_callbacks.cb_salary_add(query, _config(salary_sheet_id="sid"), notion, sheets, redis)
        assert "не найден в табе" in _last_message_text(query)

    @pytest.mark.asyncio
    async def test_successful_insert_deletes_cache_key(self, monkeypatch):
        redis = _redis_mock(cached_row=_row(manager="Рони", model_name="Новая", orders_pay=5))
        notion = MagicMock()
        sheets = MagicMock()
        sheets.get_sheet_tabs = AsyncMock(return_value={"ИЮЛЬ": 999})
        sheets.get_tab_grid = AsyncMock(return_value=[["Модель"], ["Рони"]])
        monkeypatch.setattr(salary_callbacks, "insert_new_model_row", AsyncMock(return_value=4))
        query = _query("salary_add:2026-07:id-1")
        await salary_callbacks.cb_salary_add(query, _config(salary_sheet_id="sid"), notion, sheets, redis)
        text = _last_message_text(query)
        assert "добавлена в таб" in text
        # redis.delete is called twice: once for the pending-row cache key,
        # once by the write lock's release in `finally` — check the cache key specifically.
        from app.services.salary_report import salary_pending_redis_key
        redis.delete.assert_any_await(salary_pending_redis_key("2026-07", "id-1"))

    @pytest.mark.asyncio
    async def test_lock_released_even_on_exception(self):
        notion = MagicMock()
        notion.query_all_accounting = AsyncMock(side_effect=RuntimeError("boom"))
        query = _query("salary_add:2026-07:id-err")
        await salary_callbacks.cb_salary_add(query, _config(salary_sheet_id="sid"), notion, MagicMock())
        assert await locks_module.try_acquire_write_lock(None, "salary_add_lock:2026-07:id-err")


class TestSalaryReject:
    @pytest.mark.asyncio
    async def test_reject_edits_message(self):
        query = _query("salary_reject:2026-07:id-1")
        await salary_callbacks.cb_salary_reject(query, _config())
        assert "Отклонено" in _last_message_text(query)
