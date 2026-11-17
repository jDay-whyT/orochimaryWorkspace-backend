"""Owner-only gates: a non-owner reaches no Notion / CRM / Sheets call through destructive owner commands and buttons."""
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.handlers import accounting_rename, reports, tango, wml_export_cmd

OWNER_ID = 111
OTHER_ID = 222

# (handler, kind, module, module functions that reach Notion / CRM / Sheets and must stay untouched)
CASES = [
    pytest.param(accounting_rename.cb_close_month, "callback", accounting_rename,
                 ("pick_files", "send_files", "WmlApi", "plan_close"), id="cb_close_month"),
    pytest.param(accounting_rename.cmd_rename_month, "command", accounting_rename,
                 ("plan_close",), id="cmd_rename_month"),
    pytest.param(reports.cmd_reports, "command", reports,
                 ("load_salary_accounting", "write_salary_report"), id="cmd_reports"),
    pytest.param(tango.cmd_tango, "command", tango, (), id="cmd_tango"),
    pytest.param(wml_export_cmd.cmd_wml_test_orders, "command", wml_export_cmd,
                 ("pick_month_orders",), id="cmd_wml_test_orders"),
    pytest.param(wml_export_cmd.cmd_wml_test_files, "command", wml_export_cmd,
                 ("pick_files",), id="cmd_wml_test_files"),
    pytest.param(wml_export_cmd.cb_wml_orders_send, "callback", wml_export_cmd,
                 ("pick_month_orders", "send_orders", "WmlApi"), id="cb_wml_orders_send"),
    pytest.param(wml_export_cmd.cb_wml_files_send, "callback", wml_export_cmd,
                 ("pick_files", "send_files", "WmlApi"), id="cb_wml_files_send"),
]


def _config():
    return SimpleNamespace(
        owner_telegram_id=OWNER_ID, timezone=ZoneInfo("UTC"), salary_sheet_id="sheet", sheet_id="sheet", sheet_tab_name="tab",
        db_orders="o", db_models="m", db_accounting="a", wml_username="u", wml_password="p",
    )


def _message():
    message = MagicMock()
    message.chat.type = "private"
    message.from_user.id = OTHER_ID
    message.answer = AsyncMock()
    return message


def _query():
    query = MagicMock()
    query.from_user.id = OTHER_ID
    query.data = "close_month:2026-10"
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()
    return query


@pytest.mark.asyncio
@pytest.mark.parametrize("handler, kind, module, reachers", CASES)
async def test_non_owner_reaches_no_notion_crm_or_sheets(monkeypatch, handler, kind, module, reachers):
    guarded = {name: AsyncMock() for name in reachers}
    for name, mock in guarded.items():
        monkeypatch.setattr(module, name, mock)
    notion, sheets, redis = AsyncMock(), AsyncMock(), AsyncMock()
    command = SimpleNamespace(args="2026-10")

    if kind == "callback":
        await handler(_query(), _config(), notion, redis)
    else:
        params = handler.__code__.co_varnames[:handler.__code__.co_argcount]
        available = {"message": _message(), "command": command, "config": _config(), "notion": notion,
                     "sheets": sheets, "redis": redis}
        await handler(*(available[p] for p in params))

    assert notion.mock_calls == [] and sheets.mock_calls == [] and redis.mock_calls == []
    for name, mock in guarded.items():
        mock.assert_not_called()
