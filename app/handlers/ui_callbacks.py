from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.filters.topic_access import TopicAccessCallbackFilter
from app.keyboards.inline import model_card_keyboard
from app.roles import is_authorized
from app.services import NotionClient
from app.services.model_card import build_model_card
from app.state import MemoryState, get_active_token
from app.utils.screen import render_screen
from app.utils.ui_callbacks import parse_ui_callback
from app.handlers.orders import show_orders_menu_from_model
from app.handlers.planner import show_planner_menu_from_model
from app.handlers.files import show_files_menu_from_model

router = Router()
router.callback_query.filter(TopicAccessCallbackFilter())


@router.callback_query(F.data.startswith("ui:"))
async def handle_ui_callback(
    query: CallbackQuery,
    config: Config,
    notion: NotionClient,
    memory_state: MemoryState,
) -> None:
    if not is_authorized(query.from_user.id, config):
        await query.answer("Access denied", show_alert=True)
        return

    parsed = parse_ui_callback(query.data)
    if not parsed or parsed.module != "model":
        await query.answer("Экран устарел, открой заново", show_alert=True)
        return

    chat_id = query.message.chat.id
    user_id = query.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    token = get_active_token(memory_state, chat_id, user_id, fallback_from_callback=parsed.token)

    if parsed.action == "reset":
        memory_state.transition(chat_id, user_id, flow="nlp_idle", k=token, model_id=None, model_name=None)
        await render_screen(
            query,
            "Введите имя модели обычным текстом.\nМожно сразу с действием: «трико заказы», «трико файлы 30».",
            memory_state=memory_state,
        )
        await query.answer()
        return

    model_id = state.get("model_id")
    model_name = state.get("model_name")
    if not model_id or not model_name:
        await query.answer("Сессия истекла, открой модель заново", show_alert=True)
        return

    if parsed.action == "orders":
        await show_orders_menu_from_model(query, model_id, model_name, memory_state)
        await query.answer()
        return

    if parsed.action == "files":
        await show_files_menu_from_model(query, model_id, model_name, memory_state)
        await query.answer()
        return

    if parsed.action in {"planner", "shoot"}:
        await show_planner_menu_from_model(query, model_id, model_name, memory_state)
        await query.answer()
        return

    if parsed.action == "card":
        card_text, _ = await build_model_card(model_id, model_name, config, notion)
        memory_state.transition(chat_id, user_id, flow="nlp_idle", model_id=model_id, model_name=model_name, k=token)
        await render_screen(
            query,
            card_text,
            reply_markup=model_card_keyboard(token),
            parse_mode="HTML",
            memory_state=memory_state,
        )
        await query.answer()
        return

    await query.answer("Экран устарел, открой заново", show_alert=True)
