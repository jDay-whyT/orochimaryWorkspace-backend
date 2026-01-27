import html
import logging
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.keyboards import (
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
async def orders_create(message: Message, state: MemoryState, config: Config) -> None:
    if not _is_editor(message.from_user.id, config):
        await message.answer("You have read-only access. Creating orders is disabled.")
        return
    state.set(
        message.from_user.id,
        {
            "flow": "create",
            "step": "ask_model",
        },
    )
    await message.answer("Send model name to search in Notion.")


@router.message(F.text == "/orders_close")
async def orders_close(message: Message, state: MemoryState, config: Config) -> None:
    if not _is_editor(message.from_user.id, config):
        await message.answer("Read-only mode: you can view open orders, but closing is disabled.")
    state.set(
        message.from_user.id,
        {
            "flow": "close",
            "step": "ask_model",
        },
    )
    await message.answer("Send model name to search open orders.")


@router.message(F.text)
async def handle_text(message: Message, state: MemoryState, config: Config, notion: NotionClient) -> None:
    data = state.get(message.from_user.id)
    if not data:
        return
    step = data.get("step")
    text = message.text.strip()
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
        state.update(message.from_user.id, step="pick_model", model_options=model_options)
        await message.answer("Pick a model:", reply_markup=models_keyboard(models))
        return
    if step == "qty_manual":
        qty = _parse_int(text)
        if not qty or qty <= 0:
            await message.answer("Please enter a positive number for qty.")
            return
        state.update(message.from_user.id, qty=qty, step="ask_in_date")
        await message.answer("Select in date:", reply_markup=date_keyboard())
        return
    if step == "in_date_manual":
        in_date = _parse_date(text)
        if not in_date:
            await message.answer("Enter date in YYYY-MM-DD format.")
            return
        state.update(message.from_user.id, in_date=in_date, step="ask_comments")
        await message.answer("Any comments?", reply_markup=skip_keyboard())
        return
    if step == "ask_comments":
        comments = text
        state.update(message.from_user.id, comments=comments)
        await _continue_after_comments(message, state, config, notion)
        return
    if step == "count_manual":
        count = _parse_int(text)
        if not count or count <= 0:
            await message.answer("Please enter a positive number for count.")
            return
        state.update(message.from_user.id, count=count)
        await _create_orders(message, state, config, notion)
        return


@router.callback_query(F.data.startswith("oc|"))
async def handle_callback(query: CallbackQuery, state: MemoryState, config: Config, notion: NotionClient) -> None:
    parts = query.data.split("|", 2)
    if len(parts) < 3:
        await query.answer()
        return
    _, action, value = parts
    data = state.get(query.from_user.id) or {}
    if action == "model":
        model_options = data.get("model_options", {})
        title = model_options.get(value)
        if not title:
            await query.answer("Model expired. Search again.", show_alert=True)
            state.update(query.from_user.id, step="ask_model")
            return
        flow = data.get("flow")
        state.update(query.from_user.id, model_id=value, model_title=title)
        if flow == "create":
            state.update(query.from_user.id, step="pick_type")
            await query.message.answer(
                f"Model selected: <b>{html.escape(title)}</b>\nPick order type:",
                reply_markup=types_keyboard(),
            )
        else:
            await _list_open_orders(query, state, config, notion)
        await query.answer()
        return
    if action == "type":
        state.update(query.from_user.id, order_type=value, qty=1, step="ask_qty")
        await query.message.answer("Qty? (default 1)", reply_markup=qty_keyboard())
        await query.answer()
        return
    if action == "qty":
        if value == "enter":
            state.update(query.from_user.id, step="qty_manual")
            await query.message.answer("Send qty number.")
        else:
            qty = _parse_int(value)
            if not qty:
                await query.answer("Invalid qty", show_alert=True)
                return
            state.update(query.from_user.id, qty=qty, step="ask_in_date")
            await query.message.answer("Select in date:", reply_markup=date_keyboard())
        await query.answer()
        return
    if action == "date":
        if value == "enter":
            state.update(query.from_user.id, step="in_date_manual")
            await query.message.answer("Send date in YYYY-MM-DD.")
        else:
            in_date = _resolve_relative_date(value, config)
            if not in_date:
                await query.answer("Invalid date", show_alert=True)
                return
            state.update(query.from_user.id, in_date=in_date, step="ask_comments")
            await query.message.answer("Any comments?", reply_markup=skip_keyboard())
        await query.answer()
        return
    if action == "comment":
        if value == "skip":
            state.update(query.from_user.id, comments=None)
        await _continue_after_comments(query.message, state, config, notion)
        await query.answer()
        return
    if action == "count":
        if value == "enter":
            state.update(query.from_user.id, step="count_manual")
            await query.message.answer("Send count number.")
        else:
            count = _parse_int(value)
            if not count:
                await query.answer("Invalid count", show_alert=True)
                return
            state.update(query.from_user.id, count=count)
            await _create_orders(query.message, state, config, notion)
        await query.answer()
        return
    if action == "close":
        if not _is_editor(query.from_user.id, config):
            await query.answer("Read-only access", show_alert=True)
            return
        try:
            await notion.close_order(value, _today(config))
        except Exception:
            LOGGER.exception("Failed to close order in Notion")
            await query.answer("Notion error, try again.", show_alert=True)
            return
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
        await query.message.answer("Order closed.")
        await query.answer()
        return


async def _continue_after_comments(message: Message, state: MemoryState, config: Config, notion: NotionClient) -> None:
    data = state.get(message.from_user.id) or {}
    if data.get("order_type") == "short":
        state.update(message.from_user.id, step="ask_count")
        await message.answer("Count?", reply_markup=count_keyboard())
        return
    state.update(message.from_user.id, count=1)
    await _create_orders(message, state, config, notion)


async def _create_orders(message: Message, state: MemoryState, config: Config, notion: NotionClient) -> None:
    data = state.get(message.from_user.id) or {}
    model_title = data.get("model_title")
    model_id = data.get("model_id")
    order_type = data.get("order_type")
    qty = data.get("qty", 1)
    in_date = data.get("in_date")
    count = data.get("count", 1)
    comments = data.get("comments")
    if not (model_id and order_type and in_date and model_title):
        await message.answer("Missing data. Start again with /orders_create.")
        state.clear(message.from_user.id)
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
        state.clear(message.from_user.id)
        return
    state.clear(message.from_user.id)
    await message.answer(f"Created {qty} orders for <b>{html.escape(model_title)}</b>.")


async def _list_open_orders(query: CallbackQuery, state: MemoryState, config: Config, notion: NotionClient) -> None:
    data = state.get(query.from_user.id) or {}
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
        state.clear(query.from_user.id)
        return
    if not orders:
        state.clear(query.from_user.id)
        await query.message.answer("No open orders found.")
        return
    editor = _is_editor(query.from_user.id, config)
    await query.message.answer(
        f"Open orders for <b>{html.escape(model_title or '')}</b>:",
    )
    if editor:
        for order in orders:
            await query.message.answer(_format_order(order), reply_markup=close_keyboard(order.page_id))
    else:
        lines = [f"• {_format_order(order)}" for order in orders]
        await query.message.answer("\n".join(lines))
    state.clear(query.from_user.id)


def _format_order(order: NotionOrder) -> str:
    in_part = order.in_date or ""
    type_part = order.order_type or ""
    return f"{html.escape(order.title)} ({html.escape(type_part)}) {html.escape(in_part)}"


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
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
