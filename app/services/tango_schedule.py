import re
from dataclasses import dataclass

ENTRY_RE = re.compile(r"(\d{2}\.\d{2})\s*—\s*(\d{2}:\d{2})")

# Heuristic thresholds for Google Sheets colors (0..1 float channels).
_WHITE_MIN_CHANNEL = 0.95
_GRAY_CHANNEL_SPREAD = 0.05
_RED_MIN_CHANNEL = 0.5
_RED_MAX_OTHER_CHANNEL = 0.35


@dataclass
class TangoRawRow:
    """One row of the sheet: model name cell + 'current week' cell, both with formatting."""
    name: str
    name_background: dict | None
    week_text: str
    week_text_format_runs: list[dict] | None
    url: str = ""


@dataclass
class TangoScheduleEntry:
    model_name: str
    time: str
    sort_hour: int
    url: str = ""


def find_entries(cell_text: str) -> list[dict]:
    """Extract all 'ДД.ММ — ЧЧ:ММ' entries with character offsets from a cell's text."""
    entries = []
    for m in ENTRY_RE.finditer(cell_text):
        date_str, time_str = m.group(1), m.group(2)
        hour = int(time_str[:2])
        entries.append({
            "date": date_str,
            "time": time_str,
            "hour": hour,
            "start": m.start(),
        })
    return entries


def _format_at(offset: int, runs: list[dict] | None) -> dict:
    """Sheets textFormatRuns apply from startIndex until the next run's startIndex."""
    if not runs:
        return {}
    active: dict = {}
    for run in runs:
        if run.get("startIndex", 0) <= offset:
            active = run.get("format") or {}
        else:
            break
    return active


def is_cancelled_red(fmt: dict) -> bool:
    color = fmt.get("foregroundColor") or {}
    r = color.get("red", 0)
    g = color.get("green", 0)
    b = color.get("blue", 0)
    return r > _RED_MIN_CHANNEL and g < _RED_MAX_OTHER_CHANNEL and b < _RED_MAX_OTHER_CHANNEL


def is_paused_row(background: dict | None) -> bool:
    """Gray fill = model paused. Default/white cells are never paused."""
    if not background:
        return False
    r = background.get("red", 1)
    g = background.get("green", 1)
    b = background.get("blue", 1)
    if min(r, g, b) > _WHITE_MIN_CHANNEL:
        return False
    return max(r, g, b) - min(r, g, b) < _GRAY_CHANNEL_SPREAD


def sort_key(hour: int) -> int:
    """00:00–05:59 counts as the end of the previous stream-day, sorts last."""
    return hour + 24 if hour < 6 else hour


def build_tomorrow_schedule(
    rows: list[TangoRawRow], tomorrow_ddmm: str, day_after_ddmm: str | None = None
) -> list[TangoScheduleEntry]:
    """
    Models are CIS/LatAm-based; a shift that starts in the evening runs into the early
    morning of the next calendar date, and gets logged in the sheet under that later
    date. So a 00:00-05:59 entry always belongs to the *previous* stream day, never its
    own literal date (this mirrors sort_key's "end of the previous stream day" rule —
    it must apply to which day's list an entry belongs to, not just its sort position,
    or a model with a recurring nightly 00:00-05:59 slot shows up twice in one list: once
    under its own date's direct match, again as the next day's tail).
    """
    result: list[TangoScheduleEntry] = []
    for row in rows:
        if is_paused_row(row.name_background):
            continue
        for entry in find_entries(row.week_text):
            if entry["date"] == tomorrow_ddmm and entry["hour"] >= 6:
                pass
            elif entry["date"] == day_after_ddmm and entry["hour"] < 6:
                pass
            else:
                continue
            fmt = _format_at(entry["start"], row.week_text_format_runs)
            if fmt.get("strikethrough"):
                continue
            if is_cancelled_red(fmt):
                continue
            result.append(TangoScheduleEntry(
                model_name=row.name,
                time=entry["time"],
                sort_hour=sort_key(entry["hour"]),
                url=row.url,
            ))
    result.sort(key=lambda e: e.sort_hour)
    return result
