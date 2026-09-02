import functools
import os
import re

from app.utils.constants import ACCOUNTING_STATUS_NEW, ACCOUNTING_STATUS_WORK
from app.utils.formatting import MONTHS_RU_LOWER

_MONTH_YEAR_SUFFIX_RE = re.compile(
    r"\s+(?:" + "|".join(MONTHS_RU_LOWER) + r")\s+\d{4}\s*$",
    re.IGNORECASE,
)


def rename_month_in_title(title: str, yyyy_mm: str) -> str | None:
    """
    Replace the trailing "{месяц_ru} {год}" of an accounting Title with the
    given month, keeping the model-name prefix intact.

    Returns None if the title doesn't end in the expected "{month} {year}"
    format (e.g. Tango slots, which have no month suffix at all) — caller
    should treat that as "leave alone, report as skipped".
    """
    year, month_str = yyyy_mm.split("-")
    month_label = MONTHS_RU_LOWER[int(month_str) - 1]
    new_suffix = f" {month_label} {year}"

    match = _MONTH_YEAR_SUFFIX_RE.search(title)
    if not match:
        return None

    prefix = title[: match.start()]
    return f"{prefix}{new_suffix}"


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@functools.lru_cache(maxsize=None)
def _load_targets() -> tuple[int, int]:
    """Read target env vars once per process."""
    work_fallback = _get_env_int("FILES_PER_MONTH", 200)
    work_target = _get_env_int("FILES_PER_MONTH_WORK", work_fallback)
    new_target = _get_env_int("FILES_PER_MONTH_NEW", 150)
    return work_target, new_target


def get_accounting_target(status: str | None) -> int:
    """Return monthly target based on accounting status."""
    work_target, new_target = _load_targets()
    normalized = (status or "").strip().lower()
    if normalized == ACCOUNTING_STATUS_NEW:
        return new_target
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
