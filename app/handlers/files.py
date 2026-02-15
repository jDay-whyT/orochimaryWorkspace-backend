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
)
from app.services.accounting import AccountingService
from app.state import MemoryState, generate_token
from app.utils.constants import NLP_ACCOUNTING_CONTENT_TYPES
from app.utils import safe_edit_message

router = Router()


def _state_ids_from_query(query: CallbackQuery) -> tuple[int, int]:
    if not query.message:
        return query.from_user.id, query.from_user.id
    return query.message.chat.id, query.from_user.id


async def _open_content_selector(call: CallbackQuery, memory_state: MemoryState, flow: str) -> None:
    chat_id, user_id = _state_ids_from_query(call)
    state = memory_state.get(chat_id, user_id) or {}
    token = generate_token()
    memory_state.transition(chat_id, user_id, flow=flow, k=token)
    selected = state.get("content_types", [])
    await call.message.edit_text(
        "🏠 > 📁 Файлы\n\nВыберите типы контента:",
        reply_markup=build_accounting_content_keyboard(selected, token=token),
    )


async def _ask_select_model(target: CallbackQuery | Message, memory_state: MemoryState, return_to: str = "files") -> None:
    if isinstance(target, CallbackQuery):
        chat_id, user_id = _state_ids_from_query(target)
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_view", step="select_model", return_to=return_to, k=token)
        await safe_edit_message(
            target,
            "Сначала выберите модель.\n\nВведите имя модели обычным текстом:",
            reply_markup=back_cancel_keyboard(return_to, token=token),
        )
        return

    chat_id, user_id = target.chat.id, target.from_user.id
    token = generate_token()
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

    token = generate_token()
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
async def files_menu_router(call: CallbackQuery, config: Config, memory_state: MemoryState) -> None:
    parts = (call.data or "").split("|")
    action = parts[1] if len(parts) > 1 else "menu"
    chat_id, user_id = _state_ids_from_query(call)
    state = memory_state.get(chat_id, user_id) or {}
    model_id = state.get("model_id")
    model_name = state.get("model_name") or "—"

    if action == "menu":
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            f"🏠 > 📁 Файлы\nМодель: {model_name}",
            reply_markup=build_files_menu_keyboard(token=token),
        )

    elif action == "add_files":
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_files_add_quantity", k=token)
        await call.message.edit_text(
            "🏠 > 📁 Файлы > ➕ Добавить\n\nВыберите количество:",
            reply_markup=build_quantity_input_keyboard(token=token),
        )

    elif action == "qty":
        if len(parts) < 3:
            await call.answer()
            return
        qty = parts[2]
        if qty == "custom":
            token = generate_token()
            memory_state.transition(chat_id, user_id, flow="nlp_files_quantity_input", k=token)
            await call.message.edit_text("Введите количество файлов числом:")
        else:
            await _add_files_and_prompt_content_update(call, config, memory_state, int(qty))

    elif action == "confirm_content":
        decision = parts[2] if len(parts) > 2 else ""
        if decision == "yes":
            memory_state.update(chat_id, user_id, content_types=[])
            await _open_content_selector(call, memory_state, "nlp_files_add_content")
        elif decision == "skip":
            qty = int(state.get("files_quantity") or 0)
            total_files = qty
            if model_id:
                service = AccountingService(config)
                try:
                    record = await service.get_monthly_record(model_id)
                    if record and record.files is not None:
                        total_files = record.files
                finally:
                    await service.close()
            token = generate_token()
            memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
            await call.message.edit_text(
                f"✅ Добавлено {qty} файлов → {model_name}\n"
                f"📊 Всего: {total_files} | ⚠️ Категории не указаны",
                reply_markup=build_files_menu_keyboard(token=token),
            )
        else:
            await call.answer()
            return

    elif action == "toggle_content":
        if len(parts) < 3:
            await call.answer()
            return
        content_type = parts[2]
        if content_type not in NLP_ACCOUNTING_CONTENT_TYPES:
            await call.answer("Неизвестный тип", show_alert=True)
            return
        selected = set(state.get("content_types", []))
        if content_type in selected:
            selected.remove(content_type)
        else:
            selected.add(content_type)
        memory_state.update(chat_id, user_id, content_types=sorted(selected))
        token = generate_token()
        memory_state.update(chat_id, user_id, k=token)
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

        token = generate_token()
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
        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_files_edit_comment", k=token)
        await call.message.edit_text("Введите новый комментарий для файлов:")

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

    token = generate_token()
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

    token = generate_token()
    memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
    await msg.answer(
        f"✅ Комментарий обновлён → {model_name}\n💬 \"{msg.text.strip()[:50]}{'...' if len(msg.text.strip()) > 50 else ''}\"",
        reply_markup=build_files_menu_keyboard(token=token),
    )
