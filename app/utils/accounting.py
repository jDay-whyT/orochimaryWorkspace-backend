import os

from app.utils.constants import ACCOUNTING_STATUS_NEW, ACCOUNTING_STATUS_WORK


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_accounting_target(status: str | None) -> int:
    """Return monthly target based on accounting status."""
    work_fallback = _get_env_int("FILES_PER_MONTH", 200)
    work_target = _get_env_int("FILES_PER_MONTH_WORK", work_fallback)
    new_target = _get_env_int("FILES_PER_MONTH_NEW", 150)
    normalized = (status or "").strip().lower()
    if normalized == ACCOUNTING_STATUS_NEW:
        return new_target
    if normalized == ACCOUNTING_STATUS_WORK:
        return work_target
    return work_target


def calculate_accounting_progress(files_total: int, status: str | None) -> tuple[int, int, int]:
    """Return (target, percent, over) for files accounting."""
    target = get_accounting_target(status)
    pct = min(100, round(files_total / target * 100)) if target > 0 else 0
    over = max(0, files_total - target)
    return target, pct, over


def format_accounting_progress(
    files_total: int,
    status: str | None,
    include_over: bool = True,
) -> str:
    """Format files progress as 'X/target (Y%) [+over]'."""
    target, pct, over = calculate_accounting_progress(files_total, status)
    base = f"{files_total}/{target} ({pct}%)"
    if include_over and over > 0:
        return f"{base} +{over}"
    return base
