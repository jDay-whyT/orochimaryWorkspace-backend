from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import Config
from app.state import MemoryState, RecentModels


@pytest.fixture
def config_admin() -> Config:
    return Config(
        telegram_bot_token="token",
        telegram_webhook_secret="secret",
        notion_token="notion",
        db_models="11111111-1111-1111-1111-111111111111",
        db_orders="22222222-2222-2222-2222-222222222222",
        db_planner="33333333-3333-3333-3333-333333333333",
        db_accounting="44444444-4444-4444-4444-444444444444",
        admin_ids={111},
        editor_ids=set(),
        viewer_ids=set(),
        timezone=ZoneInfo("UTC"),
        files_per_month=180,
    )


@pytest.fixture
def config_viewer() -> Config:
    return Config(
        telegram_bot_token="token",
        telegram_webhook_secret="secret",
        notion_token="notion",
        db_models="11111111-1111-1111-1111-111111111111",
        db_orders="22222222-2222-2222-2222-222222222222",
        db_planner="33333333-3333-3333-3333-333333333333",
        db_accounting="44444444-4444-4444-4444-444444444444",
        admin_ids=set(),
        editor_ids=set(),
        viewer_ids={222},
        timezone=ZoneInfo("UTC"),
        files_per_month=180,
    )


@pytest.fixture
def config_denied() -> Config:
    return Config(
        telegram_bot_token="token",
        telegram_webhook_secret="secret",
        notion_token="notion",
        db_models="11111111-1111-1111-1111-111111111111",
        db_orders="22222222-2222-2222-2222-222222222222",
        db_planner="33333333-3333-3333-3333-333333333333",
        db_accounting="44444444-4444-4444-4444-444444444444",
        admin_ids=set(),
        editor_ids=set(),
        viewer_ids=set(),
        timezone=ZoneInfo("UTC"),
        files_per_month=180,
    )


@pytest.fixture
def notion_mock() -> SimpleNamespace:
    return SimpleNamespace(
        query_models=AsyncMock(),
        query_open_orders=AsyncMock(),
        create_order=AsyncMock(),
        update_order=AsyncMock(),
        close_order=AsyncMock(),
        query_accounting_by_month=AsyncMock(),
        get_accounting_record=AsyncMock(),
        create_accounting_record=AsyncMock(),
        update_accounting_files=AsyncMock(),
        update_accounting_content=AsyncMock(),
        update_accounting_comment=AsyncMock(),
        query_upcoming_shoots=AsyncMock(),
        get_shoot=AsyncMock(),
        create_shoot=AsyncMock(),
        update_shoot_status=AsyncMock(),
        reschedule_shoot=AsyncMock(),
        update_shoot_comment=AsyncMock(),
    )


@pytest.fixture
def memory_state() -> MemoryState:
    return MemoryState()


@pytest.fixture
def recent_models() -> RecentModels:
    return RecentModels()


@pytest.fixture
def user_admin() -> int:
    return 111


@pytest.fixture
def user_denied() -> int:
    return 333


import asyncio
import inspect


def pytest_pyfunc_call(pyfuncitem):
    testfunc = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunc):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(testfunc(**pyfuncitem.funcargs))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
        return True
    return None
