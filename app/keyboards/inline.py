from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.constants import ORDER_TYPES, PLANNER_CONTENT_OPTIONS, PLANNER_LOCATION_OPTIONS


# ==================== Common ====================

def back_keyboard(callback_prefix: str, back_to: str = "main") -> InlineKeyboardMarkup:
    """Simple back button with customizable destination."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Back", callback_data=f"{callback_prefix}|back|{back_to}")]
    ])


def cancel_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    """Cancel button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖ Cancel", callback_data=f"{callback_prefix}|cancel|cancel")]
    ])


def back_cancel_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    """Back and Cancel buttons."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Back", callback_data=f"{callback_prefix}|back|back"),
            InlineKeyboardButton(text="✖ Cancel", callback_data=f"{callback_prefix}|cancel|cancel"),
        ]
    ])


# ==================== Models Selection ====================

def models_keyboard(
    prefix: str,
    recent: list[tuple[str, str]] | None = None,
    show_back: bool = True,
    show_search: bool = False,
    back_to: str = "menu",
) -> InlineKeyboardMarkup:
    """
    Keyboard with model buttons from recent list.
    recent: [(model_id, title), ...]
    """
    builder = InlineKeyboardBuilder()
    
    if recent:
        # Recent models in rows of 3
        row: list[InlineKeyboardButton] = []
        for model_id, title in recent[:9]:
            row.append(InlineKeyboardButton(
                text=title,
                callback_data=f"{prefix}|select_model|{model_id}"
            ))
            if len(row) == 3:
                builder.row(*row)
                row = []
        if row:
            builder.row(*row)
    
    if show_search:
        builder.row(InlineKeyboardButton(
            text="🔍 Search",
            callback_data=f"{prefix}|search|search"
        ))
    
    if show_back:
        builder.row(
            InlineKeyboardButton(text="◀️ Back", callback_data=f"{prefix}|back|{back_to}"),
            InlineKeyboardButton(text="✖ Cancel", callback_data=f"{prefix}|cancel|cancel"),
        )
    
    return builder.as_markup()


def recent_models_keyboard(
    recent: list[tuple[str, str]],
    prefix: str,
) -> InlineKeyboardMarkup:
    """
    Keyboard with recent models + search button.
    recent: [(model_id, title), ...]
    """
    builder = InlineKeyboardBuilder()
    
    # Recent models in rows of 3
    row: list[InlineKeyboardButton] = []
    for model_id, title in recent[:9]:
        row.append(InlineKeyboardButton(
            text=title,
            callback_data=f"{prefix}|model|{model_id}"
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    
    # Search and Back
    builder.row(
        InlineKeyboardButton(text="🔍 Search", callback_data=f"{prefix}|search|search"),
        InlineKeyboardButton(text="◀️ Back", callback_data=f"{prefix}|back|menu"),
    )
    
    return builder.as_markup()


# ==================== Orders ====================

def orders_menu_keyboard() -> InlineKeyboardMarkup:
    """Orders section menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Search model", callback_data="orders|search|search")],
        [
            InlineKeyboardButton(text="📋 Open", callback_data="orders|open|list"),
            InlineKeyboardButton(text="➕ New", callback_data="orders|new|start"),
        ],
        [InlineKeyboardButton(text="◀️ Back", callback_data="orders|back|main")],
    ])


def orders_list_keyboard(
    orders: list[dict[str, str]],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """
    List of open orders with pagination.
    orders: [{"page_id": str, "label": str}, ...]
    """
    builder = InlineKeyboardBuilder()
    
    for order in orders:
        builder.row(InlineKeyboardButton(
            text=order["label"],
            callback_data=f"orders|select|{order['page_id']}"
        ))
    
    # Pagination
    if total_pages > 1:
        pagination: list[InlineKeyboardButton] = []
        if page > 1:
            pagination.append(InlineKeyboardButton(
                text="◀ Prev", 
                callback_data=f"orders|page|{page - 1}"
            ))
        if page < total_pages:
            pagination.append(InlineKeyboardButton(
                text="Next ▶", 
                callback_data=f"orders|page|{page + 1}"
            ))
        if pagination:
            builder.row(*pagination)
    
    builder.row(InlineKeyboardButton(
        text="◀️ Back list", 
        callback_data="orders|back|model_select"
    ))
    
    return builder.as_markup()


def order_action_keyboard(page_id: str) -> InlineKeyboardMarkup:
    """Actions for a selected order."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Today", callback_data=f"orders|close_today|{page_id}"),
            InlineKeyboardButton(text="✓ Yesterday", callback_data=f"orders|close_yesterday|{page_id}"),
            InlineKeyboardButton(text="💬", callback_data=f"orders|comment|{page_id}"),
        ],
        [InlineKeyboardButton(text="◀️ Back list", callback_data="orders|back|list")],
    ])


def order_types_keyboard() -> InlineKeyboardMarkup:
    """Order type selection."""
    builder = InlineKeyboardBuilder()
    
    row: list[InlineKeyboardButton] = []
    for order_type in ORDER_TYPES:
        row.append(InlineKeyboardButton(
            text=order_type,
            callback_data=f"orders|type|{order_type}"
        ))
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data="orders|back|model"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="orders|cancel|cancel"),
    )
    
    return builder.as_markup()


def order_qty_keyboard(current_qty: int = 1) -> InlineKeyboardMarkup:
    """Quantity selection for orders."""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="1", callback_data="orders|qty|1"),
        InlineKeyboardButton(text="2", callback_data="orders|qty|2"),
        InlineKeyboardButton(text="3", callback_data="orders|qty|3"),
        InlineKeyboardButton(text="5", callback_data="orders|qty|5"),
        InlineKeyboardButton(text="+", callback_data="orders|qty|custom"),
    )
    
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data="orders|back|type"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="orders|cancel|cancel"),
    )
    
    return builder.as_markup()


def order_date_keyboard() -> InlineKeyboardMarkup:
    """Date selection for order creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Today", callback_data="orders|date|today"),
            InlineKeyboardButton(text="Yesterday", callback_data="orders|date|yesterday"),
        ],
        [
            InlineKeyboardButton(text="◀️ Back", callback_data="orders|back|qty"),
            InlineKeyboardButton(text="✖ Cancel", callback_data="orders|cancel|cancel"),
        ],
    ])


def order_comment_keyboard() -> InlineKeyboardMarkup:
    """Comment prompt for order creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Skip", callback_data="orders|comment_skip|skip"),
            InlineKeyboardButton(text="Add 💬", callback_data="orders|comment_add|add"),
        ],
        [
            InlineKeyboardButton(text="◀️ Back", callback_data="orders|back|date"),
            InlineKeyboardButton(text="✖ Cancel", callback_data="orders|cancel|cancel"),
        ],
    ])


def order_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirmation before creating order."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✓ Create", callback_data="orders|confirm|create")],
        [
            InlineKeyboardButton(text="◀️ Back", callback_data="orders|back|comment"),
            InlineKeyboardButton(text="✖ Cancel", callback_data="orders|cancel|cancel"),
        ],
    ])


def order_success_keyboard() -> InlineKeyboardMarkup:
    """After successful order creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ New order", callback_data="orders|new|start"),
            InlineKeyboardButton(text="📋 Open orders", callback_data="orders|open|list"),
        ],
        [InlineKeyboardButton(text="◀️ Back", callback_data="orders|back|menu")],
    ])


# ==================== Planner ====================

def planner_menu_keyboard() -> InlineKeyboardMarkup:
    """Planner section menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Search model", callback_data="planner|search|search")],
        [
            InlineKeyboardButton(text="📋 Upcoming", callback_data="planner|upcoming|list"),
            InlineKeyboardButton(text="➕ New", callback_data="planner|new|start"),
        ],
        [InlineKeyboardButton(text="◀️ Back", callback_data="planner|back|main")],
    ])


def planner_content_keyboard(prefix: str, selected: list[str]) -> InlineKeyboardMarkup:
    """Multi-select content for shoots."""
    builder = InlineKeyboardBuilder()
    
    row: list[InlineKeyboardButton] = []
    for option in PLANNER_CONTENT_OPTIONS:
        mark = "✓ " if option in selected else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{option}",
            callback_data=f"{prefix}|content_toggle|{option}"
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    
    builder.row(InlineKeyboardButton(text="Next →", callback_data=f"{prefix}|content_done|done"))
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data=f"{prefix}|back|select_model"),
        InlineKeyboardButton(text="✖ Cancel", callback_data=f"{prefix}|cancel|cancel"),
    )
    
    return builder.as_markup()


def planner_location_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """Location selection for shoots."""
    builder = InlineKeyboardBuilder()
    
    for loc in PLANNER_LOCATION_OPTIONS:
        builder.add(InlineKeyboardButton(
            text=loc,
            callback_data=f"{prefix}|location|{loc}"
        ))
    builder.adjust(2)
    
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data=f"{prefix}|back|content"),
        InlineKeyboardButton(text="✖ Cancel", callback_data=f"{prefix}|cancel|cancel"),
    )
    
    return builder.as_markup()


def planner_shoot_keyboard(page_id: str) -> InlineKeyboardMarkup:
    """Actions for a selected shoot."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Done", callback_data=f"planner|done|{page_id}"),
            InlineKeyboardButton(text="📅 Resched", callback_data=f"planner|reschedule|{page_id}"),
            InlineKeyboardButton(text="✗ Cancel", callback_data=f"planner|cancel_shoot|{page_id}"),
        ],
        [
            InlineKeyboardButton(text="Edit content", callback_data=f"planner|edit_content|{page_id}"),
            InlineKeyboardButton(text="💬 Comment", callback_data=f"planner|comment|{page_id}"),
        ],
        [InlineKeyboardButton(text="◀️ Back list", callback_data="planner|upcoming|list")],
    ])


# ==================== Accounting ====================

def accounting_menu_keyboard() -> InlineKeyboardMarkup:
    """Accounting section menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Search model", callback_data="account|search|search")],
        [
            InlineKeyboardButton(text="📋 Current", callback_data="account|current|list"),
            InlineKeyboardButton(text="➕ Files", callback_data="account|add_files|start"),
        ],
        [InlineKeyboardButton(text="◀️ Back", callback_data="account|back|main")],
    ])


def accounting_quick_files_keyboard(page_id: str, current: int) -> InlineKeyboardMarkup:
    """Quick file count buttons."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5", callback_data=f"account|files|{page_id}|5"),
            InlineKeyboardButton(text="10", callback_data=f"account|files|{page_id}|10"),
            InlineKeyboardButton(text="15", callback_data=f"account|files|{page_id}|15"),
            InlineKeyboardButton(text="20", callback_data=f"account|files|{page_id}|20"),
        ],
        [InlineKeyboardButton(text="◀️ Back", callback_data="account|back|list")],
    ])


# ==================== Summary ====================

def summary_menu_keyboard(recent: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Summary section with recent models."""
    builder = InlineKeyboardBuilder()
    
    # Recent models in rows of 3
    row: list[InlineKeyboardButton] = []
    for model_id, title in recent[:9]:
        row.append(InlineKeyboardButton(
            text=title,
            callback_data=f"summary|model|{model_id}"
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    
    builder.row(
        InlineKeyboardButton(text="🔍 Search", callback_data="summary|search|search"),
        InlineKeyboardButton(text="◀️ Back", callback_data="summary|back|main"),
    )
    
    return builder.as_markup()


def summary_card_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Model summary card actions."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Debts", callback_data=f"summary|debts|{model_id}"),
            InlineKeyboardButton(text="📋 Orders", callback_data=f"summary|orders|{model_id}"),
        ],
        [
            InlineKeyboardButton(text="➕ Files", callback_data=f"summary|files|{model_id}"),
            InlineKeyboardButton(text="◀️ Back", callback_data="summary|back|menu"),
        ],
    ])


# ==================== NLP Router Keyboards ====================

def nlp_model_selection_keyboard(
    models: list[dict],
    intent: str,
    entities: Any,
) -> InlineKeyboardMarkup:
    """
    Keyboard for selecting model when multiple matches found.
    models: [{"id": str, "name": str, "aliases": list[str]}, ...]
    """
    builder = InlineKeyboardBuilder()

    for model in models[:5]:  # Limit to 5 models
        builder.row(
            InlineKeyboardButton(
                text=model["name"], callback_data=f"nlp:select_model:{model['id']}:{intent}"
            )
        )

    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel"))

    return builder.as_markup()


def nlp_order_confirm_keyboard(
    model_id: str, order_type: str, count: int, date_iso: str
) -> InlineKeyboardMarkup:
    """Confirmation keyboard for creating orders via NLP."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 Сегодня",
                    callback_data=f"nlp:order_date:{model_id}:{order_type}:{count}:today",
                ),
                InlineKeyboardButton(
                    text="📅 Вчера",
                    callback_data=f"nlp:order_date:{model_id}:{order_type}:{count}:yesterday",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Создать",
                    callback_data=f"nlp:order_confirm:{model_id}:{order_type}:{count}:{date_iso}",
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel"),
            ],
        ]
    )


def nlp_disambiguate_keyboard(model_id: str, number: int) -> InlineKeyboardMarkup:
    """Keyboard for disambiguating intent (files vs orders)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📁 Добавить {number} файлов",
                    callback_data=f"nlp:disambig_files:{model_id}:{number}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📦 Создать {number} заказов",
                    callback_data=f"nlp:disambig_orders:{model_id}:{number}",
                )
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel")],
        ]
    )


def nlp_report_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Keyboard for report actions."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Детали Orders", callback_data=f"nlp:report_orders:{model_id}"
                ),
                InlineKeyboardButton(
                    text="📁 Детали Accounting",
                    callback_data=f"nlp:report_accounting:{model_id}",
                ),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="nlp:cancel:cancel")],
        ]
    )


# ==================== NLP Shoot Keyboards ====================

def nlp_shoot_date_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Date selection keyboard for shoot creation/reschedule."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Завтра",
                    callback_data=f"nlp:shoot_date:{model_id}:tomorrow",
                ),
                InlineKeyboardButton(
                    text="Послезавтра",
                    callback_data=f"nlp:shoot_date:{model_id}:day_after",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Другая дата",
                    callback_data=f"nlp:shoot_date:{model_id}:custom",
                ),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel")],
        ]
    )


def nlp_shoot_confirm_done_keyboard(shoot_id: str) -> InlineKeyboardMarkup:
    """Confirm marking a shoot as done."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да",
                    callback_data=f"nlp:shoot_done_confirm:{shoot_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data="nlp:cancel:cancel",
                ),
            ],
        ]
    )


def nlp_shoot_select_keyboard(
    shoots: list,
    action: str,
) -> InlineKeyboardMarkup:
    """
    Select a shoot from list.
    action: "done" | "reschedule" | "comment"
    """
    builder = InlineKeyboardBuilder()

    for shoot in shoots[:5]:
        date_str = shoot.date[:10] if shoot.date else "?"
        try:
            from datetime import date as _date
            d = _date.fromisoformat(date_str)
            label = d.strftime("%d.%m")
        except (ValueError, TypeError):
            label = date_str

        builder.row(
            InlineKeyboardButton(
                text=f"📅 {label}",
                callback_data=f"nlp:shoot_select:{action}:{shoot.page_id}",
            )
        )

    if len(shoots) > 5:
        builder.row(
            InlineKeyboardButton(
                text=f"Показать ещё ({len(shoots) - 5})",
                callback_data=f"nlp:shoot_more:{action}:5",
            )
        )

    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel"))
    return builder.as_markup()


# ==================== NLP Order Keyboards ====================

def nlp_order_type_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Order type selection for general order creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Кастом",
                    callback_data=f"nlp:order_type:{model_id}:custom",
                ),
                InlineKeyboardButton(
                    text="Шорт",
                    callback_data=f"nlp:order_type:{model_id}:short",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Колл",
                    callback_data=f"nlp:order_type:{model_id}:call",
                ),
                InlineKeyboardButton(
                    text="Ad Request",
                    callback_data=f"nlp:order_type:{model_id}:ad request",
                ),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel")],
        ]
    )


def nlp_order_qty_keyboard(model_id: str, order_type: str) -> InlineKeyboardMarkup:
    """Quantity selection for orders."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1", callback_data=f"nlp:order_qty:{model_id}:{order_type}:1",
                ),
                InlineKeyboardButton(
                    text="2", callback_data=f"nlp:order_qty:{model_id}:{order_type}:2",
                ),
                InlineKeyboardButton(
                    text="3", callback_data=f"nlp:order_qty:{model_id}:{order_type}:3",
                ),
                InlineKeyboardButton(
                    text="5", callback_data=f"nlp:order_qty:{model_id}:{order_type}:5",
                ),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel")],
        ]
    )


def nlp_close_order_date_keyboard(order_id: str) -> InlineKeyboardMarkup:
    """Date selection for closing an order."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✓ Сегодня",
                    callback_data=f"nlp:close_date:today:{order_id}",
                ),
                InlineKeyboardButton(
                    text="✓ Вчера",
                    callback_data=f"nlp:close_date:yesterday:{order_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Другая",
                    callback_data=f"nlp:close_date:custom:{order_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="nlp:cancel:cancel",
                ),
            ],
        ]
    )


def nlp_close_order_select_keyboard(orders: list) -> InlineKeyboardMarkup:
    """Select an order to close from multiple open orders."""
    builder = InlineKeyboardBuilder()

    for order in orders[:5]:
        from datetime import date as _date
        days = 0
        date_label = "?"
        if order.in_date:
            try:
                d = _date.fromisoformat(order.in_date[:10])
                date_label = d.strftime("%d.%m")
                days = (_date.today() - d).days
            except (ValueError, TypeError):
                pass

        label = f"{order.order_type or '?'} · {date_label} ({days}d)"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"nlp:close_order:{order.page_id}",
            )
        )

    if len(orders) > 5:
        builder.row(
            InlineKeyboardButton(
                text=f"Показать ещё ({len(orders) - 5})",
                callback_data="nlp:close_more:5",
            )
        )

    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel"))
    return builder.as_markup()


# ==================== NLP Comment Keyboards ====================

def nlp_comment_target_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Select what to comment on."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Заказ",
                    callback_data=f"nlp:comment_target:{model_id}:order",
                ),
                InlineKeyboardButton(
                    text="📅 Съемка",
                    callback_data=f"nlp:comment_target:{model_id}:shoot",
                ),
                InlineKeyboardButton(
                    text="💰 Учет",
                    callback_data=f"nlp:comment_target:{model_id}:account",
                ),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel")],
        ]
    )


def nlp_comment_order_select_keyboard(orders: list) -> InlineKeyboardMarkup:
    """Select an order to comment on."""
    builder = InlineKeyboardBuilder()

    for order in orders[:5]:
        from datetime import date as _date
        date_label = "?"
        if order.in_date:
            try:
                d = _date.fromisoformat(order.in_date[:10])
                date_label = d.strftime("%d.%m")
            except (ValueError, TypeError):
                pass

        label = f"{order.order_type or '?'} · {date_label}"
        builder.row(
            InlineKeyboardButton(
                text=label,
                callback_data=f"nlp:comment_order:{order.page_id}",
            )
        )

    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel"))
    return builder.as_markup()


# ==================== NLP Not Found Keyboard ====================

def nlp_not_found_keyboard(
    recent: list[tuple[str, str]],
    intent: str,
) -> InlineKeyboardMarkup:
    """
    Keyboard shown when model not found.
    Shows recent models + search.
    """
    builder = InlineKeyboardBuilder()

    row: list[InlineKeyboardButton] = []
    for model_id, title in recent[:5]:
        row.append(InlineKeyboardButton(
            text=title,
            callback_data=f"nlp:select_model:{model_id}:{intent}",
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    builder.row(
        InlineKeyboardButton(text="🔍 Поиск", callback_data="nlp:search:search"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:cancel:cancel"),
    )

    return builder.as_markup()
