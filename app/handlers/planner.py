import html
import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.filters import FlowFilter
from app.filters.topic_access import TopicAccessCallbackFilter, TopicAccessMessageFilter
from app.keyboards.inline import (
    planner_menu_keyboard,
    models_keyboard,
    planner_content_keyboard,
    planner_location_keyboard,
    planner_shoot_keyboard,
    planner_cancel_confirm_keyboard,
    back_keyboard,
)
from app.keyboards.calendar import calendar_keyboard, parse_calendar_navigation
from app.roles import is_authorized, is_editor_or_admin
from app.services import PlannerService, ModelsService
from app.state import MemoryState, RecentModels, generate_token
from app.utils.constants import PLANNER_CONTENT_OPTIONS, PLANNER_LOCATION_OPTIONS

LOGGER = logging.getLogger(__name__)
router = Router()
router.message.filter(TopicAccessMessageFilter())
router.callback_query.filter(TopicAccessCallbackFilter())


def _state_ids_from_message(message: Message) -> tuple[int, int]:
    return message.chat.id, message.from_user.id


def _state_ids_from_query(query: CallbackQuery) -> tuple[int, int]:
    if not query.message:
        return query.from_user.id, query.from_user.id
    return query.message.chat.id, query.from_user.id


async def show_planner_menu(message: Message, config: Config) -> None:
    """Show planner section menu."""
    await message.answer(
        "📅 <b>Planner</b>\n\n"
        "Select an action:",
        reply_markup=planner_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("planner|"))
async def handle_planner_callback(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle planner callbacks."""
    if not is_authorized(query.from_user.id, config):
        await query.answer("Access denied", show_alert=True)
        return
    
    parts = query.data.split("|")
    if len(parts) < 3:
        await query.answer()
        return
    
    action = parts[1]
    value = parts[2] if len(parts) > 2 else None
    user_id = query.from_user.id
    
    try:
        if action == "back":
            await _handle_back(query, config, memory_state, recent_models, value)
        elif action == "cancel":
            await _cancel_flow(query, memory_state)
        elif action == "upcoming":
            await _show_upcoming_shoots(query, config)
        elif action == "new":
            await _start_new_shoot(query, config, memory_state, recent_models)
        elif action == "shoot":
            await _show_shoot_details(query, config, value)
        elif action == "done":
            await _mark_shoot_done(query, config, value)
        elif action == "reschedule":
            await _start_reschedule(query, config, memory_state, value)
        elif action == "cancel_confirm":
            await _show_cancel_confirmation(query, value)
        elif action == "cancel_shoot":
            await _cancel_shoot(query, config, value)
        elif action == "edit_content":
            await _start_edit_content(query, config, memory_state, value)
        elif action == "comment":
            await _start_add_comment(query, memory_state, value)
        elif action == "select_model":
            await _select_model_for_shoot(query, config, memory_state, recent_models, value)
        elif action == "model":
            # Alias for select_model (used by recent_models_keyboard)
            await _select_model_for_shoot(query, config, memory_state, recent_models, value)
        elif action == "search":
            await _start_search(query, memory_state)
        elif action == "content_toggle":
            await _toggle_content(query, memory_state, value)
        elif action == "content_done":
            await _finish_content_selection(query, config, memory_state)
        elif action == "location":
            await _select_location(query, config, memory_state, value)
        elif action == "cal_day":
            await _select_date(query, config, memory_state, value)
        elif action == "cal_nav":
            await _navigate_calendar(query, config, memory_state, value)
        elif action == "cal_ignore":
            await query.answer()
            return
        elif action == "confirm":
            await _create_shoot(query, config, memory_state, recent_models)
        else:
            await query.answer("Unknown action", show_alert=True)
        
        await query.answer()
    
    except Exception as e:
        LOGGER.exception("Error in planner callback")
        await query.answer(f"Error: {str(e)}", show_alert=True)


@router.message(FlowFilter({"nlp_planner"}), F.text)
async def handle_text_input(
    message: Message,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle text input for planner search and comments."""
    if not is_authorized(message.from_user.id, config):
        return

    chat_id, user_id = _state_ids_from_message(message)
    state = memory_state.get(chat_id, user_id)
    step = state.get("step")
    
    # Delete user message to keep chat clean
    try:
        await message.delete()
    except Exception:
        pass

    try:
        if step == "search_model":
            await _handle_search_results(message, config, memory_state, recent_models)
        elif step == "add_comment":
            await _handle_comment_text(message, config, memory_state)
        else:
            return
    except Exception as e:
        LOGGER.exception("Error handling planner text input")
        await message.answer(f"❌ Error: {str(e)}")


# ==================== Handlers ====================

async def _handle_back(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
    value: str,
) -> None:
    """Handle back navigation."""
    chat_id, user_id = _state_ids_from_query(query)
    if value == "main":
        memory_state.clear(chat_id, user_id)
        await query.message.delete()
    elif value == "back":
        # Generic back from back_cancel_keyboard - return to menu
        memory_state.clear(chat_id, user_id)
        await query.message.edit_text(
            "📅 <b>Planner</b>\n\nSelect an action:",
            reply_markup=planner_menu_keyboard(),
            parse_mode="HTML",
        )
    elif value == "menu":
        memory_state.clear(chat_id, user_id)
        await query.message.edit_text(
            "📅 <b>Planner</b>\n\nSelect an action:",
            reply_markup=planner_menu_keyboard(),
            parse_mode="HTML",
        )
    elif value == "select_model":
        state = memory_state.get(chat_id, user_id)
        if state:
            recent = recent_models.get(user_id)
            await query.message.edit_text(
                "📅 <b>New Shoot</b>\n\nStep 1: Select model",
                reply_markup=models_keyboard("planner", recent, show_search=True, token=state.get("k", "")),
                parse_mode="HTML",
            )
            state["step"] = "select_model"
    elif value == "content":
        state = memory_state.get(chat_id, user_id)
        if state:
            selected = state.get("content", [])
            await query.message.edit_text(
                "📅 <b>New Shoot</b>\n\n"
                f"Step 2: Select content\n\n"
                f"Selected: {', '.join(selected) if selected else 'none'}",
                reply_markup=planner_content_keyboard("planner", selected, token=state.get("k", "")),
                parse_mode="HTML",
            )
            state["step"] = "select_content"
    elif value == "location":
        state = memory_state.get(chat_id, user_id)
        if state:
            await query.message.edit_text(
                "📅 <b>New Shoot</b>\n\nStep 3: Select location",
                reply_markup=planner_location_keyboard("planner", token=state.get("k", "")),
                parse_mode="HTML",
            )
            state["step"] = "select_location"


async def _cancel_flow(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Cancel current flow."""
    chat_id, user_id = _state_ids_from_query(query)
    memory_state.clear(chat_id, user_id)
    await query.message.edit_text(
        "📅 <b>Planner</b>\n\nCancelled.",
        parse_mode="HTML",
    )


async def _show_upcoming_shoots(query: CallbackQuery, config: Config) -> None:
    """Show upcoming shoots list."""
    service = PlannerService(config)
    
    try:
        shoots = await service.get_upcoming_shoots()
        
        if not shoots:
            await query.message.edit_text(
                "📅 <b>Upcoming Shoots</b>\n\n"
                "No upcoming shoots scheduled.",
                reply_markup=back_keyboard("planner", "menu", token=generate_token()),
                parse_mode="HTML",
            )
            return
        
        # Format shoots list
        lines = ["📅 <b>Upcoming Shoots</b>\n"]
        
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        builder = InlineKeyboardBuilder()
        
        for shoot in shoots[:10]:  # Limit to 10
            model_name = shoot.get("model_name", "Unknown")
            shoot_date = shoot.get("date", "No date")
            status = shoot.get("status", "")
            
            builder.row(InlineKeyboardButton(
                text=f"📅 {model_name} · {shoot_date}",
                callback_data=f"planner|shoot|{shoot['id']}"
            ))
        
        builder.row(
            InlineKeyboardButton(text="◀️ Back", callback_data="planner|back|menu")
        )
        
        await query.message.edit_text(
            "\n".join(lines),
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    
    finally:
        await service.close()


async def _start_new_shoot(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Start new shoot creation flow."""
    if not is_editor_or_admin(query.from_user.id, config):
        await query.answer("Only editors can create shoots", show_alert=True)
        return

    chat_id, user_id = _state_ids_from_query(query)
    token = generate_token()
    memory_state.set(
        chat_id,
        user_id,
        {
            "flow": "nlp_planner",
            "step": "select_model",
            "screen_chat_id": query.message.chat.id,
            "screen_message_id": query.message.message_id,
            "k": token,
        },
    )
    
    recent = recent_models.get(user_id)
    
    await query.message.edit_text(
        "📅 <b>New Shoot</b>\n\nStep 1: Select model",
        reply_markup=models_keyboard("planner", recent, show_search=True, token=token),
        parse_mode="HTML",
    )


async def _select_model_for_shoot(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
    model_id: str,
) -> None:
    """Select model and proceed to content selection."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    # Fetch model details
    models_service = ModelsService(config)
    try:
        model = await models_service.get_model(model_id)
        if not model:
            await query.answer("Model not found", show_alert=True)
            return
        
        # Add to recent
        recent_models.add(user_id, model_id, model["name"])
        
        # Save to state
        state["model_id"] = model_id
        state["model_name"] = model["name"]
        state["step"] = "select_content"
        state["content"] = []
        
        await query.message.edit_text(
            f"📅 <b>New Shoot</b>\n\n"
            f"Model: {html.escape(model['name'])}\n\n"
            f"Step 2: Select content\n\n"
            f"Selected: none",
            reply_markup=planner_content_keyboard("planner", [], token=state.get("k", "")),
            parse_mode="HTML",
        )
    
    finally:
        await models_service.close()


async def _start_search(query: CallbackQuery, memory_state: MemoryState) -> None:
    """Start model search."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    state["step"] = "search_model"
    
    await query.message.edit_text(
        "📅 <b>New Shoot</b>\n\n"
        "Step 1: Search model\n\n"
        "Enter model name:",
        reply_markup=back_keyboard("planner", "select_model", token=state.get("k", "")),
        parse_mode="HTML",
    )


async def _handle_search_results(
    message: Message,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Handle model search results."""
    chat_id, user_id = _state_ids_from_message(message)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    query_text = message.text.strip()
    if not query_text:
        return
    
    models_service = ModelsService(config)
    try:
        results = await models_service.search_models(query_text, limit=10)

        if not results:
            await message.answer(
                f"No models found for '{html.escape(query_text)}'",
                parse_mode="HTML",
            )
            return

        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder

        builder = InlineKeyboardBuilder()

        for model in results:
            builder.row(InlineKeyboardButton(
                text=model["name"],
                callback_data=f"planner|select_model|{model['id']}"
            ))

        builder.row(
            InlineKeyboardButton(text="◀️ Back", callback_data="planner|back|select_model"),
            InlineKeyboardButton(text="✖ Cancel", callback_data="planner|cancel|cancel"),
        )

        # Update screen message
        chat_id = state.get("screen_chat_id")
        message_id = state.get("screen_message_id")

        if chat_id and message_id:
            from aiogram import Bot
            bot = message.bot
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"📅 <b>New Shoot</b>\n\n"
                     f"Search results for '{html.escape(query_text)}':",
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
            )

    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to search models: %s", e)
        await message.answer(
            "❌ <b>Error searching models</b>\n\nDatabase connection failed. Please contact admin.",
            parse_mode="HTML",
        )

    finally:
        await models_service.close()


async def _toggle_content(
    query: CallbackQuery,
    memory_state: MemoryState,
    content_type: str,
) -> None:
    """Toggle content type selection."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    selected = state.get("content", [])
    
    if content_type in selected:
        selected.remove(content_type)
    else:
        selected.append(content_type)
    
    state["content"] = selected
    
    await query.message.edit_text(
        f"📅 <b>New Shoot</b>\n\n"
        f"Model: {html.escape(state.get('model_name', 'Unknown'))}\n\n"
        f"Step 2: Select content\n\n"
        f"Selected: {', '.join(selected) if selected else 'none'}",
        reply_markup=planner_content_keyboard("planner", selected),
        parse_mode="HTML",
    )


async def _finish_content_selection(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
) -> None:
    """Finish content selection and move to location."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    selected = state.get("content", [])
    if not selected:
        await query.answer("Please select at least one content type", show_alert=True)
        return
    
    state["step"] = "select_location"
    
    await query.message.edit_text(
        f"📅 <b>New Shoot</b>\n\n"
        f"Model: {html.escape(state.get('model_name', 'Unknown'))}\n"
        f"Content: {', '.join(selected)}\n\n"
        f"Step 3: Select location",
        reply_markup=planner_location_keyboard("planner", token=state.get("k", "")),
        parse_mode="HTML",
    )


async def _select_location(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    location: str,
) -> None:
    """Select location and show calendar."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    state["location"] = location
    state["step"] = "select_date"
    
    # Show calendar (future dates only)
    today = date.today()
    current_year = today.year
    current_month = today.month
    
    await query.message.edit_text(
        f"📅 <b>New Shoot</b>\n\n"
        f"Model: {html.escape(state.get('model_name', 'Unknown'))}\n"
        f"Content: {', '.join(state.get('content', []))}\n"
        f"Location: {location}\n\n"
        f"Step 4: Select date",
        reply_markup=calendar_keyboard("planner", current_year, current_month, min_date=today),
        parse_mode="HTML",
    )


async def _navigate_calendar(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    value: str,
) -> None:
    """Navigate to different month in calendar."""
    result = parse_calendar_navigation(value)
    if not result:
        return
    
    year, month = result
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    today = date.today()
    
    await query.message.edit_reply_markup(
        reply_markup=calendar_keyboard("planner", year, month, min_date=today)
    )


async def _select_date(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    date_str: str,
) -> None:
    """Select date and show confirmation."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    state["date"] = date_str
    state["step"] = "confirm"
    
    # Show confirmation with option to add comment
    model_name = state.get("model_name", "Unknown")
    content = ", ".join(state.get("content", []))
    location = state.get("location", "")
    
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💬 Add Comment", callback_data="planner|comment|shoot"),
        InlineKeyboardButton(text="Skip →", callback_data="planner|confirm|create"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data="planner|back|location"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="planner|cancel|cancel"),
    )
    
    await query.message.edit_text(
        f"📅 <b>New Shoot - Confirmation</b>\n\n"
        f"Model: {html.escape(model_name)}\n"
        f"Date: {date_str}\n"
        f"Location: {location}\n"
        f"Content: {content}\n\n"
        f"Ready to create?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


async def _start_add_comment(
    query: CallbackQuery,
    memory_state: MemoryState,
    comment_for: str,
) -> None:
    """Start adding comment."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    state["step"] = "add_comment"
    state["comment_for"] = comment_for
    
    await query.message.edit_text(
        "📅 <b>Add Comment</b>\n\n"
        "Enter your comment:",
        reply_markup=back_keyboard("planner", "confirm"),
        parse_mode="HTML",
    )


async def _handle_comment_text(
    message: Message,
    config: Config,
    memory_state: MemoryState,
) -> None:
    """Handle comment text input."""
    chat_id, user_id = _state_ids_from_message(message)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    comment = message.text.strip()
    state["comment"] = comment
    state["step"] = "confirm"
    
    # Update screen with comment added
    model_name = state.get("model_name", "Unknown")
    content = ", ".join(state.get("content", []))
    location = state.get("location", "")
    date_str = state.get("date", "")
    
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✓ Create", callback_data="planner|confirm|create"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Back", callback_data="planner|back|location"),
        InlineKeyboardButton(text="✖ Cancel", callback_data="planner|cancel|cancel"),
    )
    
    chat_id = state.get("screen_chat_id")
    message_id = state.get("screen_message_id")
    
    if chat_id and message_id:
        from aiogram import Bot
        bot = message.bot
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"📅 <b>New Shoot - Confirmation</b>\n\n"
                 f"Model: {html.escape(model_name)}\n"
                 f"Date: {date_str}\n"
                 f"Location: {location}\n"
                 f"Content: {content}\n"
                 f"Comment: {html.escape(comment)}\n\n"
                 f"Ready to create?",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )


async def _create_shoot(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    recent_models: RecentModels,
) -> None:
    """Create the shoot in Notion."""
    chat_id, user_id = _state_ids_from_query(query)
    state = memory_state.get(chat_id, user_id)
    if not state:
        return
    
    model_id = state.get("model_id")
    date_str = state.get("date")
    content = state.get("content", [])
    location = state.get("location")
    comment = state.get("comment")
    
    if not all([model_id, date_str, content, location]):
        await query.answer("Missing required data", show_alert=True)
        return
    
    service = PlannerService(config)
    try:
        shoot_id = await service.create_shoot(
            model_id=model_id,
            shoot_date=date_str,
            content=content,
            location=location,
            comment=comment,
        )
        
        memory_state.clear(chat_id, user_id)
        
        await query.message.edit_text(
            "✅ <b>Shoot Created!</b>\n\n"
            f"Model: {html.escape(state.get('model_name', 'Unknown'))}\n"
            f"Date: {date_str}\n"
            f"Location: {location}",
            parse_mode="HTML",
        )
    
    except Exception as e:
        LOGGER.exception("Failed to create shoot")
        await query.answer(f"Error creating shoot: {str(e)}", show_alert=True)
    
    finally:
        await service.close()


async def _show_shoot_details(
    query: CallbackQuery,
    config: Config,
    shoot_id: str,
) -> None:
    """Show shoot details with action buttons."""
    service = PlannerService(config)
    
    try:
        shoot = await service.get_shoot_by_id(shoot_id)
        if not shoot:
            await query.answer("Shoot not found", show_alert=True)
            return
        
        model_name = shoot.get("model_name", "Unknown")
        shoot_date = shoot.get("date", "No date")
        status = shoot.get("status", "")
        location = shoot.get("location", "")
        content = ", ".join(shoot.get("content", []))
        comments = shoot.get("comments", "")
        
        text = (
            f"📅 <b>{html.escape(model_name)} · {shoot_date}</b>\n\n"
            f"Location: {location}\n"
            f"Content: {content}\n"
            f"Status: {status}\n"
        )
        
        if comments:
            text += f"\n💬 {html.escape(comments)}"
        
        await query.message.edit_text(
            text,
            reply_markup=planner_shoot_keyboard(shoot_id),
            parse_mode="HTML",
        )
    
    finally:
        await service.close()


async def _mark_shoot_done(
    query: CallbackQuery,
    config: Config,
    shoot_id: str,
) -> None:
    """Mark shoot as done."""
    if not is_editor_or_admin(query.from_user.id, config):
        await query.answer("Only editors can modify shoots", show_alert=True)
        return
    
    service = PlannerService(config)
    try:
        await service.mark_done(shoot_id)
        await query.answer("✓ Shoot marked as done")
        
        # Refresh shoot details
        await _show_shoot_details(query, config, shoot_id)
    
    finally:
        await service.close()



async def _show_cancel_confirmation(query: CallbackQuery, shoot_id: str) -> None:
    """Show inline confirmation before shoot cancellation."""
    await query.message.edit_text(
        "🗑 Отменить съёмку?",
        reply_markup=planner_cancel_confirm_keyboard(shoot_id),
    )



async def _cancel_shoot(
    query: CallbackQuery,
    config: Config,
    shoot_id: str,
) -> None:
    """Cancel shoot."""
    if not is_editor_or_admin(query.from_user.id, config):
        await query.answer("Only editors can modify shoots", show_alert=True)
        return
    
    service = PlannerService(config)
    try:
        await service.cancel_shoot(shoot_id)
        await query.answer("✗ Shoot cancelled")
        
        # Return to menu
        await query.message.edit_text(
            "📅 <b>Planner</b>\n\n"
            "Shoot cancelled.\n\n"
            "Select an action:",
            reply_markup=planner_menu_keyboard(),
            parse_mode="HTML",
        )
    
    finally:
        await service.close()


async def _start_reschedule(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    shoot_id: str,
) -> None:
    """Start rescheduling flow."""
    if not is_editor_or_admin(query.from_user.id, config):
        await query.answer("Only editors can modify shoots", show_alert=True)
        return
    
    memory_state.set(
        *_state_ids_from_query(query),
        {
            "flow": "nlp_planner",
            "step": "reschedule_date",
            "shoot_id": shoot_id,
            "screen_chat_id": query.message.chat.id,
            "screen_message_id": query.message.message_id,
        },
    )
    
    today = date.today()
    
    await query.message.edit_text(
        "📅 <b>Reschedule Shoot</b>\n\n"
        "Select new date:",
        reply_markup=calendar_keyboard("planner", today.year, today.month, min_date=today),
        parse_mode="HTML",
    )


async def _start_edit_content(
    query: CallbackQuery,
    config: Config,
    memory_state: MemoryState,
    shoot_id: str,
) -> None:
    """Start editing content."""
    # This would be similar to content selection but for editing
    await query.answer("Edit content coming soon!", show_alert=True)
