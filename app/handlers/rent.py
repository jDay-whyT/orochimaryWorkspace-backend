"""Rent search handler — /rent command."""
import logging
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import Config
from app.filters.flow import FlowFilter
from app.filters.topic_access import RentTopicCallbackFilter, RentTopicFilter
from app.keyboards.calendar import calendar_keyboard, parse_calendar_navigation
from app.services.rent_search import RentListing, search_rentals
from app.state.memory import MemoryState

LOGGER = logging.getLogger(__name__)

router = Router(name="rent")
router.message.filter(RentTopicFilter())
router.callback_query.filter(RentTopicCallbackFilter())

CALENDAR_PREFIX = "rent"


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _budget_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="$30", callback_data="rent|budget|30"),
        InlineKeyboardButton(text="$50", callback_data="rent|budget|50"),
        InlineKeyboardButton(text="$100", callback_data="rent|budget|100"),
    )
    builder.row(InlineKeyboardButton(text="✏️ Своё", callback_data="rent|budget|custom"))
    builder.row(InlineKeyboardButton(text="✖ Отмена", callback_data="rent|cancel|cancel"))
    return builder.as_markup()


def _checkin_calendar(today: date) -> InlineKeyboardMarkup:
    return calendar_keyboard(
        prefix=CALENDAR_PREFIX,
        year=today.year,
        month=today.month,
        min_date=today,
    )


def _checkout_calendar(checkin: date) -> InlineKeyboardMarkup:
    min_checkout = checkin + timedelta(days=1)
    return calendar_keyboard(
        prefix=CALENDAR_PREFIX,
        year=min_checkout.year,
        month=min_checkout.month,
        min_date=min_checkout,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_results(listings: list[RentListing]) -> str:
    if not listings:
        return "😔 Ничего не нашёл по этим параметрам"
    lines = []
    for listing in listings:
        icon = "🔵" if listing.source == "booking" else "🟠"
        parts = [f"{icon} {listing.name}", f"${listing.price_per_night:.0f}/ночь"]
        if listing.rating is not None:
            parts.append(f"⭐{listing.rating:.1f}")
        parts.append(listing.url)
        lines.append(" · ".join(parts))
    return "\n".join(lines)


async def _run_search(
    searching_msg: Message,
    city: str,
    checkin: date,
    checkout: date,
    budget: int,
    api_key: str,
    omkar_token: str,
    memory_state: MemoryState,
    chat_id: int,
    user_id: int,
) -> None:
    memory_state.clear(chat_id, user_id)
    listings = await search_rentals(city, checkin, checkout, budget, api_key, omkar_token=omkar_token)
    nights = (checkout - checkin).days
    header = (
        f"🏠 {city} · {checkin} → {checkout} ({nights} н.) · до ${budget}/ночь\n\n"
    )
    await searching_msg.edit_text(
        header + _format_results(listings),
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------
# /rent command
# ---------------------------------------------------------------------------

@router.message(Command("rent"))
async def cmd_rent(message: Message, memory_state: MemoryState) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id
    today = date.today()

    args = (message.text or "").split(maxsplit=1)
    city = args[1].strip() if len(args) > 1 else None

    if city:
        memory_state.set(chat_id, user_id, {
            "flow": "rent",
            "step": "checkin",
            "city": city,
            "checkin": None,
            "checkout": None,
        })
        await message.answer(
            f"📅 Город: {city}\n\nВыбери дату въезда:",
            reply_markup=_checkin_calendar(today),
        )
    else:
        memory_state.set(chat_id, user_id, {
            "flow": "rent",
            "step": "city",
            "city": None,
            "checkin": None,
            "checkout": None,
        })
        await message.answer("🏙 В каком городе ищем жильё?")


# ---------------------------------------------------------------------------
# Text input (city name or manual budget)
# ---------------------------------------------------------------------------

@router.message(FlowFilter({"rent"}))
async def handle_rent_text(
    message: Message,
    memory_state: MemoryState,
    config: Config,
) -> None:
    chat_id = message.chat.id
    user_id = message.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    step = state.get("step")
    today = date.today()

    if step == "city":
        city = (message.text or "").strip()
        if not city:
            return
        memory_state.set(chat_id, user_id, {**state, "city": city, "step": "checkin"})
        await message.answer(
            f"📅 Город: {city}\n\nВыбери дату въезда:",
            reply_markup=_checkin_calendar(today),
        )

    elif step == "budget_input":
        raw = (message.text or "").strip().replace("$", "").replace(",", "")
        try:
            budget = int(float(raw))
            if budget <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Введи число, например: 75")
            return

        city = state.get("city", "")
        checkin_str = state.get("checkin")
        checkout_str = state.get("checkout")
        if not (city and checkin_str and checkout_str):
            memory_state.clear(chat_id, user_id)
            await message.answer("Что-то пошло не так, начни заново: /rent")
            return

        searching_msg = await message.answer("🔍 Ищу...")
        await _run_search(
            searching_msg,
            city=city,
            checkin=date.fromisoformat(checkin_str),
            checkout=date.fromisoformat(checkout_str),
            budget=budget,
            api_key=config.apify_token,
            omkar_token=config.omkar_token,
            memory_state=memory_state,
            chat_id=chat_id,
            user_id=user_id,
        )


# ---------------------------------------------------------------------------
# Callback handler (all rent| prefixed callbacks)
# ---------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith("rent|"))
async def rent_callback(
    query: CallbackQuery,
    memory_state: MemoryState,
    config: Config,
) -> None:
    parts = (query.data or "").split("|", 2)
    if len(parts) < 3:
        await query.answer()
        return
    _, action, value = parts

    # --- ignore (calendar header / empty cells) ---
    if action == "cal_ignore":
        await query.answer()
        return

    # --- cancel ---
    if action == "cancel":
        chat_id = query.message.chat.id
        user_id = query.from_user.id
        memory_state.clear(chat_id, user_id)
        await query.answer("Отменено")
        await query.message.edit_text("✖ Поиск жилья отменён.", reply_markup=None)
        return

    chat_id = query.message.chat.id
    user_id = query.from_user.id
    state = memory_state.get(chat_id, user_id) or {}
    step = state.get("step")
    today = date.today()

    # --- back (from calendar) ---
    if action == "back":
        if step == "checkout":
            # Go back to checkin calendar
            memory_state.set(chat_id, user_id, {**state, "step": "checkin", "checkin": None})
            await query.answer()
            await query.message.edit_text(
                "📅 Выбери дату въезда:",
                reply_markup=_checkin_calendar(today),
            )
        else:
            # step == "checkin" or unknown — cancel
            memory_state.clear(chat_id, user_id)
            await query.answer("Отменено")
            await query.message.edit_text("✖ Поиск жилья отменён.", reply_markup=None)
        return

    # --- calendar navigation ---
    if action == "cal_nav":
        parsed = parse_calendar_navigation(value)
        if not parsed:
            await query.answer()
            return
        year, month = parsed
        if step == "checkin":
            await query.answer()
            await query.message.edit_reply_markup(
                reply_markup=calendar_keyboard(
                    prefix=CALENDAR_PREFIX, year=year, month=month, min_date=today
                )
            )
        elif step == "checkout":
            checkin_str = state.get("checkin")
            min_checkout = (
                date.fromisoformat(checkin_str) + timedelta(days=1)
                if checkin_str
                else today + timedelta(days=1)
            )
            await query.answer()
            await query.message.edit_reply_markup(
                reply_markup=calendar_keyboard(
                    prefix=CALENDAR_PREFIX, year=year, month=month, min_date=min_checkout
                )
            )
        else:
            await query.answer()
        return

    # --- date selected ---
    if action == "cal_day":
        try:
            selected = date.fromisoformat(value)
        except ValueError:
            await query.answer()
            return

        if step == "checkin":
            default_checkout = selected + timedelta(days=7)
            memory_state.set(chat_id, user_id, {
                **state,
                "step": "checkout",
                "checkin": selected.isoformat(),
            })
            await query.answer()
            await query.message.edit_text(
                f"📅 Въезд: {selected}\n\nВыбери дату выезда:\n"
                f"(по умолчанию +7 дней: {default_checkout})",
                reply_markup=_checkout_calendar(selected),
            )

        elif step == "checkout":
            checkin_str = state.get("checkin")
            if not checkin_str:
                await query.answer("Начни заново: /rent")
                return
            checkin = date.fromisoformat(checkin_str)
            if selected <= checkin:
                await query.answer("Дата выезда должна быть позже въезда")
                return
            memory_state.set(chat_id, user_id, {
                **state,
                "step": "budget",
                "checkout": selected.isoformat(),
            })
            nights = (selected - checkin).days
            await query.answer()
            await query.message.edit_text(
                f"📅 Въезд: {checkin} → Выезд: {selected} ({nights} н.)\n\n"
                "💵 Бюджет на ночь?",
                reply_markup=_budget_keyboard(),
            )
        else:
            await query.answer()
        return

    # --- budget selected ---
    if action == "budget":
        if value == "custom":
            memory_state.set(chat_id, user_id, {**state, "step": "budget_input"})
            await query.answer()
            await query.message.edit_text(
                "✏️ Введи максимальный бюджет в долларах за ночь (число):",
                reply_markup=None,
            )
            return

        try:
            budget = int(value)
        except ValueError:
            await query.answer()
            return

        city = state.get("city", "")
        checkin_str = state.get("checkin")
        checkout_str = state.get("checkout")
        if not (city and checkin_str and checkout_str):
            memory_state.clear(chat_id, user_id)
            await query.answer("Что-то пошло не так")
            await query.message.edit_text("Начни заново: /rent", reply_markup=None)
            return

        await query.answer()
        await query.message.edit_text("🔍 Ищу...", reply_markup=None)
        await _run_search(
            query.message,
            city=city,
            checkin=date.fromisoformat(checkin_str),
            checkout=date.fromisoformat(checkout_str),
            budget=budget,
            api_key=config.apify_token,
            omkar_token=config.omkar_token,
            memory_state=memory_state,
            chat_id=chat_id,
            user_id=user_id,
        )
        return

    await query.answer()
