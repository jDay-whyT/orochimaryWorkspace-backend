import html
import logging
from datetime import date, datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.keyboards import (
    close_date_keyboard,
    close_list_keyboard,
    close_keyboard,
    count_keyboard,
    date_keyboard,
    models_keyboard,
    qty_keyboard,
    skip_keyboard,
    types_keyboard,
)
from app.notion import NotionClient, NotionOrder
from app.state import MemoryState

LOGGER = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "/orders_create")
async def orders_create(message: Message, memory_state: MemoryState, config: Config) -> None:
    if not _is_editor(message.from_user.id, config):
        await message.answer("You have read-only access. Creating orders is disabled.")
        return
    memory_state.set(
        message.from_user.id,
        {
            "flow": "create",
            "step": "ask_model",
        },
    )
    await message.answer("Send model name to search in Notion.")


@router.message(F.text == "/orders_close")
async def orders_close(message: Message, memory_state: MemoryState, config: Config) -> None:
    if not _is_editor(message.from_user.id, config):
        await message.answer("Read-only mode: you can view open orders, but closing is disabled.")
    memory_state.set(
        message.from_user.id,
        {
            "flow": "close",
            "step": "ask_model",
        },
    )
    await message.answer("Send model name to search open orders.")


@router.message(F.text)
async def handle_text(message: Message, memory_state: MemoryState, config: Config, notion: NotionClient) -> None:
    data = memory_state.get(message.from_user.id)
    if not data:
        return
    step = data.get("step")
    text = message.text.strip()
    if step == "close_date_manual":
        close_date = _parse_date(text)
        if not close_date:
            await message.answer("Неверная дата, пример: 2026-01-28")
            return
        await _finalize_close_date(message, memory_state, config, notion, close_date)
        return
    if step == "ask_model":
        if not text:
            await message.answer("Please enter a model name.")
            return
        try:
            models = await notion.query_models(config.notion_models_db_id, text)
        except Exception:
            LOGGER.exception("Failed to query models from Notion")
            await message.answer("Notion error, try again.")
            return
        if not models:
            await message.answer("No models found. Try another name.")
            return
        model_options = {model_id: title for model_id, title in models}
        memory_state.update(message.from_user.id, step="pick_model", model_options=model_options)
        await message.answer("Pick a model:", reply_markup=models_keyboard(models))
        return
    if step == "qty_manual":
        qty = _parse_int(text)
        if not qty or qty <= 0:
            await message.answer("Please enter a positive number for qty.")
            return
        memory_state.update(message.from_user.id, qty=qty, step="ask_in_date")
        await message.answer("Select in date:", reply_markup=date_keyboard())
        return
    if step == "in_date_manual":
        in_date = _parse_date(text)
        if not in_date:
            await message.answer("Enter date in YYYY-MM-DD format.")
            return
        memory_state.update(message.from_user.id, in_date=in_date, step="ask_comments")
        await message.answer("Any comments?", reply_markup=skip_keyboard())
        return
    if step == "ask_comments":
        comments = text
        memory_state.update(message.from_user.id, comments=comments)
        await _continue_after_comments(message, memory_state, config, notion)
        return
    if step == "count_manual":
        count = _parse_int(text)
        if not count or count <= 0:
            await message.answer("Please enter a positive number for count.")
            return
        memory_state.update(message.from_user.id, count=count)
        await _create_orders(message, memory_state, config, notion)
        return


@router.callback_query(F.data.startswith("oc|"))
async def handle_callback(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    parts = query.data.split("|", 2)
    if len(parts) < 3:
        await query.answer()
        return
    _, action, value = parts
    data = memory_state.get(query.from_user.id) or {}
    if action == "model":
        model_options = data.get("model_options", {})
        title = model_options.get(value)
        if not title:
            await query.answer("Model expired. Search again.", show_alert=True)
            memory_state.update(query.from_user.id, step="ask_model")
            return
        flow = data.get("flow")
        memory_state.update(
            query.from_user.id,
            model_id=value,
            model_title=title,
            selected_model_id=value,
        )
        if flow == "create":
            memory_state.update(query.from_user.id, step="pick_type")
            await query.message.answer(
                f"Model selected: <b>{html.escape(title)}</b>\nPick order type:",
                reply_markup=types_keyboard(),
            )
        else:
            await _list_open_orders(query, memory_state, config, notion)
        await query.answer()
        return
    if action == "list":
        if value == "back":
            model_options = data.get("model_options", {})
            if not model_options:
                await query.answer("Search models again.", show_alert=True)
                memory_state.update(query.from_user.id, step="ask_model")
                return
            memory_state.update(query.from_user.id, step="pick_model")
            await query.message.answer("Pick a model:", reply_markup=models_keyboard(list(model_options.items())))
            await query.answer()
            return
        if value == "cancel":
            memory_state.clear(query.from_user.id)
            await query.message.answer("Canceled.")
            await query.answer()
            return
    if action == "type":
        memory_state.update(query.from_user.id, order_type=value, qty=1, step="ask_qty")
        await query.message.answer("Qty? (default 1)", reply_markup=qty_keyboard())
        await query.answer()
        return
    if action == "qty":
        if value == "enter":
            memory_state.update(query.from_user.id, step="qty_manual")
            await query.message.answer("Send qty number.")
        else:
            qty = _parse_int(value)
            if not qty:
                await query.answer("Invalid qty", show_alert=True)
                return
            memory_state.update(query.from_user.id, qty=qty, step="ask_in_date")
            await query.message.answer("Select in date:", reply_markup=date_keyboard())
        await query.answer()
        return
    if action == "date":
        if value == "enter":
            memory_state.update(query.from_user.id, step="in_date_manual")
            await query.message.answer("Send date in YYYY-MM-DD.")
        else:
            in_date = _resolve_relative_date(value, config)
            if not in_date:
                await query.answer("Invalid date", show_alert=True)
                return
            memory_state.update(query.from_user.id, in_date=in_date, step="ask_comments")
            await query.message.answer("Any comments?", reply_markup=skip_keyboard())
        await query.answer()
        return
    if action == "comment":
        if value == "skip":
            memory_state.update(query.from_user.id, comments=None)
        await _continue_after_comments(query.message, memory_state, config, notion)
        await query.answer()
        return
    if action == "count":
        if value == "enter":
            memory_state.update(query.from_user.id, step="count_manual")
            await query.message.answer("Send count number.")
        else:
            count = _parse_int(value)
            if not count:
                await query.answer("Invalid count", show_alert=True)
                return
            memory_state.update(query.from_user.id, count=count)
            await _create_orders(query.message, memory_state, config, notion)
        await query.answer()
        return
    if action == "close_today":
        if not _is_editor(query.from_user.id, config):
            await query.answer("Read-only access", show_alert=True)
            return
        close_date = _today(config)
        success = await _close_order(query, memory_state, config, notion, value, close_date)
        if success:
            await query.answer()
        return
    if action == "close_date":
        if not _is_editor(query.from_user.id, config):
            await query.answer("Read-only access", show_alert=True)
            return
        prompt = await query.message.answer(
            "Введи дату закрытия (YYYY-MM-DD) или нажми Today/Yesterday",
            reply_markup=close_date_keyboard(),
        )
        memory_state.update(
            query.from_user.id,
            step="close_date_manual",
            pending_close_page_id=value,
            pending_close_message_id=getattr(query.message, "message_id", None),
            pending_close_chat_id=getattr(getattr(query.message, "chat", None), "id", None),
            pending_prompt_message_id=getattr(prompt, "message_id", None),
            pending_prompt_chat_id=getattr(getattr(prompt, "chat", None), "id", None),
        )
        await query.answer()
        return
    if action == "close_date_pick":
        if not _is_editor(query.from_user.id, config):
            await query.answer("Read-only access", show_alert=True)
            return
        close_date = _resolve_relative_date(value, config)
        if not close_date:
            await query.answer("Invalid date", show_alert=True)
            return
        await _finalize_close_date(query.message, memory_state, config, notion, close_date)
        await query.answer()
        return
    if action == "close_date_back":
        await _clear_close_prompt(query, memory_state)
        await _return_to_open_orders(query, memory_state, config, notion)
        await query.answer()
        return
    if action == "close_date_cancel":
        await _clear_close_prompt(query, memory_state)
        memory_state.clear(query.from_user.id)
        await query.message.answer("Canceled.")
        await query.answer()
        return


async def _continue_after_comments(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    data = memory_state.get(message.from_user.id) or {}
    if data.get("order_type") == "short":
        memory_state.update(message.from_user.id, step="ask_count")
        await message.answer("Count?", reply_markup=count_keyboard())
        return
    memory_state.update(message.from_user.id, count=1)
    await _create_orders(message, memory_state, config, notion)


async def _create_orders(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    data = memory_state.get(message.from_user.id) or {}
    model_title = data.get("model_title")
    model_id = data.get("model_id")
    order_type = data.get("order_type")
    qty = data.get("qty", 1)
    in_date = data.get("in_date")
    count = data.get("count", 1)
    comments = data.get("comments")
    if not (model_id and order_type and in_date and model_title):
        await message.answer("Missing data. Start again with /orders_create.")
        memory_state.clear(message.from_user.id)
        return
    try:
        for idx in range(1, qty + 1):
            title = f"{order_type} {idx}/{qty} — {in_date.isoformat()}"
            await notion.create_order(
                config.notion_orders_db_id,
                model_id,
                order_type,
                in_date,
                count,
                title,
                comments,
            )
    except Exception:
        LOGGER.exception("Failed to create orders in Notion")
        await message.answer("Notion error, try again.")
        memory_state.clear(message.from_user.id)
        return
    memory_state.clear(message.from_user.id)
    await message.answer(f"Created {qty} orders for <b>{html.escape(model_title)}</b>.")


async def _list_open_orders(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    data = memory_state.get(query.from_user.id) or {}
    model_id = data.get("model_id")
    model_title = data.get("model_title")
    if not model_id:
        await query.message.answer("Select a model first.")
        return
    try:
        orders = await notion.query_open_orders(config.notion_orders_db_id, model_id)
    except Exception:
        LOGGER.exception("Failed to query open orders from Notion")
        await query.message.answer("Notion error, try again.")
        memory_state.clear(query.from_user.id)
        return
    if not orders:
        memory_state.clear(query.from_user.id)
        await query.message.answer("No open orders found.")
        return
    orders = sorted(orders, key=_order_sort_key)
    open_orders = {order.page_id: order.in_date for order in orders}
    memory_state.update(
        query.from_user.id,
        step="list_orders",
        open_orders=open_orders,
        selected_model_id=model_id,
        selected_model_title=model_title,
    )
    editor = _is_editor(query.from_user.id, config)
    await query.message.answer(
        f"Open orders for <b>{html.escape(model_title or '')}</b>:",
        reply_markup=close_list_keyboard(),
    )
    if editor:
        for order in orders:
            label_html = build_order_label_html(order.order_type, order.in_date)
            await query.message.answer(
                label_html,
                reply_markup=close_keyboard(order.page_id),
            )
    else:
        lines = [f"• {build_order_label_html(order.order_type, order.in_date)}" for order in orders]
        await query.message.answer("\n".join(lines))


def format_date_short(date_str: str) -> str:
    parsed = date.fromisoformat(date_str)
    months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    return f"{parsed.day} {months[parsed.month - 1]}"


def build_order_label_raw(order_type: str | None, in_date_str: str | None) -> str:
    safe_type = order_type or "order"
    if not in_date_str:
        return safe_type
    return f"{format_date_short(in_date_str)} · {safe_type}"


def build_order_label_html(order_type: str | None, in_date_str: str | None) -> str:
    return html.escape(build_order_label_raw(order_type, in_date_str))


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except (TypeError, ValueError):
            continue
    return None


def _resolve_relative_date(value: str, config: Config) -> date | None:
    today = _today(config)
    if value == "today":
        return today
    if value == "yesterday":
        return today - timedelta(days=1)
    return None


def _today(config: Config) -> date:
    return datetime.now(config.timezone).date()


def _is_editor(user_id: int, config: Config) -> bool:
    return user_id in config.allowed_editors


def _order_sort_key(order: NotionOrder) -> tuple[int, date]:
    if not order.in_date:
        return (1, date.max)
    parsed = _parse_date(order.in_date)
    if not parsed:
        return (1, date.max)
    return (0, parsed)


def _build_completion_message(in_date_str: str | None, close_date: date) -> str:
    if not in_date_str:
        return "Заказ выполнен ✅"
    in_date = _parse_date(in_date_str)
    if not in_date:
        return "Заказ выполнен ✅"
    days = (close_date - in_date).days + 1
    if days < 1:
        days = 1
    return f"Заказ выполнен за {days} дней"


async def _close_order(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    page_id: str,
    close_date: date,
) -> bool:
    try:
        await notion.close_order(page_id, close_date)
    except Exception:
        LOGGER.exception("Failed to close order in Notion")
        await query.answer("Notion error, try again.", show_alert=True)
        return False
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        LOGGER.error(
            "Telegram API error %s when clearing close keyboard: %s",
            getattr(exc, "status_code", "unknown"),
            str(exc),
        )
    except Exception:
        LOGGER.exception("Failed to clear close keyboard")
    data = memory_state.get(query.from_user.id) or {}
    open_orders = data.get("open_orders", {})
    in_date = open_orders.get(page_id) if isinstance(open_orders, dict) else None
    if isinstance(open_orders, dict):
        open_orders.pop(page_id, None)
        memory_state.update(query.from_user.id, open_orders=open_orders, step="list_orders")
    await query.message.answer(_build_completion_message(in_date, close_date))
    return True


async def _finalize_close_date(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    close_date: date,
) -> None:
    data = memory_state.get(message.from_user.id) or {}
    if not _is_editor(message.from_user.id, config):
        await message.answer("Read-only access")
        await _clear_pending_prompt_keyboard(message, data)
        memory_state.update(
            message.from_user.id,
            pending_close_page_id=None,
            pending_close_message_id=None,
            pending_close_chat_id=None,
            pending_prompt_message_id=None,
            pending_prompt_chat_id=None,
            step="list_orders",
        )
        return
    page_id = data.get("pending_close_page_id")
    if not page_id:
        await message.answer("No pending order to close.")
        return
    try:
        await notion.close_order(page_id, close_date)
    except Exception:
        LOGGER.exception("Failed to close order in Notion")
        await message.answer("Notion error, try again.")
        return
    await _clear_pending_prompt_keyboard(message, data)
    await _clear_pending_close_keyboard(message, data)
    open_orders = data.get("open_orders", {})
    in_date = open_orders.get(page_id) if isinstance(open_orders, dict) else None
    if isinstance(open_orders, dict):
        open_orders.pop(page_id, None)
    memory_state.update(
        message.from_user.id,
        open_orders=open_orders,
        pending_close_page_id=None,
        pending_close_message_id=None,
        pending_close_chat_id=None,
        pending_prompt_message_id=None,
        pending_prompt_chat_id=None,
        step="list_orders",
    )
    await message.answer(_build_completion_message(in_date, close_date))


async def _clear_pending_close_keyboard(message: Message, data: dict[str, Any]) -> None:
    chat_id = data.get("pending_close_chat_id")
    message_id = data.get("pending_close_message_id")
    if not chat_id or not message_id:
        return
    try:
        await message.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except TelegramAPIError as exc:
        LOGGER.error(
            "Telegram API error %s when clearing close keyboard: %s",
            getattr(exc, "status_code", "unknown"),
            str(exc),
        )
    except Exception:
        LOGGER.exception("Failed to clear close keyboard")


async def _clear_pending_prompt_keyboard(message: Message, data: dict[str, Any]) -> None:
    chat_id = data.get("pending_prompt_chat_id")
    message_id = data.get("pending_prompt_message_id")
    if not chat_id or not message_id:
        return
    try:
        await message.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except TelegramAPIError:
        LOGGER.warning("Failed to clear close date prompt keyboard")
    except Exception:
        LOGGER.exception("Failed to clear close date prompt keyboard")


async def _clear_close_prompt(query: CallbackQuery, memory_state: MemoryState) -> None:
    data = memory_state.get(query.from_user.id) or {}
    await _clear_pending_prompt_keyboard(query.message, data)
    memory_state.update(
        query.from_user.id,
        pending_close_page_id=None,
        pending_close_message_id=None,
        pending_close_chat_id=None,
        pending_prompt_message_id=None,
        pending_prompt_chat_id=None,
        step="list_orders",
    )


async def _return_to_open_orders(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    data = memory_state.get(query.from_user.id) or {}
    model_id = data.get("selected_model_id") or data.get("model_id")
    model_title = data.get("selected_model_title") or data.get("model_title")
    if not model_id:
        memory_state.update(query.from_user.id, step="ask_model")
        await query.message.answer("Send model name to search open orders.")
        return
    memory_state.update(query.from_user.id, model_id=model_id, model_title=model_title)
    await _list_open_orders(query, memory_state, config, notion)
