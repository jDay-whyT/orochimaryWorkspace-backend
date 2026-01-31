from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Summary"),
                KeyboardButton(text="📦 Orders"),
            ],
            [
                KeyboardButton(text="📅 Planner"),
                KeyboardButton(text="💰 Account"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
