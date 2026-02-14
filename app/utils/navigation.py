"""Navigation helpers for breadcrumbs and common navigation buttons."""

from aiogram.types import InlineKeyboardButton


def format_breadcrumbs(path: list[str] | tuple[str, ...] | str) -> str:
    """Format breadcrumbs path like: '📦 Orders → Model → #123'."""
    if isinstance(path, str):
        items = [part.strip() for part in path.split("→") if part.strip()]
    else:
        items = [str(part).strip() for part in path if str(part).strip()]

    if not items:
        return "🏠 Меню"

    return " → ".join(items)


def build_nav_buttons(
    callback_prefix: str,
    section_label: str,
    *,
    back_to: str = "back",
    section_to: str = "menu",
    menu_to: str = "main",
    token: str = "",
) -> list[InlineKeyboardButton]:
    """Build a standard navigation row: Back / Section / Main menu."""
    suffix = f"|{token}" if token else ""
    return [
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"{callback_prefix}|back|{back_to}{suffix}"),
        InlineKeyboardButton(text=section_label, callback_data=f"{callback_prefix}|back|{section_to}{suffix}"),
        InlineKeyboardButton(text="🏠 Меню", callback_data=f"{callback_prefix}|back|{menu_to}{suffix}"),
    ]
