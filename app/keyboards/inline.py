from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.constants import ORDER_TYPES, PLANNER_CONTENT_OPTIONS, PLANNER_LOCATION_OPTIONS, NLP_SHOOT_CONTENT_TYPES, NLP_ACCOUNTING_CONTENT_TYPES
from app.utils.navigation import MODULE_ICONS, build_nav_buttons


def _section_label(prefix: str) -> str:
    names = {
        "orders": "Orders",
        "planner": "Planner",
        "account": "Accounting",
        "summary": "Summary",
    }
    return f"{MODULE_ICONS.get(prefix, '📁')} {names.get(prefix, 'Раздел')}"


def _with_token(callback_data: str, token: str = "") -> str:
    if token:
        return f"{callback_data}|{token}"
    return callback_data


def build_main_menu_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Unified bot main menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Заказы", callback_data=_with_token("order:menu", token)),
            InlineKeyboardButton(text="📂 Планер", callback_data=_with_token("planner:menu", token)),
            InlineKeyboardButton(text="📁 Файлы", callback_data=_with_token("files:menu", token)),
        ]
    ])


# ==================== Common ====================

def back_keyboard(callback_prefix: str, back_to: str = "main", token: str = "") -> InlineKeyboardMarkup:
    """Simple back button with customizable destination."""
    return InlineKeyboardMarkup(inline_keyboard=[
        build_nav_buttons(callback_prefix, _section_label(callback_prefix), back_to=back_to, section_to="menu", menu_to="main", token=token)
    ])


def cancel_keyboard(callback_prefix: str, token: str = "") -> InlineKeyboardMarkup:
    """Cancel button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✖ Cancel", callback_data=_with_token(f"{callback_prefix}|cancel|cancel", token))]
    ])


def back_cancel_keyboard(callback_prefix: str, token: str = "") -> InlineKeyboardMarkup:
    """Back and Cancel buttons."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️ Back", callback_data=_with_token(f"{callback_prefix}|back|back", token)),
            InlineKeyboardButton(text="✖ Cancel", callback_data=_with_token(f"{callback_prefix}|cancel|cancel", token)),
        ],
        build_nav_buttons(callback_prefix, _section_label(callback_prefix), token=token),
    ])


# ==================== Models Selection ====================

def models_keyboard(
    prefix: str,
    recent: list[tuple[str, str]] | None = None,
    show_back: bool = True,
    show_search: bool = False,
    back_to: str = "menu",
    token: str = "",
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
                callback_data=_with_token(f"{prefix}|select_model|{model_id}", token)
            ))
            if len(row) == 3:
                builder.row(*row)
                row = []
        if row:
            builder.row(*row)
    
    if show_search:
        builder.row(InlineKeyboardButton(
            text="🔍 Search",
            callback_data=_with_token(f"{prefix}|search|search", token)
        ))
    
    if show_back:
        builder.row(*build_nav_buttons(prefix, _section_label(prefix), back_to=back_to, token=token))
    
    return builder.as_markup()


def recent_models_keyboard(
    recent: list[tuple[str, str]],
    prefix: str,
    token: str = "",
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
            callback_data=_with_token(f"{prefix}|model|{model_id}", token)
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    
    # Search and Back
    builder.row(InlineKeyboardButton(text="🔍 Search", callback_data=_with_token(f"{prefix}|search|search", token)))
    builder.row(*build_nav_buttons(prefix, _section_label(prefix), back_to="menu", token=token))
    
    return builder.as_markup()


# ==================== Orders ====================

def orders_menu_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Orders section menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск модели", callback_data=_with_token("orders|search|search", token))],
        [
            InlineKeyboardButton(text="📋 Открытые", callback_data=_with_token("orders|open|list", token)),
            InlineKeyboardButton(text="➕ Новый заказ", callback_data=_with_token("orders|new|start", token)),
        ],
        build_nav_buttons("orders", _section_label("orders"), back_to="main", token=token),
    ])


def orders_list_keyboard(
    orders: list[dict[str, str]],
    page: int,
    total_pages: int,
    token: str = "",
) -> InlineKeyboardMarkup:
    """
    List of open orders with pagination.
    orders: [{"page_id": str, "label": str}, ...]
    """
    builder = InlineKeyboardBuilder()
    
    for order in orders:
        builder.row(InlineKeyboardButton(
            text=order["label"],
            callback_data=_with_token(f"orders|select|{order['page_id']}", token)
        ))
    
    # Pagination
    if total_pages > 1:
        pagination: list[InlineKeyboardButton] = []
        if page > 1:
            pagination.append(InlineKeyboardButton(
                text="◀ Prev", 
                callback_data=_with_token(f"orders|page|{page - 1}", token)
            ))
        if page < total_pages:
            pagination.append(InlineKeyboardButton(
                text="Next ▶", 
                callback_data=_with_token(f"orders|page|{page + 1}", token)
            ))
        if pagination:
            builder.row(*pagination)
    
    builder.row(*build_nav_buttons("orders", _section_label("orders"), back_to="model_select", token=token))
    
    return builder.as_markup()


def order_action_keyboard(page_id: str, token: str = "") -> InlineKeyboardMarkup:
    """Actions for a selected order."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Закрыть сегодня", callback_data=_with_token(f"orders|close_today_confirm|{page_id}", token)),
            InlineKeyboardButton(text="✅ Закрыть вчера", callback_data=_with_token(f"orders|close_yesterday_confirm|{page_id}", token)),
        ],
        [
            InlineKeyboardButton(text="💬 Коммент", callback_data=_with_token(f"orders|comment|{page_id}", token)),
        ],
        build_nav_buttons("orders", _section_label("orders"), back_to="list", token=token),
    ])


def order_close_confirm_keyboard(page_id: str, when: str, token: str = "") -> InlineKeyboardMarkup:
    """Inline confirmation before closing an order."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, закрыть", callback_data=_with_token(f"orders|close_{when}|{page_id}", token))],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=_with_token(f"orders|select|{page_id}", token))],
        build_nav_buttons("orders", _section_label("orders"), back_to="list", token=token),
    ])


def order_types_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Order type selection."""
    builder = InlineKeyboardBuilder()
    
    row: list[InlineKeyboardButton] = []
    for order_type in ORDER_TYPES:
        row.append(InlineKeyboardButton(
            text=order_type,
            callback_data=_with_token(f"orders|type|{order_type}", token)
        ))
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    
    builder.row(*build_nav_buttons("orders", _section_label("orders"), back_to="model", token=token))
    
    return builder.as_markup()


def order_qty_keyboard(current_qty: int = 1, token: str = "") -> InlineKeyboardMarkup:
    """Quantity selection for orders."""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="1", callback_data=_with_token("orders|qty|1", token)),
        InlineKeyboardButton(text="2", callback_data=_with_token("orders|qty|2", token)),
        InlineKeyboardButton(text="3", callback_data=_with_token("orders|qty|3", token)),
        InlineKeyboardButton(text="5", callback_data=_with_token("orders|qty|5", token)),
        InlineKeyboardButton(text="+", callback_data=_with_token("orders|qty|custom", token)),
    )
    
    builder.row(*build_nav_buttons("orders", _section_label("orders"), back_to="type", token=token))
    
    return builder.as_markup()


def order_date_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Date selection for order creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Today", callback_data=_with_token("orders|date|today", token)),
            InlineKeyboardButton(text="Yesterday", callback_data=_with_token("orders|date|yesterday", token)),
        ],
        [
            InlineKeyboardButton(text="◀️ Back", callback_data=_with_token("orders|back|qty", token)),
            InlineKeyboardButton(text="✖ Cancel", callback_data=_with_token("orders|cancel|cancel", token)),
        ],
        build_nav_buttons("orders", _section_label("orders"), back_to="qty", token=token),
    ])


def order_comment_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Comment prompt for order creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Skip", callback_data=_with_token("orders|comment_skip|skip", token)),
            InlineKeyboardButton(text="Add 💬", callback_data=_with_token("orders|comment_add|add", token)),
        ],
        [
            InlineKeyboardButton(text="◀️ Back", callback_data=_with_token("orders|back|date", token)),
            InlineKeyboardButton(text="✖ Cancel", callback_data=_with_token("orders|cancel|cancel", token)),
        ],
        build_nav_buttons("orders", _section_label("orders"), back_to="date", token=token),
    ])


def order_confirm_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Confirmation before creating order."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✓ Create", callback_data=_with_token("orders|confirm|create", token))],
        [
            InlineKeyboardButton(text="◀️ Back", callback_data=_with_token("orders|back|comment", token)),
            InlineKeyboardButton(text="✖ Cancel", callback_data=_with_token("orders|cancel|cancel", token)),
        ],
        build_nav_buttons("orders", _section_label("orders"), back_to="comment", token=token),
    ])


def order_success_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """After successful order creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ New order", callback_data=_with_token("orders|new|start", token)),
            InlineKeyboardButton(text="📋 Open orders", callback_data=_with_token("orders|open|list", token)),
        ],
        build_nav_buttons("orders", _section_label("orders"), back_to="menu", token=token),
    ])


def build_orders_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Final simplified orders menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Новый заказ", callback_data=_with_token("order:new", token)),
            InlineKeyboardButton(text="📂 Открытые", callback_data=_with_token("order:list", token)),
        ],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data=_with_token("menu", token))],
    ])


def build_order_card_keyboard(order_id: str, token: str = "") -> InlineKeyboardMarkup:
    """Order card actions for the new navigation scheme."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Информация", callback_data=_with_token(f"order:info:{order_id}", token))],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=_with_token(f"order:edit:{order_id}", token))],
        [
            InlineKeyboardButton(text="◀️ К списку", callback_data=_with_token("order:list", token)),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data=_with_token("menu", token)),
        ],
    ])


# ==================== Planner ====================

def planner_menu_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Planner section menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск модели", callback_data=_with_token("planner|search|search", token))],
        [
            InlineKeyboardButton(text="📋 Ближайшие", callback_data=_with_token("planner|upcoming|list", token)),
            InlineKeyboardButton(text="➕ Новая съёмка", callback_data=_with_token("planner|new|start", token)),
        ],
        build_nav_buttons("planner", _section_label("planner"), back_to="main", token=token),
    ])


def planner_content_keyboard(prefix: str, selected: list[str], token: str = "") -> InlineKeyboardMarkup:
    """Multi-select content for shoots."""
    builder = InlineKeyboardBuilder()
    
    row: list[InlineKeyboardButton] = []
    for option in PLANNER_CONTENT_OPTIONS:
        mark = "✓ " if option in selected else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{option}",
            callback_data=_with_token(f"{prefix}|content_toggle|{option}", token)
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    
    builder.row(InlineKeyboardButton(text="Next →", callback_data=_with_token(f"{prefix}|content_done|done", token)))
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data=_with_token(f"{prefix}|back|select_model", token)),
        InlineKeyboardButton(text="✖ Cancel", callback_data=_with_token(f"{prefix}|cancel|cancel", token)),
    )
    
    return builder.as_markup()


def planner_location_keyboard(prefix: str, token: str = "") -> InlineKeyboardMarkup:
    """Location selection for shoots."""
    builder = InlineKeyboardBuilder()
    
    for loc in PLANNER_LOCATION_OPTIONS:
        builder.add(InlineKeyboardButton(
            text=loc,
            callback_data=_with_token(f"{prefix}|location|{loc}", token)
        ))
    builder.adjust(2)
    
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data=_with_token(f"{prefix}|back|content", token)),
        InlineKeyboardButton(text="✖ Cancel", callback_data=_with_token(f"{prefix}|cancel|cancel", token)),
    )
    
    return builder.as_markup()


def planner_shoot_keyboard(page_id: str, token: str = "") -> InlineKeyboardMarkup:
    """Actions for a selected shoot."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Завершить", callback_data=_with_token(f"planner|done|{page_id}", token)),
            InlineKeyboardButton(text="📅 Перенести", callback_data=_with_token(f"planner|reschedule|{page_id}", token)),
            InlineKeyboardButton(text="🗑 Отменить", callback_data=_with_token(f"planner|cancel_confirm|{page_id}", token)),
        ],
        [
            InlineKeyboardButton(text="🗂 Content", callback_data=_with_token(f"planner|edit_content|{page_id}", token)),
            InlineKeyboardButton(text="💬 Коммент", callback_data=_with_token(f"planner|comment|{page_id}", token)),
        ],
        [InlineKeyboardButton(text="◀️ К списку", callback_data=_with_token("planner|upcoming|list", token))],
    ])


def planner_cancel_confirm_keyboard(page_id: str, token: str = "") -> InlineKeyboardMarkup:
    """Inline confirmation before cancelling a shoot."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data=_with_token(f"planner|cancel_shoot|{page_id}", token))],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=_with_token(f"planner|shoot|{page_id}", token))],
        [InlineKeyboardButton(text="◀️ К списку", callback_data=_with_token("planner|upcoming|list", token))],
    ])


def build_planner_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Главное меню планера."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Съёмка", callback_data=_with_token("planner:new", token)),
            InlineKeyboardButton(text="🖊️ Редактировать", callback_data=_with_token("planner:edit", token)),
        ],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data=_with_token("menu", token))],
    ])


def build_planner_edit_keyboard(shoot_id: str, token: str = "") -> InlineKeyboardMarkup:
    """Меню редактирования съёмки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Перенести", callback_data=_with_token(f"planner:move:{shoot_id}", token)),
            InlineKeyboardButton(text="🎨 Синтез", callback_data=_with_token(f"planner:synth:{shoot_id}", token)),
        ],
        [
            InlineKeyboardButton(text="💬 Комментарий", callback_data=_with_token(f"planner:comment:{shoot_id}", token)),
            InlineKeyboardButton(text="✅ Закрыть", callback_data=_with_token(f"planner:close:{shoot_id}", token)),
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data=_with_token("planner:menu", token)),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data=_with_token("menu", token)),
        ],
    ])


def build_files_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Главное меню файлов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Тек. месяц", callback_data=_with_token("files:stats", token)),
            InlineKeyboardButton(text="➕ Добавить", callback_data=_with_token("files:add", token)),
        ],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data=_with_token("menu", token))],
    ])


def build_files_add_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Меню добавления файла."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузка файлов", callback_data=_with_token("files:upload", token))],
        [InlineKeyboardButton(text="📂 Подбор типа", callback_data=_with_token("files:select_type", token))],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data=_with_token("files:menu", token)),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data=_with_token("menu", token)),
        ],
    ])


def build_file_type_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Выбор типа файла."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="custom", callback_data=_with_token("files:type:custom", token)),
            InlineKeyboardButton(text="short", callback_data=_with_token("files:type:short", token)),
        ],
        [
            InlineKeyboardButton(text="reel", callback_data=_with_token("files:type:reel", token)),
            InlineKeyboardButton(text="story", callback_data=_with_token("files:type:story", token)),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=_with_token("files:add", token))],
    ])


# ==================== Accounting ====================

def accounting_menu_keyboard(token: str = "") -> InlineKeyboardMarkup:
    """Accounting section menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск модели", callback_data=_with_token("account|search|search", token))],
        [
            InlineKeyboardButton(text="📋 Текущий месяц", callback_data=_with_token("account|current|list", token)),
            InlineKeyboardButton(text="➕ добавить файлы", callback_data=_with_token("account|add_files|start", token)),
        ],
        build_nav_buttons("account", _section_label("account"), back_to="main", token=token),
    ])


def accounting_quick_files_keyboard(page_id: str, current: int, token: str = "") -> InlineKeyboardMarkup:
    """Quick file count buttons."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5", callback_data=_with_token(f"account|files|{page_id}|5", token)),
            InlineKeyboardButton(text="10", callback_data=_with_token(f"account|files|{page_id}|10", token)),
            InlineKeyboardButton(text="15", callback_data=_with_token(f"account|files|{page_id}|15", token)),
            InlineKeyboardButton(text="20", callback_data=_with_token(f"account|files|{page_id}|20", token)),
        ],
        [InlineKeyboardButton(text="◀️ Back", callback_data=_with_token("account|back|list", token))],
    ])


def nlp_accounting_content_keyboard(
    selected: list[str],
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Multi-select content types for accounting Content property.
    Toggle ✅/⬜ for each option, plus Save and Back.
    """
    s = f":{k}" if k else ""
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for ct in NLP_ACCOUNTING_CONTENT_TYPES:
        mark = "✅ " if ct in selected else "⬜ "
        row.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:acct:{ct}{s}",
        ))
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
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
    "call": "call",
    "ad_request": "ad request",
}
ORDER_TYPE_CB_REVERSE = {v: k for k, v in ORDER_TYPE_CB_MAP.items()}

# Display names for order types (user-facing)
ORDER_TYPE_DISPLAY = {
    "custom": "Кастом",
    "short": "Шорт",
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
        [InlineKeyboardButton(text="♻️ Сброс", callback_data="nlp:x:c")],
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
        rows.append([InlineKeyboardButton(text="📄 Список заказов", callback_data=f"nlp:om:view{s}")])
    else:
        rows.append([InlineKeyboardButton(text="📄 Заказов нет", callback_data="nlp:noop")])
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
        rows.append([InlineKeyboardButton(text="🗂 тип (контент)", callback_data=f"nlp:fm:content{s}")])
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
            InlineKeyboardButton(text="Колл", callback_data=f"nlp:ot:call{s}"),
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
            InlineKeyboardButton(text="5", callback_data=f"nlp:oq:5{s}"),
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
    """Multi-select content types for shoot creation via NLP.
    Twitter/Reddit/Main/SFC/Posting/Fansly + ✅ Готово
    """
    s = f":{k}" if k else ""
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for ct in NLP_SHOOT_CONTENT_TYPES:
        mark = "✓ " if ct in selected else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{ct}",
            callback_data=f"nlp:sct:{ct}{s}",
        ))
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
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
            InlineKeyboardButton(text="+15", callback_data=f"nlp:af:15{s}"),
            InlineKeyboardButton(text="+30", callback_data=f"nlp:af:30{s}"),
            InlineKeyboardButton(text="+50", callback_data=f"nlp:af:50{s}"),
            InlineKeyboardButton(text="Ввод", callback_data=f"nlp:af:custom{s}"),
        ],
        [nlp_back_button(model_id)],
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
