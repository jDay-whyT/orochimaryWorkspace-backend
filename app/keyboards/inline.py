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
#
# All NLP keyboards use SHORT callback_data (max ~55 bytes) to stay within
# Telegram's 64-byte limit.  Flow context (model_id, order_type, count …)
# is kept in memory_state; only the *new decision* goes into callback_data.
#
# Callback format:  nlp:{short_action}:{param}
#   sm  = select_model     ot  = order_type      oq  = order_qty
#   od  = order_date       oc  = order_confirm    sd  = shoot_date
#   sdc = shoot_done_conf  ss  = shoot_select     co  = close_order
#   cd  = close_date       ct  = comment_target   cmo = comment_order
#   df  = disambig_files   do  = disambig_orders  ro  = report_orders
#   ra  = report_account   af  = add_files        act = model_action
#   x   = cancel (c=cancel, m=menu)


_NLP_CANCEL_BTN = InlineKeyboardButton(text="❌ Отмена", callback_data="nlp:x:c")


def nlp_model_selection_keyboard(models: list[dict]) -> InlineKeyboardMarkup:
    """Model disambiguation. Intent is stored in memory_state by caller."""
    builder = InlineKeyboardBuilder()
    for model in models[:5]:
        builder.row(InlineKeyboardButton(
            text=model["name"], callback_data=f"nlp:sm:{model['id']}",
        ))
    builder.row(_NLP_CANCEL_BTN)
    return builder.as_markup()


def nlp_confirm_model_keyboard(model_id: str, model_name: str) -> InlineKeyboardMarkup:
    """Confirm fuzzy-matched model. Intent is stored in memory_state."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Да, {model_name}", callback_data=f"nlp:sm:{model_id}")],
        [InlineKeyboardButton(text="Нет", callback_data="nlp:x:c")],
    ])


def nlp_model_actions_keyboard() -> InlineKeyboardMarkup:
    """CRM action card shown after model context is set. model_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Заказ", callback_data="nlp:act:order"),
            InlineKeyboardButton(text="📁 Файлы", callback_data="nlp:act:files"),
        ],
        [
            InlineKeyboardButton(text="📅 Съемка", callback_data="nlp:act:shoot"),
            InlineKeyboardButton(text="📊 Репорт", callback_data="nlp:act:report"),
        ],
        [
            InlineKeyboardButton(text="📋 Заказы", callback_data="nlp:act:orders"),
            InlineKeyboardButton(text="✓ Закрыть", callback_data="nlp:act:close"),
        ],
        [_NLP_CANCEL_BTN],
    ])


# ==================== NLP Order Keyboards ====================

def nlp_order_type_keyboard() -> InlineKeyboardMarkup:
    """Order type selection. model_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Кастом", callback_data="nlp:ot:custom"),
            InlineKeyboardButton(text="Шорт", callback_data="nlp:ot:short"),
        ],
        [
            InlineKeyboardButton(text="Колл", callback_data="nlp:ot:call"),
            InlineKeyboardButton(text="Ad Request", callback_data="nlp:ot:ad request"),
        ],
        [_NLP_CANCEL_BTN],
    ])


def nlp_order_qty_keyboard() -> InlineKeyboardMarkup:
    """Quantity selection. model_id + order_type in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data="nlp:oq:1"),
            InlineKeyboardButton(text="2", callback_data="nlp:oq:2"),
            InlineKeyboardButton(text="3", callback_data="nlp:oq:3"),
            InlineKeyboardButton(text="5", callback_data="nlp:oq:5"),
        ],
        [_NLP_CANCEL_BTN],
    ])


def nlp_order_confirm_keyboard() -> InlineKeyboardMarkup:
    """Date + confirm for order. All context in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Сегодня", callback_data="nlp:od:today"),
            InlineKeyboardButton(text="📅 Вчера", callback_data="nlp:od:yesterday"),
        ],
        [
            InlineKeyboardButton(text="✅ Создать", callback_data="nlp:oc"),
            _NLP_CANCEL_BTN,
        ],
    ])


def nlp_disambiguate_keyboard(number: int) -> InlineKeyboardMarkup:
    """Disambiguate files vs orders. model_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📁 Добавить {number} файлов", callback_data=f"nlp:df:{number}")],
        [InlineKeyboardButton(text=f"📦 Создать {number} заказов", callback_data=f"nlp:do:{number}")],
        [_NLP_CANCEL_BTN],
    ])


def nlp_report_keyboard() -> InlineKeyboardMarkup:
    """Report detail buttons. model_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Детали Orders", callback_data="nlp:ro"),
            InlineKeyboardButton(text="📁 Детали Accounting", callback_data="nlp:ra"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="nlp:x:c")],
    ])


# ==================== NLP Shoot Keyboards ====================

def nlp_shoot_date_keyboard() -> InlineKeyboardMarkup:
    """Date selection for shoot. model_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Завтра", callback_data="nlp:sd:tomorrow"),
            InlineKeyboardButton(text="Послезавтра", callback_data="nlp:sd:day_after"),
        ],
        [InlineKeyboardButton(text="📅 Другая дата", callback_data="nlp:sd:custom")],
        [_NLP_CANCEL_BTN],
    ])


def nlp_shoot_confirm_done_keyboard(shoot_id: str) -> InlineKeyboardMarkup:
    """Confirm marking a shoot as done."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"nlp:sdc:{shoot_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="nlp:x:c"),
        ],
    ])


def nlp_shoot_select_keyboard(shoots: list, action: str) -> InlineKeyboardMarkup:
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
        builder.row(InlineKeyboardButton(
            text=f"📅 {label}",
            callback_data=f"nlp:ss:{action}:{shoot.page_id}",
        ))
    if len(shoots) > 5:
        builder.row(InlineKeyboardButton(
            text=f"Показать ещё ({len(shoots) - 5})",
            callback_data=f"nlp:shm:{action}:5",
        ))
    builder.row(_NLP_CANCEL_BTN)
    return builder.as_markup()


# ==================== NLP Close Order Keyboards ====================

def nlp_close_order_date_keyboard() -> InlineKeyboardMarkup:
    """Date for closing order. order_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✓ Сегодня", callback_data="nlp:cd:today"),
            InlineKeyboardButton(text="✓ Вчера", callback_data="nlp:cd:yesterday"),
        ],
        [
            InlineKeyboardButton(text="📅 Другая", callback_data="nlp:cd:custom"),
            _NLP_CANCEL_BTN,
        ],
    ])


def nlp_close_order_select_keyboard(orders: list) -> InlineKeyboardMarkup:
    """Select an order to close."""
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
        builder.row(InlineKeyboardButton(
            text=label, callback_data=f"nlp:co:{order.page_id}",
        ))
    if len(orders) > 5:
        builder.row(InlineKeyboardButton(
            text=f"Показать ещё ({len(orders) - 5})",
            callback_data="nlp:clm:5",
        ))
    builder.row(_NLP_CANCEL_BTN)
    return builder.as_markup()


# ==================== NLP Comment Keyboards ====================

def nlp_comment_target_keyboard() -> InlineKeyboardMarkup:
    """Select comment target. model_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Заказ", callback_data="nlp:ct:order"),
            InlineKeyboardButton(text="📅 Съемка", callback_data="nlp:ct:shoot"),
            InlineKeyboardButton(text="💰 Учет", callback_data="nlp:ct:account"),
        ],
        [_NLP_CANCEL_BTN],
    ])


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
        builder.row(InlineKeyboardButton(
            text=label, callback_data=f"nlp:cmo:{order.page_id}",
        ))
    builder.row(_NLP_CANCEL_BTN)
    return builder.as_markup()


# ==================== NLP Files Keyboard ====================

def nlp_files_qty_keyboard() -> InlineKeyboardMarkup:
    """Quick file-count selection. model_id in memory."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5", callback_data="nlp:af:5"),
            InlineKeyboardButton(text="10", callback_data="nlp:af:10"),
            InlineKeyboardButton(text="15", callback_data="nlp:af:15"),
            InlineKeyboardButton(text="20", callback_data="nlp:af:20"),
            InlineKeyboardButton(text="30", callback_data="nlp:af:30"),
        ],
        [_NLP_CANCEL_BTN],
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


def nlp_not_found_keyboard(recent: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Model not found — recent models. Intent in memory."""
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for model_id, title in recent[:5]:
        row.append(InlineKeyboardButton(
            text=title, callback_data=f"nlp:sm:{model_id}",
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(_NLP_CANCEL_BTN)
    return builder.as_markup()
