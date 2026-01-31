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
