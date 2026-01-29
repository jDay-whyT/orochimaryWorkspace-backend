import html
import logging
from datetime import date, datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.keyboards import (
    close_list_keyboard,
    close_action_keyboard,
    close_date_keyboard_min,
    comment_keyboard,
    date_keyboard,
    models_keyboard,
    skip_keyboard,
    types_keyboard,
)
from app.notion import NotionClient, NotionOrder
from app.state import MemoryState

LOGGER = logging.getLogger(__name__)
router = Router()
CLOSE_PAGE_SIZE = 5


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
    screen = await message.answer("Модель?", reply_markup=close_list_keyboard([], 1, 1))
    memory_state.set(
        message.from_user.id,
        {
            "flow": "close",
            "mode": "close_search",
            "screen_chat_id": screen.chat.id,
            "screen_message_id": screen.message_id,
        },
    )


@router.message(F.text)
async def handle_text(message: Message, memory_state: MemoryState, config: Config, notion: NotionClient) -> None:
    data = memory_state.get(message.from_user.id)
    if not data:
        return
    text = message.text.strip()
    flow = data.get("flow")
    if flow == "close":
        mode = data.get("mode")
        if mode == "close_search":
            if not text:
                await _edit_screen_from_message(
                    message,
                    memory_state,
                    "Модель?",
                    reply_markup=close_list_keyboard([], 1, 1),
                    mode="close_search",
                )
                return
            try:
                models = await notion.query_models(config.notion_models_db_id, text)
            except Exception:
                LOGGER.exception("Failed to query models from Notion")
                await _edit_screen_from_message(
                    message,
                    memory_state,
                    "Notion error, try again.",
                    reply_markup=close_list_keyboard([], 1, 1),
                    mode="close_search",
                )
                return
            if not models:
                await _edit_screen_from_message(
                    message,
                    memory_state,
                    "Модель не найдена. Попробуй еще раз.",
                    reply_markup=close_list_keyboard([], 1, 1),
                    mode="close_search",
                )
                return
            model_options = {model_id: title for model_id, title in models}
            await _edit_screen_from_message(
                message,
                memory_state,
                "Выбери модель:",
                reply_markup=models_keyboard(models, prefix="oclose"),
                mode="close_pick_model",
                model_options=model_options,
            )
            return
        if mode == "close_date_manual":
            close_date = _parse_date(text)
            if not close_date:
                await _edit_screen_from_message(
                    message,
                    memory_state,
                    "Неверная дата. Пример: 2026-01-28",
                    reply_markup=close_date_keyboard_min(),
                    mode="close_date_manual",
                )
                return
            await _finalize_close_action(message, memory_state, config, notion, close_date)
            return
        if mode == "close_comment_manual":
            comment_text = text.strip()
            if not comment_text:
                await _edit_screen_from_message(
                    message,
                    memory_state,
                    "Комментарий не может быть пустым.",
                    reply_markup=comment_keyboard(),
                    mode="close_comment_manual",
                )
                return
            await _save_order_comment(message, memory_state, config, notion, comment_text)
            return
        await _edit_screen_from_message(
            message,
            memory_state,
            "Сессия устарела. Запусти /orders_close заново.",
            reply_markup=None,
        )
        memory_state.clear(message.from_user.id)
        return
    step = data.get("step")
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
        await message.answer("Pick a model:", reply_markup=models_keyboard(models, prefix="ocreate"))
        return
    if step == "ask_qty":
        lowered = text.lower()
        if not lowered or lowered == "skip":
            qty = 1
        else:
            qty = _parse_int(text)
            if not qty or not 1 <= qty <= 50:
                await message.answer("Send qty number (1..50) or 'skip'.")
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
        comments = None if text.lower() == "skip" else text
        memory_state.update(message.from_user.id, comments=comments)
        await _continue_after_comments(message, memory_state, config, notion)
        return
    if step == "ask_count":
        count = _parse_int(text)
        if not count or not 1 <= count <= 999:
            await message.answer("Send count number (1..999).")
            return
        memory_state.update(message.from_user.id, count=count)
        await _create_orders(message, memory_state, config, notion)
        return
    await message.answer("Session expired. Run /orders_create again.")
    memory_state.clear(message.from_user.id)


@router.callback_query(F.data.startswith("oclose|"))
async def handle_close_callback(
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
    flow = data.get("flow")
    close_actions = {
        "list_back",
        "page",
        "pick_order",
        "action_back",
        "close_today",
        "close_date",
        "close_date_pick",
        "close_date_back",
        "comment",
        "comment_back",
        "cancel",
    }
    if flow != "close" and action in close_actions:
        await _expire_close_session(query, memory_state)
        await query.answer()
        return
    if action == "model":
        if flow != "close":
            await _expire_close_session(query, memory_state)
            await query.answer()
            return
        model_options = data.get("model_options", {})
        title = model_options.get(value)
        if not title:
            await query.answer("Model expired. Search again.", show_alert=True)
            await _expire_close_session(query, memory_state)
            return
        memory_state.update(query.from_user.id, model_id=value, model_title=title, selected_model_id=value)
        memory_state.update(
            query.from_user.id,
            selected_model_title=title,
            current_page=1,
            mode="close_list",
        )
        await _show_open_orders_screen(
            query.message,
            memory_state,
            config,
            notion,
            user_id=query.from_user.id,
        )
        await query.answer()
        return
    if flow == "close" and action in close_actions:
        if action == "list_back":
            model_options = data.get("model_options", {})
            if not model_options:
                await _edit_screen_from_callback(
                    query,
                    memory_state,
                    "Модель?",
                    reply_markup=close_list_keyboard([], 1, 1),
                    mode="close_search",
                )
                await query.answer()
                return
            await _edit_screen_from_callback(
                query,
                memory_state,
                "Выбери модель:",
                reply_markup=models_keyboard(list(model_options.items()), prefix="oclose"),
                mode="close_pick_model",
            )
            await query.answer()
            return
        if action == "page":
            page = _parse_int(value)
            if not page:
                await query.answer()
                return
            memory_state.update(query.from_user.id, current_page=page, mode="close_list")
            await _show_open_orders_screen(
                query.message,
                memory_state,
                config,
                notion,
                user_id=query.from_user.id,
            )
            await query.answer()
            return
        if action == "pick_order":
            await _show_action_screen(
                query.message,
                memory_state,
                config,
                notion,
                value,
                user_id=query.from_user.id,
            )
            await query.answer()
            return
        if action == "action_back":
            memory_state.update(query.from_user.id, mode="close_list")
            await _show_open_orders_screen(
                query.message,
                memory_state,
                config,
                notion,
                user_id=query.from_user.id,
            )
            await query.answer()
            return
        if action == "close_today":
            if not _is_editor(query.from_user.id, config):
                await query.answer("Read-only access", show_alert=True)
                return
            close_date = _today(config)
            await _finalize_close_action(
                query.message,
                memory_state,
                config,
                notion,
                close_date,
                page_id=value,
                user_id=query.from_user.id,
            )
            await query.answer()
            return
        if action == "close_date":
            if not _is_editor(query.from_user.id, config):
                await query.answer("Read-only access", show_alert=True)
                return
            memory_state.update(query.from_user.id, selected_order_page_id=value, mode="close_date_manual")
            await _edit_screen_from_callback(
                query,
                memory_state,
                "Введи дату закрытия (YYYY-MM-DD) или нажми Today/Yesterday",
                reply_markup=close_date_keyboard_min(),
            )
            await query.answer()
            return
        if action == "close_date_pick":
            close_date = _resolve_relative_date(value, config)
            if not close_date:
                await query.answer("Invalid date", show_alert=True)
                return
            await _finalize_close_action(
                query.message,
                memory_state,
                config,
                notion,
                close_date,
                user_id=query.from_user.id,
            )
            await query.answer()
            return
        if action == "close_date_back":
            await _show_action_screen(
                query.message,
                memory_state,
                config,
                notion,
                data.get("selected_order_page_id"),
                user_id=query.from_user.id,
            )
            await query.answer()
            return
        if action == "comment":
            if not _is_editor(query.from_user.id, config):
                await query.answer("Read-only access", show_alert=True)
                return
            memory_state.update(query.from_user.id, selected_order_page_id=value, mode="close_comment_manual")
            await _edit_screen_from_callback(
                query,
                memory_state,
                "Комментарий:",
                reply_markup=comment_keyboard(),
            )
            await query.answer()
            return
        if action == "comment_back":
            await _show_action_screen(
                query.message,
                memory_state,
                config,
                notion,
                data.get("selected_order_page_id"),
                user_id=query.from_user.id,
            )
            await query.answer()
            return
        if action == "cancel":
            await _edit_screen_from_callback(query, memory_state, "Отменено.", reply_markup=None)
            memory_state.clear(query.from_user.id)
            await query.answer()
            return
        await query.answer()
        return
    await query.answer()


@router.callback_query(F.data.startswith("ocreate|"))
async def handle_create_callback(
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
    flow = data.get("flow")
    if flow != "create":
        await _expire_create_session(query, memory_state)
        await query.answer()
        return
    if action == "model":
        model_options = data.get("model_options", {})
        title = model_options.get(value)
        if not title:
            await _expire_create_session(query, memory_state)
            await query.answer()
            return
        memory_state.update(query.from_user.id, model_id=value, model_title=title, selected_model_id=value)
        memory_state.update(query.from_user.id, step="pick_type")
        await query.message.answer(
            f"Model selected: <b>{html.escape(title)}</b>\nPick order type:",
            reply_markup=types_keyboard(),
        )
        await query.answer()
        return
    if action == "type":
        memory_state.update(query.from_user.id, order_type=value, qty=1, step="ask_qty")
        await query.message.answer("Qty? (default 1). Send a number or 'skip'.")
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
    await query.answer()


async def _continue_after_comments(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
) -> None:
    data = memory_state.get(message.from_user.id) or {}
    if data.get("order_type") == "short":
        memory_state.update(message.from_user.id, step="ask_count")
        await message.answer("Count? Send a number.")
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
        await message.answer("Session expired. Run /orders_create again.")
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


async def _edit_screen_from_message(
    message: Message,
    memory_state: MemoryState,
    text: str,
    reply_markup: Any | None = None,
    user_id: int | None = None,
    **updates: Any,
) -> None:
    target_user_id = user_id or message.from_user.id
    data = memory_state.get(target_user_id) or {}
    screen_chat_id = data.get("screen_chat_id")
    screen_message_id = data.get("screen_message_id")
    created_new = False
    if not screen_chat_id or not screen_message_id:
        if message.from_user and message.from_user.id != target_user_id:
            screen_chat_id = message.chat.id
            screen_message_id = message.message_id
        else:
            screen = await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
            screen_chat_id = screen.chat.id
            screen_message_id = screen.message_id
            created_new = True
    if screen_chat_id and screen_message_id and not created_new:
        try:
            await message.bot.edit_message_text(
                chat_id=screen_chat_id,
                message_id=screen_message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except TelegramAPIError as exc:
            LOGGER.error(
                "Telegram API error %s when editing screen: %s",
                getattr(exc, "status_code", "unknown"),
                str(exc),
            )
    memory_state.update(
        target_user_id,
        screen_chat_id=screen_chat_id,
        screen_message_id=screen_message_id,
        **updates,
    )


async def _edit_screen_from_callback(
    query: CallbackQuery,
    memory_state: MemoryState,
    text: str,
    reply_markup: Any | None = None,
    **updates: Any,
) -> None:
    user_id = query.from_user.id
    data = memory_state.get(user_id) or {}
    screen_chat_id = data.get("screen_chat_id") or getattr(getattr(query.message, "chat", None), "id", None)
    screen_message_id = data.get("screen_message_id") or getattr(query.message, "message_id", None)
    if not screen_chat_id or not screen_message_id:
        return
    try:
        await query.message.bot.edit_message_text(
            chat_id=screen_chat_id,
            message_id=screen_message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except TelegramAPIError as exc:
        LOGGER.error(
            "Telegram API error %s when editing screen: %s",
            getattr(exc, "status_code", "unknown"),
            str(exc),
        )
    memory_state.update(
        user_id,
        screen_chat_id=screen_chat_id,
        screen_message_id=screen_message_id,
        **updates,
    )


async def _expire_close_session(query: CallbackQuery, memory_state: MemoryState) -> None:
    await _edit_screen_from_callback(
        query,
        memory_state,
        "Сессия устарела. Запусти /orders_close заново.",
        reply_markup=None,
    )
    memory_state.clear(query.from_user.id)


async def _expire_create_session(query: CallbackQuery, memory_state: MemoryState) -> None:
    if query.message:
        await query.message.answer("Session expired. Run /orders_create again.")
    memory_state.clear(query.from_user.id)


def _build_orders_payload(orders: list[NotionOrder]) -> list[dict[str, str | None]]:
    return [
        {
            "page_id": order.page_id,
            "label": build_order_label_raw(order.order_type, order.in_date),
            "in_date": order.in_date,
            "order_type": order.order_type,
        }
        for order in orders
    ]


async def _show_open_orders_screen(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    user_id: int | None = None,
) -> None:
    target_user_id = user_id or message.from_user.id
    data = memory_state.get(target_user_id) or {}
    model_id = data.get("selected_model_id") or data.get("model_id")
    model_title = data.get("selected_model_title") or data.get("model_title")
    if not model_id or not model_title:
        await _edit_screen_from_message(
            message,
            memory_state,
            "Сессия устарела. Запусти /orders_close заново.",
            reply_markup=None,
            user_id=target_user_id,
        )
        memory_state.clear(target_user_id)
        return
    try:
        orders = await notion.query_open_orders(config.notion_orders_db_id, model_id)
    except Exception:
        LOGGER.exception("Failed to query open orders from Notion")
        await _edit_screen_from_message(
            message,
            memory_state,
            "Notion error, try again.",
            reply_markup=None,
            user_id=target_user_id,
        )
        memory_state.clear(target_user_id)
        return
    orders = sorted(orders, key=_order_sort_key)
    open_orders = _build_orders_payload(orders)
    if not open_orders:
        await _edit_screen_from_message(
            message,
            memory_state,
            "Открытых нет ✅",
            reply_markup=close_list_keyboard([], 1, 1),
            user_id=target_user_id,
            mode="close_list",
            open_orders=open_orders,
            current_page=1,
            selected_model_id=model_id,
            selected_model_title=model_title,
        )
        return
    page = data.get("current_page", 1)
    total_pages = max(1, (len(open_orders) + CLOSE_PAGE_SIZE - 1) // CLOSE_PAGE_SIZE)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * CLOSE_PAGE_SIZE
    orders_page = open_orders[start : start + CLOSE_PAGE_SIZE]
    header = f"Открытые: {html.escape(model_title)} (page {page}/{total_pages})"
    await _edit_screen_from_message(
        message,
        memory_state,
        header,
        reply_markup=close_list_keyboard(orders_page, page, total_pages),
        user_id=target_user_id,
        mode="close_list",
        open_orders=open_orders,
        current_page=page,
        selected_model_id=model_id,
        selected_model_title=model_title,
    )


async def _show_action_screen(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    page_id: str | None,
    user_id: int | None = None,
) -> None:
    target_user_id = user_id or message.from_user.id
    data = memory_state.get(target_user_id) or {}
    if not page_id:
        await _edit_screen_from_message(
            message,
            memory_state,
            "Сессия устарела. Запусти /orders_close заново.",
            reply_markup=None,
            user_id=target_user_id,
        )
        memory_state.clear(target_user_id)
        return
    order = _find_order(data.get("open_orders", []), page_id)
    if not order:
        await _show_open_orders_screen(message, memory_state, config, notion, user_id=target_user_id)
        return
    label = order["label"]
    await _edit_screen_from_message(
        message,
        memory_state,
        f"{html.escape(label)}\n\nВыбери действие",
        reply_markup=close_action_keyboard(page_id),
        user_id=target_user_id,
        mode="close_action",
        selected_order_page_id=page_id,
        selected_order_label=label,
    )


def _find_order(open_orders: list[dict[str, str | None]], page_id: str) -> dict[str, str | None] | None:
    for order in open_orders:
        if order.get("page_id") == page_id:
            return order
    return None


async def _finalize_close_action(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    close_date: date,
    page_id: str | None = None,
    user_id: int | None = None,
) -> None:
    target_user_id = user_id or message.from_user.id
    if not _is_editor(target_user_id, config):
        await _edit_screen_from_message(
            message,
            memory_state,
            "Read-only access.",
            reply_markup=None,
            user_id=target_user_id,
        )
        return
    data = memory_state.get(target_user_id) or {}
    target_page_id = page_id or data.get("selected_order_page_id")
    if not target_page_id:
        await _edit_screen_from_message(
            message,
            memory_state,
            "Сессия устарела. Запусти /orders_close заново.",
            reply_markup=None,
            user_id=target_user_id,
        )
        memory_state.clear(target_user_id)
        return
    order = _find_order(data.get("open_orders", []), target_page_id)
    in_date = order.get("in_date") if order else None
    try:
        await notion.close_order(target_page_id, close_date)
    except Exception:
        LOGGER.exception("Failed to close order in Notion")
        await _edit_screen_from_message(
            message,
            memory_state,
            "Notion error, try again.",
            reply_markup=None,
            user_id=target_user_id,
        )
        return
    completion = _build_completion_message(in_date, close_date)
    await _edit_screen_from_message(message, memory_state, completion, reply_markup=None, user_id=target_user_id)
    await _show_open_orders_screen(message, memory_state, config, notion, user_id=target_user_id)


async def _save_order_comment(
    message: Message,
    memory_state: MemoryState,
    config: Config,
    notion: NotionClient,
    comment_text: str,
    user_id: int | None = None,
) -> None:
    target_user_id = user_id or message.from_user.id
    if not _is_editor(target_user_id, config):
        await _edit_screen_from_message(
            message,
            memory_state,
            "Read-only access.",
            reply_markup=None,
            user_id=target_user_id,
        )
        return
    data = memory_state.get(target_user_id) or {}
    page_id = data.get("selected_order_page_id")
    if not page_id:
        await _edit_screen_from_message(
            message,
            memory_state,
            "Сессия устарела. Запусти /orders_close заново.",
            reply_markup=None,
            user_id=target_user_id,
        )
        memory_state.clear(target_user_id)
        return
    try:
        await notion.update_order(
            page_id,
            {"comments": {"rich_text": [{"text": {"content": comment_text}}]}},
        )
    except Exception:
        LOGGER.exception("Failed to update order comment in Notion")
        await _edit_screen_from_message(
            message,
            memory_state,
            "Notion error, try again.",
            reply_markup=None,
            user_id=target_user_id,
        )
        return
    await _edit_screen_from_message(message, memory_state, "Сохранено ✅", reply_markup=None, user_id=target_user_id)
    await _show_open_orders_screen(message, memory_state, config, notion, user_id=target_user_id)


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
