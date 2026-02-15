from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.filters.flow import FlowFilter
from app.keyboards.inline import (
    back_cancel_keyboard,
    build_accounting_content_keyboard,
    build_files_confirm_content_keyboard,
    build_files_menu_keyboard,
    build_quantity_input_keyboard,
    model_card_keyboard,
)
from app.services import NotionClient
from app.services.accounting import AccountingService
from app.services.model_card import build_model_card
from app.state import MemoryState, get_active_token
from app.utils import safe_edit_message
from app.utils.screen import clear_previous_screen_keyboard, render_screen

router = Router()


def _state_ids_from_query(query: CallbackQuery) -> tuple[int, int]:
    if not query.message:
        return query.from_user.id, query.from_user.id
    return query.message.chat.id, query.from_user.id


def _callback_token(parts: list[str]) -> str | None:
    if len(parts) >= 4:
        return parts[-1]
    return None


async def show_files_menu_from_model(
    target: CallbackQuery | Message,
    model_id: str,
    model_name: str,
    memory_state: MemoryState,
) -> None:
    if hasattr(target, "data") and hasattr(target, "message"):
        chat_id, user_id = _state_ids_from_query(target)
        callback_token = _callback_token((target.data or "").split("|"))
    else:
        chat_id, user_id = target.chat.id, target.from_user.id
        callback_token = None

    token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
    memory_state.transition(chat_id, user_id, flow="nlp_idle", model_id=model_id, model_name=model_name, k=token)
    if not (hasattr(target, "data") and hasattr(target, "message")):
        await clear_previous_screen_keyboard(target, memory_state)
    await render_screen(
        target,
        f"🏠 > 📁 Файлы\nМодель: {model_name}",
        reply_markup=build_files_menu_keyboard(token=token),
        memory_state=memory_state,
    )


async def _open_content_selector(call: CallbackQuery, memory_state: MemoryState, flow: str) -> None:
    chat_id, user_id = _state_ids_from_query(call)
    state = memory_state.get(chat_id, user_id) or {}
    token = get_active_token(memory_state, chat_id, user_id)
    memory_state.transition(chat_id, user_id, flow=flow, k=token)
    selected = state.get("content_types", [])
    await call.message.edit_text(
        "🏠 > 📁 Файлы\n\nВыберите типы контента:",
        reply_markup=build_accounting_content_keyboard(selected, token=token),
    )


async def _ask_select_model(target: CallbackQuery | Message, memory_state: MemoryState, return_to: str = "files") -> None:
    if hasattr(target, "data") and hasattr(target, "message"):
        chat_id, user_id = _state_ids_from_query(target)
        callback_token = _callback_token((target.data or "").split("|"))
        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        memory_state.transition(chat_id, user_id, flow="nlp_view", step="select_model", return_to=return_to, k=token)
        await safe_edit_message(
            target,
            "Сначала выберите модель.\n\nВведите имя модели обычным текстом:",
            reply_markup=back_cancel_keyboard(return_to, token=token),
        )
        return

    chat_id, user_id = target.chat.id, target.from_user.id
    token = get_active_token(memory_state, chat_id, user_id)
    memory_state.transition(chat_id, user_id, flow="nlp_view", step="select_model", return_to=return_to, k=token)
    await target.answer(
        "Сначала выберите модель.\n\nВведите имя модели обычным текстом:",
        reply_markup=back_cancel_keyboard(return_to, token=token),
    )


async def _add_files_and_prompt_content_update(
    call: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    qty: int,
) -> None:
    chat_id, user_id = _state_ids_from_query(call)
    state = memory_state.get(chat_id, user_id) or {}
    model_id = state.get("model_id")
    model_name = state.get("model_name") or "—"

    if not model_id:
        await _ask_select_model(call, memory_state, return_to="files")
        return

    service = AccountingService(config)
    try:
        await service.add_files(model_id=model_id, model_name=model_name, files_to_add=qty)
    finally:
        await service.close()

    token = get_active_token(memory_state, chat_id, user_id)
    memory_state.transition(
        chat_id,
        user_id,
        flow="nlp_files_confirm_content",
        files_quantity=qty,
        k=token,
    )
    await call.message.edit_text(
        f"✅ Добавлено файлов: {qty}\n\nОбновить категории контента?",
        reply_markup=build_files_confirm_content_keyboard(token=token),
    )


@router.callback_query(F.data.startswith("files|"))
async def files_menu_router(call: CallbackQuery, config: Config, notion: NotionClient, memory_state: MemoryState) -> None:
    parts = (call.data or "").split("|")
    action = parts[1] if len(parts) > 1 else "menu"
    value = parts[2] if len(parts) > 2 else ""
    chat_id, user_id = _state_ids_from_query(call)
    state = memory_state.get(chat_id, user_id) or {}
    callback_token = _callback_token(parts)
    model_id = state.get("model_id")
    model_name = state.get("model_name") or "—"

    if action == "menu":
        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            f"🏠 > 📁 Файлы\nМодель: {model_name}",
            reply_markup=build_files_menu_keyboard(token=token),
        )

    elif action == "add_files":
        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        memory_state.transition(chat_id, user_id, flow="nlp_files_add_quantity", k=token)
        await call.message.edit_text(
            "🏠 > 📁 Файлы > ➕ Добавить\n\nВыберите количество:",
            reply_markup=build_quantity_input_keyboard(token=token),
        )

    elif action == "qty":
        if not value:
            await call.answer("Экран устарел, открой заново", show_alert=True)
            return
        if value == "custom":
            token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
            memory_state.transition(chat_id, user_id, flow="nlp_files_quantity_input", k=token)
            await call.message.edit_text("Введите количество файлов числом:")
        else:
            await _add_files_and_prompt_content_update(call, config, memory_state, int(value))

    elif action == "confirm_content":
        decision = value
        if decision == "yes":
            token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
            memory_state.transition(chat_id, user_id, flow="nlp_files_add_content", k=token)
            await _open_content_selector(call, memory_state, "nlp_files_add_content")
        else:
            token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
            memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
            await call.message.edit_text(
                f"🏠 > 📁 Файлы\nМодель: {model_name}",
                reply_markup=build_files_menu_keyboard(token=token),
            )

    elif action == "toggle_content":
        selected = set(state.get("content_types", []))
        if value in selected:
            selected.remove(value)
        else:
            selected.add(value)
        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        memory_state.update(chat_id, user_id, content_types=sorted(selected), k=token)
        await call.message.edit_reply_markup(
            reply_markup=build_accounting_content_keyboard(sorted(selected), token=token),
        )

    elif action == "content_done":
        flow = state.get("flow")
        if not model_id:
            await _ask_select_model(call, memory_state, return_to="files")
            return
        service = AccountingService(config)
        try:
            record = await service.get_monthly_record(model_id)
            content_types = state.get("content_types", [])
            content_str = ", ".join(content_types) if content_types else "не указаны"
            qty_added = int(state.get("files_quantity") or 0)
            total_files = record.files if record and record.files is not None else qty_added

            if flow == "nlp_files_add_content":
                if record:
                    await service.update_content(record.page_id, content_types)
                success_text = (
                    f"✅ Добавлено {qty_added} файлов → {model_name}\n"
                    f"📊 Всего: {total_files} | 🗂 {content_str}"
                )
            elif flow == "nlp_files_edit_content":
                if record:
                    await service.update_content(record.page_id, content_types)
                success_text = f"✅ Категории обновлены → {model_name}\n🗂 {content_str}"
            else:
                success_text = f"✅ Добавлено файлов: {qty_added}\nМодель: {model_name}"
        finally:
            await service.close()

        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            success_text,
            reply_markup=build_files_menu_keyboard(token=token),
        )

    elif action == "edit_content":
        if not model_id:
            await _ask_select_model(call, memory_state, return_to="files")
            return
        service = AccountingService(config)
        try:
            record = await service.get_monthly_record(model_id)
            selected = record.content if record and record.content else []
        finally:
            await service.close()
        memory_state.update(chat_id, user_id, content_types=selected)
        await _open_content_selector(call, memory_state, "nlp_files_edit_content")

    elif action == "edit_comment":
        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        memory_state.transition(chat_id, user_id, flow="nlp_files_edit_comment", k=token)
        await call.message.edit_text("Введите новый комментарий для файлов:")

    elif action == "back":
        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        if value == "card":
            if not model_id or not model_name or model_name == "—":
                await call.answer("Экран устарел, открой заново", show_alert=True)
                return
            card_text, _ = await build_model_card(model_id, model_name, config, notion)
            memory_state.transition(chat_id, user_id, flow="nlp_idle", model_id=model_id, model_name=model_name, k=token)
            await call.message.edit_text(card_text, reply_markup=model_card_keyboard(token), parse_mode="HTML")
        else:
            memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
            await call.message.edit_text(
                f"🏠 > 📁 Файлы\nМодель: {model_name}",
                reply_markup=build_files_menu_keyboard(token=token),
            )

    elif action == "cancel":
        token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=callback_token)
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            f"🏠 > 📁 Файлы\nМодель: {model_name}",
            reply_markup=build_files_menu_keyboard(token=token),
        )

    else:
        await call.answer("Экран устарел, открой заново", show_alert=True)
        return

    await call.answer()


@router.message(FlowFilter({"nlp_files_quantity_input"}), F.text)
async def handle_quantity_input(msg: Message, config: Config, memory_state: MemoryState) -> None:
    chat_id, user_id = msg.chat.id, msg.from_user.id
    value = (msg.text or "").strip()
    if not value.isdigit():
        await msg.answer("Введите целое число")
        return
    qty = int(value)
    state = memory_state.get(chat_id, user_id) or {}
    model_id = state.get("model_id")
    model_name = state.get("model_name") or "—"
    if not model_id:
        await _ask_select_model(msg, memory_state, return_to="files")
        return

    service = AccountingService(config)
    try:
        await service.add_files(model_id=model_id, model_name=model_name, files_to_add=qty)
    finally:
        await service.close()

    token = get_active_token(memory_state, chat_id, user_id)
    memory_state.transition(chat_id, user_id, flow="nlp_files_confirm_content", files_quantity=qty, k=token)
    await msg.answer(
        f"✅ Добавлено файлов: {qty}\n\nОбновить категории контента?",
        reply_markup=build_files_confirm_content_keyboard(token=token),
    )


@router.message(FlowFilter({"nlp_files_edit_comment"}), F.text)
async def handle_edit_comment(msg: Message, config: Config, memory_state: MemoryState) -> None:
    chat_id, user_id = msg.chat.id, msg.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    model_id = state.get("model_id")
    model_name = state.get("model_name") or "—"
    if not model_id:
        await _ask_select_model(msg, memory_state, return_to="files")
        return

    service = AccountingService(config)
    try:
        record = await service.get_monthly_record(model_id)
        if record:
            await service.update_comment(record.page_id, msg.text.strip())
    finally:
        await service.close()

    token = get_active_token(memory_state, chat_id, user_id)
    memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
    await msg.answer(
        f"✅ Комментарий обновлён → {model_name}\n💬 \"{msg.text.strip()[:50]}{'...' if len(msg.text.strip()) > 50 else ''}\"",
        reply_markup=build_files_menu_keyboard(token=token),
    )
