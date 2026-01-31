import calendar
from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def calendar_keyboard(
    prefix: str,
    year: int,
    month: int,
    min_date: date | None = None,
    max_date: date | None = None,
) -> InlineKeyboardMarkup:
    """
    Generate inline calendar keyboard.
    
    Args:
        prefix: Callback prefix (e.g., "planner")
        year: Year to display
        month: Month to display (1-12)
        min_date: Minimum selectable date (inclusive)
        max_date: Maximum selectable date (inclusive)
    """
    builder = InlineKeyboardBuilder()
    
    # Header: Month Year
    builder.row(InlineKeyboardButton(
        text=f"{MONTHS[month - 1]} {year}",
        callback_data=f"{prefix}|cal_ignore|ignore"
    ))
    
    # Weekday headers
    builder.row(*[
        InlineKeyboardButton(text=day, callback_data=f"{prefix}|cal_ignore|ignore")
        for day in WEEKDAYS
    ])
    
    # Get calendar for month
    cal = calendar.Calendar(firstweekday=0)  # Monday first
    month_days = cal.monthdayscalendar(year, month)
    
    for week in month_days:
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                # Empty cell
                row.append(InlineKeyboardButton(
                    text=" ",
                    callback_data=f"{prefix}|cal_ignore|ignore"
                ))
            else:
                current_date = date(year, month, day)
                
                # Check if date is selectable
                is_selectable = True
                if min_date and current_date < min_date:
                    is_selectable = False
                if max_date and current_date > max_date:
                    is_selectable = False
                
                if is_selectable:
                    row.append(InlineKeyboardButton(
                        text=str(day),
                        callback_data=f"{prefix}|cal_day|{current_date.isoformat()}"
                    ))
                else:
                    # Grayed out (not selectable)
                    row.append(InlineKeyboardButton(
                        text=f"·{day}·",
                        callback_data=f"{prefix}|cal_ignore|ignore"
                    ))
        
        builder.row(*row)
    
    # Navigation: Prev / Next month
    nav_row: list[InlineKeyboardButton] = []
    
    # Previous month
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1
    
    # Check if prev month has any selectable dates
    can_go_prev = True
    if min_date:
        last_day_prev = date(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1])
        if last_day_prev < min_date:
            can_go_prev = False
    
    if can_go_prev:
        nav_row.append(InlineKeyboardButton(
            text="< Prev",
            callback_data=f"{prefix}|cal_nav|{prev_year}-{prev_month:02d}"
        ))
    else:
        nav_row.append(InlineKeyboardButton(
            text=" ",
            callback_data=f"{prefix}|cal_ignore|ignore"
        ))
    
    # Next month
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    
    # Check if next month has any selectable dates
    can_go_next = True
    if max_date:
        first_day_next = date(next_year, next_month, 1)
        if first_day_next > max_date:
            can_go_next = False
    
    if can_go_next:
        nav_row.append(InlineKeyboardButton(
            text="Next >",
            callback_data=f"{prefix}|cal_nav|{next_year}-{next_month:02d}"
        ))
    else:
        nav_row.append(InlineKeyboardButton(
            text=" ",
            callback_data=f"{prefix}|cal_ignore|ignore"
        ))
    
    builder.row(*nav_row)
    
    # Back/Cancel
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data=f"{prefix}|back|location"),
        InlineKeyboardButton(text="✖ Cancel", callback_data=f"{prefix}|cancel|cancel"),
    )
    
    return builder.as_markup()


def parse_calendar_navigation(value: str) -> tuple[int, int] | None:
    """Parse calendar navigation callback value (YYYY-MM)."""
    try:
        parts = value.split("-")
        if len(parts) != 2:
            return None
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
