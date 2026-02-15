from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.filters.flow import FlowFilter
from app.keyboards.inline import (
    build_accounting_content_keyboard,
    build_files_confirm_content_keyboard,
    build_files_menu_keyboard,
    build_quantity_input_keyboard,
)
from app.services.accounting import AccountingService
from app.state import MemoryState, generate_token
from app.utils.constants import NLP_ACCOUNTING_CONTENT_TYPES

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
        await call.answer("Сначала выберите модель через /трико", show_alert=True)
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
        "Обновить категории контента?",
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
            token = generate_token()
            memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
            await call.message.edit_text(
                f"✅ Данные по файлам обновлены\nМодель: {model_name}",
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
            await call.answer("Сначала выберите модель через /трико", show_alert=True)
            return
        service = AccountingService(config)
        try:
            record = await service.get_monthly_record(model_id)
            content_types = state.get("content_types", [])

            if flow == "nlp_files_add_content":
                if record:
                    await service.update_content(record.page_id, content_types)

            elif flow == "nlp_files_edit_content":
                if record:
                    await service.update_content(record.page_id, content_types)
        finally:
            await service.close()

        token = generate_token()
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token)
        await call.message.edit_text(
            f"✅ Данные по файлам обновлены\nМодель: {model_name}",
            reply_markup=build_files_menu_keyboard(token=token),
        )

    elif action == "edit_content":
        if not model_id:
            await call.answer("Сначала выберите модель через /трико", show_alert=True)
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
        await msg.answer("Сначала выберите модель через /трико")
        return

    service = AccountingService(config)
    try:
        await service.add_files(model_id=model_id, model_name=model_name, files_to_add=qty)
    finally:
        await service.close()

    token = generate_token()
    memory_state.transition(chat_id, user_id, flow="nlp_files_confirm_content", files_quantity=qty, k=token)
    await msg.answer(
        "Обновить категории контента?",
        reply_markup=build_files_confirm_content_keyboard(token=token),
    )


@router.message(FlowFilter({"nlp_files_edit_comment"}), F.text)
async def handle_edit_comment(msg: Message, config: Config, memory_state: MemoryState) -> None:
    chat_id, user_id = msg.chat.id, msg.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    model_id = state.get("model_id")
    model_name = state.get("model_name") or "—"
    if not model_id:
        await msg.answer("Сначала выберите модель через /трико")
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
        f"✅ Комментарий обновлён\nМодель: {model_name}",
        reply_markup=build_files_menu_keyboard(token=token),
    )
