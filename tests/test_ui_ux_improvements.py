from app.keyboards.inline import (
    order_action_keyboard,
    order_close_confirm_keyboard,
    planner_shoot_keyboard,
    planner_cancel_confirm_keyboard,
)
from app.utils.navigation import MODULE_ICONS


def test_module_icons_contains_core_modules():
    assert MODULE_ICONS["orders"] == "📦"
    assert MODULE_ICONS["planner"] == "📅"
    assert MODULE_ICONS["account"] == "💰"


def test_order_close_requires_confirmation_callback():
    kb = order_action_keyboard("ord-1")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "orders|close_today_confirm|ord-1" in callbacks
    assert "orders|close_yesterday_confirm|ord-1" in callbacks


def test_order_close_confirmation_keeps_original_callback_action():
    kb = order_close_confirm_keyboard("ord-1", "today")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "orders|close_today|ord-1" in callbacks


def test_planner_cancel_requires_confirmation_callback():
    kb = planner_shoot_keyboard("shoot-1")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "planner|cancel_confirm|shoot-1" in callbacks


def test_planner_cancel_confirmation_keeps_original_callback_action():
    kb = planner_cancel_confirm_keyboard("shoot-1")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "planner|cancel_shoot|shoot-1" in callbacks
