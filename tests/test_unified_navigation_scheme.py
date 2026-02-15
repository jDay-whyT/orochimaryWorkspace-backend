from app.keyboards.inline import (
    build_main_menu_keyboard,
    build_orders_menu_keyboard,
    build_order_card_keyboard_final,
    build_planner_menu_keyboard,
    build_planner_shoot_edit_keyboard,
    build_files_menu_keyboard,
)


def _texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_has_three_modules():
    kb = build_main_menu_keyboard("tok")
    assert _texts(kb) == ["📦 Заказы", "📂 Планер", "📁 Файлы"]


def test_orders_menu_buttons():
    kb = build_orders_menu_keyboard("tok")
    assert _texts(kb) == ["➕ Новый заказ", "📂 Открытые", "◀️ К карточке"]


def test_order_card_navigation_buttons_present():
    kb = build_order_card_keyboard_final("123", "tok")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "orders|select|123|tok" in callbacks
    assert "orders|comment|123|tok" in callbacks
    assert "orders|open|list|tok" in callbacks


def test_planner_menu_buttons():
    kb = build_planner_menu_keyboard("tok")
    assert _texts(kb) == ["➕ Съёмка", "🖊️ Редактировать", "◀️ К карточке"]


def test_planner_shoot_edit_keyboard():
    kb = build_planner_shoot_edit_keyboard("shoot-1", "tok")
    assert _texts(kb) == [
        "📋 Перенести",
        "🗂 Content",
        "💬 Комментарий",
        "✅ Закрыть",
        "◀️ Назад",
        "◀️ К карточке",
    ]


def test_files_menu_buttons():
    kb = build_files_menu_keyboard("tok")
    assert _texts(kb) == [
        "➕ Добавить файлы",
        "📂 Тип (контент)",
        "💬 Обновить комментарий",
        "◀️ К карточке",
    ]
