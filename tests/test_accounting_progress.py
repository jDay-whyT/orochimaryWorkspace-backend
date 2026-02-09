import pytest

from app.utils.accounting import (
    calculate_accounting_progress,
    format_accounting_progress,
    get_accounting_target,
)


@pytest.fixture()
def accounting_env(monkeypatch):
    monkeypatch.delenv("FILES_PER_MONTH", raising=False)
    monkeypatch.setenv("FILES_PER_MONTH_WORK", "200")
    monkeypatch.setenv("FILES_PER_MONTH_NEW", "150")
    yield


def test_accounting_target_work(accounting_env):
    target, pct, _ = calculate_accounting_progress(200, "work")
    assert target == 200
    assert pct == 100


def test_accounting_target_new(accounting_env):
    target, pct, _ = calculate_accounting_progress(150, "new")
    assert target == 150
    assert pct == 100


def test_accounting_target_new_half(accounting_env):
    target, pct, _ = calculate_accounting_progress(75, "new")
    assert target == 150
    assert pct == 50


@pytest.mark.parametrize("status", [None, "??"])
def test_accounting_target_unknown_defaults_to_work(accounting_env, status):
    assert get_accounting_target(status) == 200


def test_accounting_progress_format(accounting_env):
    progress = format_accounting_progress(75, "new")
    assert progress.startswith("75/150")
