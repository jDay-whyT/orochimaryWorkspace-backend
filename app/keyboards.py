from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def models_keyboard(models: list[tuple[str, str]], prefix: str = "ocreate") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for model_id, title in models:
        builder.add(InlineKeyboardButton(text=title, callback_data=f"{prefix}|model|{model_id}"))
    builder.adjust(1)
    return builder.as_markup()


def types_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in ["short", "ad request", "call", "custom"]:
        builder.add(InlineKeyboardButton(text=value, callback_data=f"ocreate|type|{value}"))
    builder.adjust(2)
    return builder.as_markup()


def date_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Today", callback_data="ocreate|date|today"))
    builder.add(InlineKeyboardButton(text="Yesterday", callback_data="ocreate|date|yesterday"))
    builder.add(InlineKeyboardButton(text="Enter", callback_data="ocreate|date|enter"))
    builder.adjust(2)
    return builder.as_markup()


def skip_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Skip", callback_data="ocreate|comment|skip"))
    return builder.as_markup()


def create_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✖ Cancel", callback_data="ocreate|cancel|cancel"))
    return builder.as_markup()


def create_back_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="ocreate|back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="ocreate|cancel|cancel"),
    )
    return builder.as_markup()


def create_models_keyboard(models: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for model_id, title in models:
        builder.add(InlineKeyboardButton(text=title, callback_data=f"ocreate|model|{model_id}"))
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="ocreate|back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="ocreate|cancel|cancel"),
    )
    return builder.as_markup()


def create_types_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in ["short", "ad request", "call", "custom"]:
        builder.add(InlineKeyboardButton(text=value, callback_data=f"ocreate|type|{value}"))
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="ocreate|back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="ocreate|cancel|cancel"),
    )
    return builder.as_markup()


def create_in_date_keyboard(include_enter: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Today", callback_data="ocreate|date|today"))
    builder.add(InlineKeyboardButton(text="Yesterday", callback_data="ocreate|date|yesterday"))
    if include_enter:
        builder.add(InlineKeyboardButton(text="Enter", callback_data="ocreate|date|enter"))
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="ocreate|back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="ocreate|cancel|cancel"),
    )
    return builder.as_markup()


def create_comment_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Skip", callback_data="ocreate|comment|skip"))
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="ocreate|back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="ocreate|cancel|cancel"),
    )
    return builder.as_markup()


def create_success_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="New order", callback_data="ocreate|start|start"),
        InlineKeyboardButton(text="Close orders", callback_data="oclose|start|start"),
    )
    return builder.as_markup()


def close_list_keyboard(
    orders_page: list[dict[str, str]],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders_page:
        builder.row(
            InlineKeyboardButton(
                text=order["label"],
                callback_data=f"oclose|pick_order|{order['page_id']}",
            )
        )
    if total_pages > 1:
        pagination: list[InlineKeyboardButton] = []
        if page > 1:
            pagination.append(InlineKeyboardButton(text="◀ Prev", callback_data=f"oclose|page|{page - 1}"))
        if page < total_pages:
            pagination.append(InlineKeyboardButton(text="Next ▶", callback_data=f"oclose|page|{page + 1}"))
        if pagination:
            builder.row(*pagination)
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="oclose|list_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oclose|cancel|cancel"),
    )
    return builder.as_markup()


def close_action_keyboard(page_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Close today", callback_data=f"oclose|close_today|{page_id}"),
        InlineKeyboardButton(text="📅 Close date", callback_data=f"oclose|close_date|{page_id}"),
    )
    builder.row(InlineKeyboardButton(text="✏️ Comment", callback_data=f"oclose|comment|{page_id}"))
    builder.row(
        InlineKeyboardButton(text="⬅ Back to list", callback_data="oclose|action_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oclose|cancel|cancel"),
    )
    return builder.as_markup()


def close_date_keyboard_min() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Today", callback_data="oclose|close_date_pick|today"),
        InlineKeyboardButton(text="Yesterday", callback_data="oclose|close_date_pick|yesterday"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="oclose|close_date_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oclose|cancel|cancel"),
    )
    return builder.as_markup()


def comment_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="oclose|comment_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oclose|cancel|cancel"),
    )
    return builder.as_markup()
