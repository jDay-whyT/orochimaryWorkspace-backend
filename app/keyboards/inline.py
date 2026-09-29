from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


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

    builder.row(InlineKeyboardButton(text="✓ Create", callback_data=f"nlp:accs:save{s}"))
    builder.row(nlp_back_button(model_id))
    return builder.as_markup()


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

# Display names for order types (user-facing)
ORDER_TYPE_DISPLAY = {
    "custom": "Custom",
    "short": "Short",
    "verif reddit": "Verif Reddit",
    "verif_reddit": "Verif Reddit",
    "Verif Reddit": "Verif Reddit",
    "call": "Call",
    "ad_request": "Ad Request",
    "ad request": "Ad Request",
}


_NLP_CANCEL_BTN = InlineKeyboardButton(text="⬅ Back", callback_data="nlp:x:c")


def nlp_back_button(model_id: str) -> InlineKeyboardButton:
    """Stateless back button (model_id in callback)."""
    return InlineKeyboardButton(text="⬅ Back", callback_data=f"nlp:bk:{model_id}")


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
        [InlineKeyboardButton(text=f"Yes, {model_name}", callback_data=cb)],
        [InlineKeyboardButton(text="No", callback_data="nlp:x:c")],
    ])


def nlp_back_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Single back button to return to model card."""
    return InlineKeyboardMarkup(inline_keyboard=[[nlp_back_button(model_id)]])

def model_card_keyboard(k: str = "") -> InlineKeyboardMarkup:
    """
    Universal model card keyboard (CRM main scenario).

    Row 1: 📦 Orders | 📅 Shoot | 📁 Files
    Row 2: 📝 Note | ✓ Done
    """
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Orders", callback_data=f"nlp:act:orders{s}"),
            InlineKeyboardButton(text="📅 Shoot", callback_data=f"nlp:act:shoot{s}"),
            InlineKeyboardButton(text="📁 Files", callback_data=f"nlp:act:files{s}"),
        ],
        [
            InlineKeyboardButton(text="📝 Note", callback_data=f"nlp:act:note{s}"),
            InlineKeyboardButton(text="✓ Done", callback_data="nlp:x:c"),
        ],
    ])


_ORDER_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
OVERDUE_ORDER_DAYS = 3


def order_line(order, today) -> str:
    """'⚠️ short ×8 (5/8) · 22 Sep · 6d' — ⚠️ when open longer than OVERDUE_ORDER_DAYS."""
    from datetime import date as _date

    kind = order.order_type or "?"
    count = order.count or 0
    if kind in ("short", "verif reddit") and count:
        kind += f" ×{count} ({order.received or 0}/{count})"
    elif count > 1:
        kind += f" ×{count}"
    parts = [kind]
    days = None
    try:
        d = _date.fromisoformat((order.in_date or "")[:10])
        parts.append(f"{d.day} {_ORDER_MONTHS[d.month - 1]}")
        days = ((today or _date.today()) - d).days
        parts.append(f"{days}d")
    except ValueError:
        parts.append("no date")
    line = " · ".join(parts)
    return f"⚠️ {line}" if days is not None and days > OVERDUE_ORDER_DAYS else line


def nlp_orders_screen_keyboard(
    orders: list,
    page: int,
    total_pages: int,
    model_id: str,
    can_edit: bool,
    today=None,
) -> InlineKeyboardMarkup:
    """Orders screen: ➕ Order, then one button per open order (tap = close it), paging."""
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.append([InlineKeyboardButton(text="➕ Order", callback_data="nlp:om:new")])
        for order in orders:
            rows.append([InlineKeyboardButton(text=order_line(order, today), callback_data=f"nlp:co:{order.page_id}")])
    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"nlp:cp:{page - 1}"))
        if page < total_pages:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"nlp:cp:{page + 1}"))
        rows.append(nav)
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_files_menu_keyboard(can_edit: bool, model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Files (accounting) module menu for a model."""
    s = f":{k}" if k else ""
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.append([InlineKeyboardButton(text="+ Files", callback_data=f"nlp:fm:add{s}")])
        rows.append([InlineKeyboardButton(text="💬 Comment", callback_data=f"nlp:fm:comment{s}")])
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_shoot_menu_keyboard(
    can_edit: bool,
    model_id: str,
    picks: list[str] | None = None,
    actions: bool = False,
    from_list: bool = False,
    new_button: bool = True,
) -> InlineKeyboardMarkup:
    """Shoots of a model.

    picks   — date labels of upcoming shoots to choose from (several shoots);
    actions — show actions for the chosen shoot (one shoot, or one was picked);
    from_list — the shoot was picked from a list: offer the way back to it.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        if new_button:
            rows.append([InlineKeyboardButton(text="➕ New shoot", callback_data="nlp:smn:new")])
        if actions:
            rows.append([
                InlineKeyboardButton(text="✅ Shot done", callback_data="nlp:smn:close"),
                InlineKeyboardButton(text="✏️ Edit", callback_data="nlp:smn:edit"),
            ])
        elif picks:
            buttons = [InlineKeyboardButton(text=f"{label} ▸", callback_data=f"nlp:smn:pick{i}")
                       for i, label in enumerate(picks)]
            for i in range(0, len(buttons), 3):
                rows.append(buttons[i:i + 3])
    if from_list:
        rows.append([InlineKeyboardButton(text="← Shoots", callback_data="nlp:smn:list")])
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_shoot_edit_keyboard(has_date: bool) -> InlineKeyboardMarkup:
    """Edit a shoot: date, content, comment."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Date" if has_date else "📅 Set date", callback_data="nlp:smn:reschedule"),
            InlineKeyboardButton(text="🗂 Content", callback_data="nlp:smn:content"),
            InlineKeyboardButton(text="💬 Comment", callback_data="nlp:smn:comment"),
        ],
        [InlineKeyboardButton(text="← Back", callback_data="nlp:smn:view")],
    ])


def nlp_received_keyboard(remaining: int, model_id: str) -> InlineKeyboardMarkup:
    """Quick amounts for 'Add part' (typing a number still works)."""
    quick = [InlineKeyboardButton(text=f"+{n}", callback_data=f"nlp:prq:{n}") for n in (1, 2) if n < remaining]
    if remaining > 0:
        quick.append(InlineKeyboardButton(text=f"All remaining ({remaining})", callback_data=f"nlp:prq:{remaining}"))
    rows = [quick] if quick else []
    rows.append([nlp_back_button(model_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nlp_shoot_done_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yes, done", callback_data="nlp:smn:closeok"),
        InlineKeyboardButton(text="No", callback_data="nlp:smn:list"),
    ]])


# ==================== NLP Order Keyboards ====================

def nlp_order_type_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Order type selection. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Custom", callback_data=f"nlp:ot:custom{s}"),
            InlineKeyboardButton(text="Short", callback_data=f"nlp:ot:short{s}"),
        ],
        [
            InlineKeyboardButton(text="Verif Reddit", callback_data=f"nlp:ot:verif_reddit{s}"),
            InlineKeyboardButton(text="Call", callback_data=f"nlp:ot:call{s}"),
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
            InlineKeyboardButton(text="Today", callback_data=f"nlp:od:today{s}"),
            InlineKeyboardButton(text="Yesterday", callback_data=f"nlp:od:yesterday{s}"),
        ],
        [
            InlineKeyboardButton(text="📅 Other date", callback_data=f"nlp:od:custom{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_order_confirm_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Confirmation after date selection. All context in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✓ Create", callback_data=f"nlp:oc{s}")],
        [nlp_back_button(model_id)],
    ])


def nlp_report_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Report detail buttons. model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Orders details", callback_data=f"nlp:ro{s}"),
            InlineKeyboardButton(text="📁 Accounting details", callback_data=f"nlp:ra{s}"),
        ],
        [nlp_back_button(model_id)],
    ])


# ==================== NLP Shoot Keyboards ====================

def nlp_shoot_date_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """New date when rescheduling a shoot (or the first date of one without it). model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Today", callback_data=f"nlp:sd:today{s}"),
            InlineKeyboardButton(text="Tomorrow", callback_data=f"nlp:sd:tomorrow{s}"),
            InlineKeyboardButton(text="Day after", callback_data=f"nlp:sd:day_after{s}"),
        ],
        [InlineKeyboardButton(text="📅 Other date", callback_data=f"nlp:sd:custom{s}")],
        [nlp_back_button(model_id)],
    ])


def nlp_shoot_new_date_keyboard(model_id: str, today) -> InlineKeyboardMarkup:
    """First step of a new shoot: the day (or 'no date yet')."""
    from datetime import timedelta

    quick = [("Today", today), ("Tomorrow", today + timedelta(days=1)), ("Day after", today + timedelta(days=2))]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"nlp:sn:d:{d.isoformat()}") for label, d in quick],
        [InlineKeyboardButton(text="📅 Other date", callback_data="nlp:sn:custom")],
        [InlineKeyboardButton(text="❓ No date yet", callback_data="nlp:sn:nodate")],
        [nlp_back_button(model_id)],
    ])


def nlp_shoot_comment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Skip →", callback_data="nlp:sn:skip")],
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


# ==================== NLP Shoot Content Types ====================

def nlp_shoot_content_keyboard(
    selected: list[str],
    model_id: str,
    k: str = "",
) -> InlineKeyboardMarkup:
    """Multi-select content types for shoot creation via NLP."""
    s = f":{k}" if k else ""
    builder = InlineKeyboardBuilder()

    from app.utils.constants import NLP_SHOOT_CONTENT_TYPES

    # values are exactly the Planner `content` options
    types = list(NLP_SHOOT_CONTENT_TYPES)
    for i in range(0, len(types), 3):
        builder.row(*[
            InlineKeyboardButton(text=f"{'✓ ' if ct in selected else ''}{ct}", callback_data=f"nlp:sct:{ct}{s}")
            for ct in types[i:i + 3]
        ])

    builder.row(InlineKeyboardButton(text="✅ Done", callback_data=f"nlp:scd:done{s}"))
    builder.row(nlp_back_button(model_id))
    return builder.as_markup()


# ==================== NLP Close Order Keyboards ====================

def nlp_close_order_date_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Date for closing order. order_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Today", callback_data=f"nlp:cd:today{s}"),
            InlineKeyboardButton(text="Yesterday", callback_data=f"nlp:cd:yesterday{s}"),
        ],
        [InlineKeyboardButton(text="📅 Other date", callback_data=f"nlp:cd:custom{s}")],
        [nlp_back_button(model_id)],
    ])


def nlp_files_qty_keyboard(model_id: str, k: str = "") -> InlineKeyboardMarkup:
    """Quick file-count selection (second step, after the type). model_id in memory."""
    s = f":{k}" if k else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="20", callback_data=f"nlp:af:20{s}"),
            InlineKeyboardButton(text="50", callback_data=f"nlp:af:50{s}"),
            InlineKeyboardButton(text="80", callback_data=f"nlp:af:80{s}"),
            InlineKeyboardButton(text="Enter", callback_data=f"nlp:af:custom{s}"),
        ],
        [InlineKeyboardButton(text="← Back", callback_data=f"nlp:af:back{s}")],
    ])


def nlp_files_content_type_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """First step of adding files: the Accounting column (Request opens its kinds)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="OF", callback_data="nlp:fct:of"),
            InlineKeyboardButton(text="Reddit", callback_data="nlp:fct:reddit"),
            InlineKeyboardButton(text="Twitter", callback_data="nlp:fct:twitter"),
        ],
        [
            InlineKeyboardButton(text="Fansly", callback_data="nlp:fct:fansly"),
            InlineKeyboardButton(text="Request ▶", callback_data="nlp:fct:req"),
        ],
        [nlp_back_button(model_id)],
    ])


def nlp_files_request_type_keyboard() -> InlineKeyboardMarkup:
    """Kinds of requests: counted in request_files, the kind is tagged in Content."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Pornhub", callback_data="nlp:fct:pornhub"),
            InlineKeyboardButton(text="Instagram", callback_data="nlp:fct:instagram"),
            InlineKeyboardButton(text="Snapchat", callback_data="nlp:fct:snapchat"),
        ],
        [
            InlineKeyboardButton(text="Event", callback_data="nlp:fct:event"),
            InlineKeyboardButton(text="SFS", callback_data="nlp:fct:sfs"),
        ],
        [InlineKeyboardButton(text="Other request", callback_data="nlp:fct:request")],
        [InlineKeyboardButton(text="← Back", callback_data="nlp:fct:back")],
    ])


# ==================== NLP Flow Control ====================

def nlp_action_complete_keyboard(model_id: str) -> InlineKeyboardMarkup:
    """Post-action keyboard shown after every successful NLP action.

    Buttons:
      • «Еще действие»  → nlp:more_actions:{model_id}  (opens model card for next action)
      • «Готово»         → nlp:done:{model_id}          (removes keyboard, clears state)
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="+ More",
            callback_data=f"nlp:more_actions:{model_id}",
        ),
        InlineKeyboardButton(
            text="Done",
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
