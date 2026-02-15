from app.keyboards.inline import (
    build_file_type_keyboard,
    build_files_add_keyboard,
    build_files_keyboard,
    build_main_menu_keyboard,
    build_order_card_keyboard,
    build_orders_keyboard,
    build_planner_edit_keyboard,
    build_planner_keyboard,
)


def _texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_has_three_modules():
    kb = build_main_menu_keyboard("tok")
    assert _texts(kb) == ["📦 Заказы", "📂 Планер", "📁 Файлы"]


def test_orders_menu_is_simplified():
    kb = build_orders_keyboard("tok")
    assert _texts(kb) == ["➕ Новый заказ", "📂 Открытые", "🏠 Главное меню"]


def test_order_card_navigation_buttons_present():
    kb = build_order_card_keyboard("123", "tok")
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "order:info:123|tok" in callbacks
    assert "order:edit:123|tok" in callbacks
    assert "order:list|tok" in callbacks


def test_planner_and_files_have_back_and_menu():
    planner = build_planner_edit_keyboard("shoot-1", "tok")
    files_add = build_files_add_keyboard("tok")
    files_types = build_file_type_keyboard("tok")

    assert "◀️ Назад" in _texts(planner)
    assert "🏠 Главное меню" in _texts(planner)
    assert "◀️ Назад" in _texts(files_add)
    assert "🏠 Главное меню" in _texts(files_add)
    assert "◀️ Назад" in _texts(files_types)


def test_files_menu_buttons():
    kb = build_files_keyboard("tok")
    assert _texts(kb) == ["📊 Тек. месяц", "➕ Добавить", "🏠 Главное меню"]


def test_planner_menu_buttons():
    kb = build_planner_keyboard("tok")
    assert _texts(kb) == ["➕ Съёмка", "🖊️ Редактировать", "🏠 Главное меню"]
