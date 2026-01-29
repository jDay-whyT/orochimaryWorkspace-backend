from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def models_keyboard(models: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for model_id, title in models:
        builder.add(InlineKeyboardButton(text=title, callback_data=f"oc|model|{model_id}"))
    builder.adjust(1)
    return builder.as_markup()


def types_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in ["short", "ad request", "call", "custom"]:
        builder.add(InlineKeyboardButton(text=value, callback_data=f"oc|type|{value}"))
    builder.adjust(2)
    return builder.as_markup()


def qty_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in [1, 2, 3, 5, 10]:
        builder.add(InlineKeyboardButton(text=str(value), callback_data=f"oc|qty|{value}"))
    builder.add(InlineKeyboardButton(text="Enter", callback_data="oc|qty|enter"))
    builder.adjust(3)
    return builder.as_markup()


def date_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Today", callback_data="oc|date|today"))
    builder.add(InlineKeyboardButton(text="Yesterday", callback_data="oc|date|yesterday"))
    builder.add(InlineKeyboardButton(text="Enter", callback_data="oc|date|enter"))
    builder.adjust(2)
    return builder.as_markup()


def skip_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Skip", callback_data="oc|comment|skip"))
    return builder.as_markup()


def count_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in [1, 2, 3, 5, 10]:
        builder.add(InlineKeyboardButton(text=str(value), callback_data=f"oc|count|{value}"))
    builder.add(InlineKeyboardButton(text="Enter", callback_data="oc|count|enter"))
    builder.adjust(3)
    return builder.as_markup()


def close_keyboard(label: str, order_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=label, callback_data=f"oc|close|{order_id}"))
    return builder.as_markup()
