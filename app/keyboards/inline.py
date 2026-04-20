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
            InlineKeyboardButton(text="20", callback_data=f"account|files|{page_id}|20"),
            InlineKeyboardButton(text="50", callback_data=f"account|files|{page_id}|50"),
            InlineKeyboardButton(text="80", callback_data=f"account|files|{page_id}|80"),
            InlineKeyboardButton(text="Ввод", callback_data=f"account|files|{page_id}|custom"),
        ],
        [InlineKeyboardButton(text="◀️ Back", callback_data="account|back|list")],
    ])


def content_type_selection_keyboard() -> InlineKeyboardMarkup:
    """Single-select keyboard for content type selection when adding files."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Reddit", callback_data="account|content_type|reddit"),
            InlineKeyboardButton(text="Twitter", callback_data="account|content_type|twitter"),
        ],
        [
            InlineKeyboardButton(text="Main Pack", callback_data="account|content_type|main pack"),
            InlineKeyboardButton(text="New Main", callback_data="account|content_type|new main"),
        ],
        [
            InlineKeyboardButton(text="Basic", callback_data="account|content_type|basic"),
            InlineKeyboardButton(text="Event", callback_data="account|content_type|event"),
        ],
        [
            InlineKeyboardButton(text="Fansly", callback_data="account|content_type|fansly"),
            InlineKeyboardButton(text="Snapchat", callback_data="account|content_type|snapchat"),
        ],
        [
            InlineKeyboardButton(text="Instagram", callback_data="account|content_type|IG"),
            InlineKeyboardButton(text="Ad Request", callback_data="account|content_type|ad request"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="account|back|menu")],
    ])


def nlp_accounting_content_keyboard(
    selected: list[str],
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Multi-select content types for accounting Content property."""
    s = f":{k}" if k else ""
    builder = InlineKeyboardBuilder()

    # Группа 1: Основные типы
    row1 = []
    for ct in ["main", "new main", "basic"]:
        mark = "✅ " if ct in selected else "⬜ "
        row1.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:acct:{ct}{s}",
        ))
    builder.row(*row1)

    # Группа 2: Платформы
    row2 = []
    for ct in ["twitter", "reddit", "fansly"]:
        mark = "✅ " if ct in selected else "⬜ "
        row2.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:acct:{ct}{s}",
        ))
    builder.row(*row2)

    # Группа 3: Специальные
    row3 = []
    for ct in ["ad request", "no content", "event"]:
        mark = "✅ " if ct in selected else "⬜ "
        row3.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:acct:{ct}{s}",
        ))
    builder.row(*row3)

    builder.row(InlineKeyboardButton(text="✅ Save", callback_data=f"nlp:accs:save{s}"))
    builder.row(nlp_back_button(model_id))
    return builder.as_markup()


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
#
# All NLP keyboards use SHORT callback_data (max ~55 bytes) to stay within
# Telegram's 64-byte limit.  Flow context (model_id, order_type, count …)
# is kept in memory_state; only the *new decision* goes into callback_data.
#
# Callback format:  nlp:{short_action}:{param}:{k}
#   sm  = select_model     ot  = order_type      oq  = order_qty
#   od  = order_date       oc  = order_confirm   sd  = shoot_date
#   sdc = shoot_done_conf  ss  = shoot_select    co  = close_order
#   cd  = close_date       ct  = comment_target  cmo = comment_order
#   df  = disambig_files   do  = disambig_orders ro  = report_orders
#   ra  = report_account   af  = add_files       act = model_action
#   om  = orders_menu      op  = orders_page     cp  = close_page
#   fm  = files_menu       smn = shoot_menu      bk  = back (model_id)
#   x   = cancel (c=cancel, m=menu) — no token needed
#
# Anti-stale token (k): a 6-char base36 string appended as the last segment.
# Generated fresh each time a keyboard is sent; stored in memory_state.
# The handler verifies the token to reject presses on stale keyboards.

# Centralized order_type mapping: callback_data value <-> internal value
# callback_data must NOT contain spaces (Telegram limits).
ORDER_TYPE_CB_MAP = {
    "custom": "custom",
    "short": "short",
    "verif_reddit": "verif reddit",
    "call": "call",
    "ad_request": "ad request",
}
ORDER_TYPE_CB_REVERSE = {v: k for k, v in ORDER_TYPE_CB_MAP.items()}

# Display names for order types (user-facing)
ORDER_TYPE_DISPLAY = {
    "custom": "Кастом",
    "short": "Шорт",
    "verif_reddit": "verif reddit",
    "verif reddit": "verif reddit",
    "call": "Колл",
    "ad_request": "Ad Request",
    "ad request": "Ad Request",
}


_NLP_CANCEL_BTN = InlineKeyboardButton(text="⬅ Назад", callback_data="nlp:x:c")


def nlp_back_button(model_id: str) -> InlineKeyboardButton:
    """Stateless back button (model_id in callback)."""
    return InlineKeyboardButton(text="⬅ Назад", callback_data=f"nlp:bk:{model_id}")


def nlp_model_selection_keyboard(models: list[dict], k: str = "") -> InlineKeyboardMarkup:
    """Model disambiguation. Intent is stored in memory_state by caller."""
    builder = InlineKeyboardBuilder()
    for model in models[:5]:
        cb = f"nlp:sm:{model['id']}"
        if k:
            cb += f":{k}"
        builder.row(InlineKeyboardButton(text=model["name"], callback_data=cb))
    builder.row(_NLP_CANCEL_BTN)
    return builder.as_markup()


def nlp_confirm_model_keyboard(model_id: str, model_name: str, k: str = "") -> InlineKeyboardMarkup:
    """Confirm fuzzy-matched model. Intent is stored in memory_state."""
    cb = f"nlp:sm:{model_id}"
    if k:
        cb += f":{k}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Да, {model_name}", callback_data=cb)],
        [InlineKeyboardButton(text="Нет", callback_data="nlp:x:c")],
    ])


def nlp_model_actions_keyboard(k: str = "") -> InlineKeyboardMarkup:
    """CRM action card shown after model context is set. model_id in memory."""
    return model_card_keyboard(k)


def nlp_back_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Single back button to return to model card."""
    return InlineKeyboardMarkup(inline_keyboard=[[nlp_back_button(model_id)]])

def model_card_keyboard(k: str = "") -> InlineKeyboardMarkup:
    """
    Universal model card keyboard (CRM main scenario).

    Row 1: 📦 Заказы | 📅 Съёмка | 📁 Файлы
    """
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Заказы", callback_data=f"nlp:act:orders{s}"),
            InlineKeyboardButton(text="📅 Съёмка", callback_data=f"nlp:act:shoot{s}"),
            InlineKeyboardButton(text="📁 Файлы", callback_data=f"nlp:act:files{s}"),
        ],
        [InlineKeyboardButton(text="Готово", callback_data="nlp:x:c")],
    ])


def nlp_orders_menu_keyboard(
    can_edit: bool,
    has_orders: bool,
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Orders module menu for a model."""
    s = f":{k}" if k else ""
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.append([InlineKeyboardButton(text="➕ Заказ", callback_data=f"nlp:om:new{s}")])
    if has_orders:
        if can_edit:
            rows.append([InlineKeyboardButton(text="✅ Закрыть", callback_data=f"nlp:om:close{s}")])
        rows.append([InlineKeyboardButton(text="📄 Просмотр заказов", callback_data=f"nlp:om:view{s}")])
    else:
        rows.append([InlineKeyboardButton(text="📄 Нет заказов", callback_data="nlp:noop")])
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_orders_view_keyboard(page: int, total_pages: int, model_id: str) -> InlineKeyboardMarkup:
    """Orders view pagination + back."""
    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        pagination: list[InlineKeyboardButton] = []
        if page > 1:
            pagination.append(InlineKeyboardButton(text="⬅️", callback_data=f"nlp:op:{page - 1}"))
        if page < total_pages:
            pagination.append(InlineKeyboardButton(text="➡️", callback_data=f"nlp:op:{page + 1}"))
        if pagination:
            rows.append(pagination)
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_files_menu_keyboard(can_edit: bool, model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Files (accounting) module menu for a model."""
    s = f":{k}" if k else ""
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.append([InlineKeyboardButton(text="➕ добавить файлы", callback_data=f"nlp:fm:add{s}")])
        rows.append([InlineKeyboardButton(text="💬 обновить коммент", callback_data=f"nlp:fm:comment{s}")])
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_shoot_menu_keyboard(
    has_shoot: bool,
    can_edit: bool,
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Shoot module menu for a model."""
    s = f":{k}" if k else ""
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.append([InlineKeyboardButton(text="➕ Съёмка", callback_data=f"nlp:smn:new{s}")])
        if has_shoot:
            rows.append([
                InlineKeyboardButton(text="↩️ Перенести", callback_data=f"nlp:smn:reschedule{s}"),
                InlineKeyboardButton(text="✅ Закрыть", callback_data=f"nlp:smn:close{s}"),
            ])
            rows.append([
                InlineKeyboardButton(text="🗂 Content", callback_data=f"nlp:smn:content{s}"),
                InlineKeyboardButton(text="💬 Коммент", callback_data=f"nlp:smn:comment{s}"),
            ])
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_shoot_post_create_keyboard(
    shoot_id: str,
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Post-create shoot actions."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗂 Content", callback_data=f"nlp:sctm:{shoot_id}{s}"),
            InlineKeyboardButton(text="💬 Коммент", callback_data=f"nlp:scm:{shoot_id}{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


# ==================== NLP Order Keyboards ====================

def nlp_order_type_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Order type selection. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Кастом", callback_data=f"nlp:ot:custom{s}"),
            InlineKeyboardButton(text="Шорт", callback_data=f"nlp:ot:short{s}"),
        ],
        [
            InlineKeyboardButton(text="verif reddit", callback_data=f"nlp:ot:verif_reddit{s}"),
            InlineKeyboardButton(text="Колл", callback_data=f"nlp:ot:call{s}"),
        ],
        [
            InlineKeyboardButton(text="Ad Request", callback_data=f"nlp:ot:ad_request{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_order_qty_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Quantity selection. model_id + order_type in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data=f"nlp:oq:1{s}"),
            InlineKeyboardButton(text="2", callback_data=f"nlp:oq:2{s}"),
            InlineKeyboardButton(text="3", callback_data=f"nlp:oq:3{s}"),
            InlineKeyboardButton(text="+", callback_data=f"nlp:oq:custom{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_order_date_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Date selection for order creation. All context in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Сегодня", callback_data=f"nlp:od:today{s}"),
            InlineKeyboardButton(text="📅 Вчера", callback_data=f"nlp:od:yesterday{s}"),
        ],
        [
            InlineKeyboardButton(text="📅 Другая дата", callback_data=f"nlp:od:custom{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_order_confirm_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Confirmation after date selection. All context in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data=f"nlp:oc{s}")],
        [nlp_back_button(model_id)],
    ])


def nlp_disambiguate_keyboard(number: int, k: str = "") -> InlineKeyboardMarkup:
    """Disambiguate files vs orders. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📁 Добавить {number} файлов", callback_data=f"nlp:df:{number}{s}")],
        [InlineKeyboardButton(text=f"📦 Создать {number} заказов", callback_data=f"nlp:do:{number}{s}")],
        [_NLP_CANCEL_BTN],
    ])


def nlp_report_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Report detail buttons. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Детали Orders", callback_data=f"nlp:ro{s}"),
            InlineKeyboardButton(text="📁 Детали Accounting", callback_data=f"nlp:ra{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


# ==================== NLP Shoot Keyboards ====================

def nlp_shoot_date_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Date selection for shoot. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Завтра", callback_data=f"nlp:sd:tomorrow{s}"),
            InlineKeyboardButton(text="Послезавтра", callback_data=f"nlp:sd:day_after{s}"),
        ],
        [InlineKeyboardButton(text="📅 Другая дата", callback_data=f"nlp:sd:custom{s}")],
        [nlp_back_button(model_id)],
    ])


def nlp_shoot_location_keyboard(
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Location selection for shoot creation."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="home", callback_data=f"nlp:sl:home{s}"),
            InlineKeyboardButton(text="rent", callback_data=f"nlp:sl:rent{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_shoot_confirm_done_keyboard(shoot_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Confirm marking a shoot as done."""
    cb = f"nlp:sdc:{shoot_id}"
    if k:
        cb += f":{k}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=cb),
            InlineKeyboardButton(text="❌ Нет", callback_data="nlp:x:c"),
        ],
    ])


def nlp_shoot_select_keyboard(
    shoots: list,
    action: str,
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Select a shoot. action: done|reschedule|comment"""
    builder = InlineKeyboardBuilder()
    for shoot in shoots[:5]:
        date_str = shoot.date[:10] if shoot.date else "?"
        try:
            from datetime import date as _date
            d = _date.fromisoformat(date_str)
            label = d.strftime("%d.%m")
        except (ValueError, TypeError):
            label = date_str
        cb = f"nlp:ss:{action}:{shoot.page_id}"
        if k:
            cb += f":{k}"
        builder.row(InlineKeyboardButton(text=f"📅 {label}", callback_data=cb))
    if len(shoots) > 5:
        builder.row(InlineKeyboardButton(
            text=f"Показать ещё ({len(shoots) - 5})",
            callback_data=f"nlp:shm:{action}:5",
        ))
    builder.row(nlp_back_button(model_id))
    return builder.as_markup()


# ==================== NLP Shoot Content Types ====================

def nlp_shoot_content_keyboard(
    selected: list[str],
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Multi-select content types for shoot creation via NLP."""
    s = f":{k}" if k else ""
    builder = InlineKeyboardBuilder()

    # Группа 1: Основные типы
    row1 = []
    for ct in ["main", "new main", "basic"]:
        mark = "✓ " if ct in selected else ""
        row1.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:sct:{ct}{s}",
        ))
    builder.row(*row1)

    # Группа 2: Платформы
    row2 = []
    for ct in ["twitter", "reddit", "fansly"]:
        mark = "✓ " if ct in selected else ""
        row2.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:sct:{ct}{s}",
        ))
    builder.row(*row2)

    # Группа 3: Специальные
    row3 = []
    for ct in ["SFS", "posting", "event"]:
        mark = "✓ " if ct in selected else ""
        row3.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:sct:{ct}{s}",
        ))
    builder.row(*row3)

    builder.row(InlineKeyboardButton(text="✅ Готово", callback_data=f"nlp:scd:done{s}"))
    builder.row(nlp_back_button(model_id))
    return builder.as_markup()


# ==================== NLP Shoot Manage Keyboard ====================

def nlp_shoot_manage_keyboard(
    shoot_id: str,
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Manage nearest shoot: Done / Reschedule / Comment."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"nlp:sdc:{shoot_id}{s}"),
            InlineKeyboardButton(text="↩️ Перенести", callback_data=f"nlp:srs:{shoot_id}{s}"),
        ],
        [
            InlineKeyboardButton(text="🗂 Content", callback_data=f"nlp:sctm:{shoot_id}{s}"),
            InlineKeyboardButton(text="💬 Коммент", callback_data=f"nlp:scm:{shoot_id}{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


# ==================== NLP Close Order Keyboards ====================

def nlp_close_order_date_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Date for closing order. order_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Сегодня", callback_data=f"nlp:cd:today{s}"),
            InlineKeyboardButton(text="✓ Вчера", callback_data=f"nlp:cd:yesterday{s}"),
        ],
        [InlineKeyboardButton(text="📅 Другая дата", callback_data=f"nlp:cd:custom{s}")],
        [nlp_back_button(model_id)],
    ])


def nlp_close_order_select_keyboard(
    orders: list,
    page: int,
    total_pages: int,
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Select an order to close (paginated)."""
    builder = InlineKeyboardBuilder()
    for order in orders:
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
        cb = f"nlp:co:{order.page_id}"
        if k:
            cb += f":{k}"
        builder.row(InlineKeyboardButton(text=label, callback_data=cb))
    if total_pages > 1:
        pagination: list[InlineKeyboardButton] = []
        if page > 1:
            pagination.append(InlineKeyboardButton(text="⬅️", callback_data=f"nlp:cp:{page - 1}"))
        if page < total_pages:
            pagination.append(InlineKeyboardButton(text="➡️", callback_data=f"nlp:cp:{page + 1}"))
        if pagination:
            builder.row(*pagination)
    builder.row(nlp_back_button(model_id))
    return builder.as_markup()


# ==================== NLP Comment Keyboards ====================

def nlp_comment_target_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Select comment target. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Заказ", callback_data=f"nlp:ct:order{s}"),
            InlineKeyboardButton(text="📅 Съемка", callback_data=f"nlp:ct:shoot{s}"),
            InlineKeyboardButton(text="💰 Учет", callback_data=f"nlp:ct:account{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_comment_order_select_keyboard(
    orders: list,
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
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
        cb = f"nlp:cmo:{order.page_id}"
        if k:
            cb += f":{k}"
        builder.row(InlineKeyboardButton(text=label, callback_data=cb))
    builder.row(nlp_back_button(model_id))
    return builder.as_markup()


# ==================== NLP Files Keyboard ====================

def nlp_files_qty_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Quick file-count selection. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="20", callback_data=f"nlp:af:20{s}"),
            InlineKeyboardButton(text="50", callback_data=f"nlp:af:50{s}"),
            InlineKeyboardButton(text="80", callback_data=f"nlp:af:80{s}"),
            InlineKeyboardButton(text="Ввод", callback_data=f"nlp:af:custom{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_files_content_type_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Level 1 content-type menu for adding files in NLP flow."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Reddit", callback_data="nlp:fct:reddit"),
            InlineKeyboardButton(text="Twitter", callback_data="nlp:fct:twitter"),
        ],
        [
            InlineKeyboardButton(text="OF ▶", callback_data="nlp:fct:of"),
            InlineKeyboardButton(text="Extras ▶", callback_data="nlp:fct:extras"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_files_of_type_keyboard() -> InlineKeyboardMarkup:
    """Level 2 OF submenu for adding files."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Main Pack", callback_data="nlp:fct:main_pack"),
            InlineKeyboardButton(text="New Main", callback_data="nlp:fct:new_main"),
        ],
        [
            InlineKeyboardButton(text="Basic", callback_data="nlp:fct:basic"),
            InlineKeyboardButton(text="Event", callback_data="nlp:fct:event"),
        ],
        [InlineKeyboardButton(text="Request", callback_data="nlp:fct:request")],
        [InlineKeyboardButton(text="← Back", callback_data="nlp:fct:back")],
    ])


def nlp_files_extras_type_keyboard() -> InlineKeyboardMarkup:
    """Level 2 Extras submenu for adding files."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Fansly", callback_data="nlp:fct:fansly")],
        [
            InlineKeyboardButton(text="Instagram", callback_data="nlp:fct:instagram"),
            InlineKeyboardButton(text="Snapchat", callback_data="nlp:fct:snapchat"),
        ],
        [InlineKeyboardButton(text="← Back", callback_data="nlp:fct:back")],
    ])


# ==================== NLP Flow Control ====================

def nlp_flow_waiting_keyboard() -> InlineKeyboardMarkup:
    """Shown when user sends text while in nlp_* flow expecting buttons."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f3e0 Меню", callback_data="nlp:x:m"),
            InlineKeyboardButton(text="♻️ Сбросить", callback_data="nlp:x:c"),
        ],
    ])


def nlp_stale_keyboard() -> InlineKeyboardMarkup:
    """Shown when a stale/invalid callback is detected."""
    return InlineKeyboardMarkup(inline_keyboard=[])


def nlp_action_complete_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Post-action keyboard shown after every successful NLP action.

    Buttons:
      • «Еще действие»  → nlp:more_actions:{model_id}  (opens model card for next action)
      • «Готово»         → nlp:done:{model_id}          (removes keyboard, clears state)
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Еще действие",
            callback_data=f"nlp:more_actions:{model_id}",
        ),
        InlineKeyboardButton(
            text="Готово",
            callback_data=f"nlp:done:{model_id}",
        ),
    ]])


def nlp_not_found_keyboard(recent: list[tuple[str, str]], k: str = "") -> InlineKeyboardMarkup:
    """Model not found — recent models. Intent in memory."""
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for model_id, title in recent[:5]:
        cb = f"nlp:sm:{model_id}"
        if k:
            cb += f":{k}"
        row.append(InlineKeyboardButton(text=title, callback_data=cb))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(_NLP_CANCEL_BTN)
    return builder.as_markup()
