#!/usr/bin/env python3
"""
Тест валидации конфигурации
"""

import os
import sys
from pathlib import Path

# Добавить путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

def test_validation():
    """Тест валидации с пустыми токенами."""
    print("=" * 70)
    print("Тест 1: Валидация с пустыми токенами")
    print("=" * 70)
    
    # Очистим env
    for key in ["TELEGRAM_BOT_TOKEN", "NOTION_TOKEN", "ADMIN_IDS", "EDITOR_IDS", "VIEWER_IDS"]:
        os.environ.pop(key, None)
    
    from app.config import load_config, ConfigValidationError
    
    try:
        config = load_config(validate=True)
        print("❌ FAIL: Должна была вылететь ошибка валидации")
        return False
    except SystemExit as e:
        if e.code == 1:
            print("✅ PASS: Валидация сработала, бот не запустился")
            return True
        else:
            print(f"❌ FAIL: Неожиданный exit code: {e.code}")
            return False
    except Exception as e:
        print(f"❌ FAIL: Неожиданная ошибка: {e}")
        return False


def test_valid_config():
    """Тест с валидной конфигурацией."""
    print("\n" + "=" * 70)
    print("Тест 2: Валидная конфигурация")
    print("=" * 70)
    
    # Установим валидные значения
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    os.environ["NOTION_TOKEN"] = "secret_test123"
    os.environ["ADMIN_IDS"] = "123456"
    
    from app.config import load_config
    
    try:
        config = load_config(validate=True)
        print("✅ PASS: Конфиг загружен успешно")
        print(f"   - Telegram Token: {'*' * 20}...{config.telegram_bot_token[-4:]}")
        print(f"   - Notion Token: {'*' * 20}")
        print(f"   - Admin IDs: {config.admin_ids}")
        print(f"   - FILES_PER_MONTH: {config.files_per_month}")
        return True
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False


def test_files_per_month():
    """Тест использования FILES_PER_MONTH из env."""
    print("\n" + "=" * 70)
    print("Тест 3: FILES_PER_MONTH из environment")
    print("=" * 70)
    
    # Установим custom значение
    os.environ["FILES_PER_MONTH"] = "200"
    
    from app.config import load_config
    
    try:
        # Перезагрузим модуль чтобы взять новое значение
        import importlib
        import app.config
        importlib.reload(app.config)
        
        config = app.config.load_config(validate=True)
        
        if config.files_per_month == 200:
            print(f"✅ PASS: FILES_PER_MONTH = {config.files_per_month} (из env)")
            return True
        else:
            print(f"❌ FAIL: FILES_PER_MONTH = {config.files_per_month}, ожидалось 200")
            return False
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False


def test_invalid_files_per_month():
    """Тест с невалидным FILES_PER_MONTH."""
    print("\n" + "=" * 70)
    print("Тест 4: Невалидный FILES_PER_MONTH")
    print("=" * 70)
    
    # Установим невалидное значение
    os.environ["FILES_PER_MONTH"] = "-10"
    
    from app.config import load_config
    
    try:
        # Перезагрузим модуль
        import importlib
        import app.config
        importlib.reload(app.config)
        
        config = app.config.load_config(validate=True)
        print("❌ FAIL: Должна была вылететь ошибка для отрицательного значения")
        return False
    except SystemExit as e:
        if e.code == 1:
            print("✅ PASS: Валидация отклонила отрицательное значение")
            return True
        else:
            print(f"❌ FAIL: Неожиданный exit code: {e.code}")
            return False
    except Exception as e:
        print(f"❌ FAIL: Неожиданная ошибка: {e}")
        return False


def main():
    """Запуск всех тестов."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "ТЕСТЫ ВАЛИДАЦИИ КОНФИГУРАЦИИ" + " " * 25 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    results = {
        "Пустые токены": test_validation(),
        "Валидный конфиг": test_valid_config(),
        "FILES_PER_MONTH из env": test_files_per_month(),
        "Невалидный FILES_PER_MONTH": test_invalid_files_per_month(),
    }
    
    print("\n" + "=" * 70)
    print("ИТОГИ")
    print("=" * 70)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print()
    
    all_passed = all(results.values())
    if all_passed:
        print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        return 0
    else:
        print("❌ НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ")
        return 1


if __name__ == "__main__":
    sys.exit(main())
