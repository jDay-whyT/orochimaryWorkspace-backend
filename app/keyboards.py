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
                callback_data=f"oc|pick_order|{order['page_id']}",
            )
        )
    if total_pages > 1:
        pagination: list[InlineKeyboardButton] = []
        if page > 1:
            pagination.append(InlineKeyboardButton(text="◀ Prev", callback_data=f"oc|page|{page - 1}"))
        if page < total_pages:
            pagination.append(InlineKeyboardButton(text="Next ▶", callback_data=f"oc|page|{page + 1}"))
        if pagination:
            builder.row(*pagination)
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="oc|list_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oc|cancel|cancel"),
    )
    return builder.as_markup()


def close_action_keyboard(page_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Close today", callback_data=f"oc|close_today|{page_id}"),
        InlineKeyboardButton(text="📅 Close date", callback_data=f"oc|close_date|{page_id}"),
    )
    builder.row(InlineKeyboardButton(text="✏️ Comment", callback_data=f"oc|comment|{page_id}"))
    builder.row(
        InlineKeyboardButton(text="⬅ Back to list", callback_data="oc|action_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oc|cancel|cancel"),
    )
    return builder.as_markup()


def close_date_keyboard_min() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Today", callback_data="oc|close_date_pick|today"),
        InlineKeyboardButton(text="Yesterday", callback_data="oc|close_date_pick|yesterday"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="oc|close_date_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oc|cancel|cancel"),
    )
    return builder.as_markup()


def comment_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅ Back", callback_data="oc|comment_back|back"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="oc|cancel|cancel"),
    )
    return builder.as_markup()


def close_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✖ Cancel", callback_data="oc|cancel|cancel"))
    return builder.as_markup()
