#!/usr/bin/env python3
"""
Тест валидации конфигурации
"""

import sys
from pathlib import Path

import pytest

# Добавить путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

def test_validation(monkeypatch):
    """Тест валидации с пустыми токенами."""
    # Очистим env
    for key in ["TELEGRAM_BOT_TOKEN", "NOTION_TOKEN", "ADMIN_IDS", "EDITOR_IDS", "VIEWER_IDS"]:
        monkeypatch.delenv(key, raising=False)
    
    from app.config import load_config
    
    with pytest.raises(SystemExit) as exc:
        load_config(validate=True)
    assert exc.value.code == 1


def test_valid_config(monkeypatch):
    """Тест с валидной конфигурацией."""
    # Установим валидные значения
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    monkeypatch.setenv("NOTION_TOKEN", "secret_test123")
    monkeypatch.setenv("ADMIN_IDS", "123456")
    monkeypatch.delenv("FILES_PER_MONTH", raising=False)
    
    from app.config import load_config
    
    config = load_config(validate=True)
    assert config.telegram_bot_token == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    assert config.notion_token == "secret_test123"
    assert config.admin_ids == {123456}
    assert config.files_per_month == 180


def test_files_per_month(monkeypatch):
    """Тест использования FILES_PER_MONTH из env."""
    # Установим custom значение
    monkeypatch.setenv("FILES_PER_MONTH", "200")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("NOTION_TOKEN", "secret")
    monkeypatch.setenv("ADMIN_IDS", "123")
    
    from app.config import load_config
    
    config = load_config(validate=True)
    assert config.files_per_month == 200


def test_invalid_files_per_month(monkeypatch):
    """Тест с невалидным FILES_PER_MONTH."""
    # Установим невалидное значение
    monkeypatch.setenv("FILES_PER_MONTH", "-10")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("NOTION_TOKEN", "secret")
    monkeypatch.setenv("ADMIN_IDS", "123")
    
    from app.config import load_config
    
    with pytest.raises(SystemExit) as exc:
        load_config(validate=True)
    assert exc.value.code == 1


def main():
    """Запуск всех тестов."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "ТЕСТЫ ВАЛИДАЦИИ КОНФИГУРАЦИИ" + " " * 25 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    tests = [
        ("Пустые токены", test_validation),
        ("Валидный конфиг", test_valid_config),
        ("FILES_PER_MONTH из env", test_files_per_month),
        ("Невалидный FILES_PER_MONTH", test_invalid_files_per_month),
    ]
    results = {}
    for name, test in tests:
        patch = pytest.MonkeyPatch()
        try:
            test(patch)
            results[name] = True
        except Exception:
            results[name] = False
        finally:
            patch.undo()
    
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
