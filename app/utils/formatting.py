from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


MONTHS_SHORT = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]


def format_date_short(d: date | str | None) -> str:
    """Format date as '15 Jan'."""
    if d is None:
        return "—"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d)
        except ValueError:
            return d
    return f"{d.day} {MONTHS_SHORT[d.month - 1]}"


def format_month_year(d: date | None) -> str:
    """Format date as 'January 2026'."""
    if d is None:
        return "—"
    return f"{MONTHS_SHORT[d.month - 1]} {d.year}"


def format_month_ru(d: date | None) -> str:
    """Format date as 'Январь' (Russian month name)."""
    if d is None:
        return "—"
    return MONTHS_RU[d.month - 1]


def days_open(in_date: date | str | None, today: date) -> int | None:
    """Calculate days since order was opened."""
    if in_date is None:
        return None
    if isinstance(in_date, str):
        try:
            in_date = date.fromisoformat(in_date)
        except ValueError:
            return None
    return (today - in_date).days


def parse_date(value: str) -> date | None:
    """Parse date from various formats."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def today(tz: ZoneInfo) -> date:
    """Get today's date in the specified timezone."""
    return datetime.now(tz).date()


def resolve_relative_date(value: str, tz: ZoneInfo) -> date | None:
    """Resolve 'today' or 'yesterday' to actual date."""
    now = today(tz)
    if value == "today":
        return now
    if value == "yesterday":
        return now - timedelta(days=1)
    return None


def format_percent(value: float | None) -> str:
    """Format percentage value."""
    if value is None:
        return "0%"
    return f"{int(value * 100)}%"


def calculate_percent(amount: int, total: int) -> float:
    """Calculate percentage as decimal (0.0 - 1.0)."""
    if total <= 0:
        return 0.0
    return amount / total


def escape_html(text: str | None) -> str:
    """Escape HTML special characters."""
    if text is None:
        return ""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
