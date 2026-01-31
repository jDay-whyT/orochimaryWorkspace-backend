#!/usr/bin/env python3
"""
Скрипт проверки исправлений Orochimaru Bot
Проверяет, что все критические проблемы исправлены
"""

import sys
import ast
from pathlib import Path

def check_imports():
    """Проверка импортов"""
    print("=" * 70)
    print("1. Проверка импортов")
    print("=" * 70)
    
    # Проверка импорта RecentModels в start.py
    start_py = Path("app/handlers/start.py")
    if not start_py.exists():
        print("❌ Файл app/handlers/start.py не найден")
        return False
    
    content = start_py.read_text()
    if "from app.state import RecentModels" in content:
        print("✅ RecentModels импортирован в start.py")
    else:
        print("❌ RecentModels НЕ импортирован в start.py")
        return False
    
    # Проверка импорта FILES_PER_MONTH в notion.py
    notion_py = Path("app/services/notion.py")
    if not notion_py.exists():
        print("❌ Файл app/services/notion.py не найден")
        return False
    
    content = notion_py.read_text()
    if "from app.utils.constants import FILES_PER_MONTH" in content:
        print("✅ FILES_PER_MONTH импортирован в notion.py")
    else:
        print("❌ FILES_PER_MONTH НЕ импортирован в notion.py")
        return False
    
    print()
    return True


def check_api_calls():
    """Проверка вызовов API"""
    print("=" * 70)
    print("2. Проверка вызовов get_recent() -> get()")
    print("=" * 70)
    
    files_to_check = [
        "app/handlers/summary.py",
        "app/handlers/accounting.py"
    ]
    
    all_fixed = True
    for filepath in files_to_check:
        path = Path(filepath)
        if not path.exists():
            print(f"❌ Файл {filepath} не найден")
            all_fixed = False
            continue
        
        content = path.read_text()
        if "get_recent(" in content:
            print(f"❌ {filepath}: найден вызов get_recent()")
            # Покажем строки с проблемой
            for i, line in enumerate(content.split('\n'), 1):
                if "get_recent(" in line:
                    print(f"   Строка {i}: {line.strip()}")
            all_fixed = False
        else:
            print(f"✅ {filepath}: get_recent() исправлен на get()")
    
    print()
    return all_fixed


def check_hardcoded_values():
    """Проверка хардкодов"""
    print("=" * 70)
    print("3. Проверка использования константы FILES_PER_MONTH")
    print("=" * 70)
    
    notion_py = Path("app/services/notion.py")
    if not notion_py.exists():
        print("❌ Файл app/services/notion.py не найден")
        return False
    
    content = notion_py.read_text()
    
    # Проверяем, что нет хардкода 180
    if "/ 180.0" in content or "/ 180" in content:
        print("❌ Найден хардкод 180 в notion.py")
        for i, line in enumerate(content.split('\n'), 1):
            if "/ 180" in line:
                print(f"   Строка {i}: {line.strip()}")
        return False
    
    # Проверяем, что используется FILES_PER_MONTH
    if "FILES_PER_MONTH" in content and "percent = amount / float(FILES_PER_MONTH)" in content:
        print("✅ FILES_PER_MONTH используется корректно")
    else:
        print("⚠️  FILES_PER_MONTH импортирован, но может не использоваться")
        return False
    
    print()
    return True


def check_singleton_pattern():
    """Проверка singleton паттерна для NotionClient"""
    print("=" * 70)
    print("4. Проверка singleton паттерна NotionClient")
    print("=" * 70)
    
    notion_py = Path("app/services/notion.py")
    if not notion_py.exists():
        print("❌ Файл app/services/notion.py не найден")
        return False
    
    content = notion_py.read_text()
    
    checks = [
        ("_instances", "словарь для хранения singleton-инстансов"),
        ("__new__", "переопределение __new__ для singleton"),
        ("close_all", "метод для закрытия всех инстансов"),
    ]
    
    all_present = True
    for check, description in checks:
        if check in content:
            print(f"✅ Найден {description}")
        else:
            print(f"❌ Не найден {description}")
            all_present = False
    
    print()
    return all_present


def check_timezone():
    """Проверка timezone"""
    print("=" * 70)
    print("5. Проверка timezone (europe-west1)")
    print("=" * 70)
    
    env_example = Path(".env.example")
    if not env_example.exists():
        print("❌ Файл .env.example не найден")
        return False
    
    content = env_example.read_text()
    
    if "TIMEZONE=Europe/Brussels" in content:
        print("✅ Timezone установлен на Europe/Brussels (europe-west1)")
    elif "TIMEZONE=Europe/Paris" in content:
        print("✅ Timezone установлен на Europe/Paris (europe-west1)")
    else:
        print("⚠️  Timezone не установлен на europe-west1 зону")
        for line in content.split('\n'):
            if "TIMEZONE=" in line:
                print(f"   Текущее значение: {line}")
        return False
    
    print()
    return True


def check_syntax():
    """Проверка синтаксиса Python файлов"""
    print("=" * 70)
    print("6. Проверка синтаксиса Python")
    print("=" * 70)
    
    files_to_check = [
        "app/handlers/start.py",
        "app/handlers/summary.py",
        "app/handlers/accounting.py",
        "app/services/notion.py",
        "app/config.py",
    ]
    
    all_valid = True
    for filepath in files_to_check:
        path = Path(filepath)
        if not path.exists():
            print(f"⚠️  {filepath} не найден, пропускаем")
            continue
        
        try:
            content = path.read_text()
            ast.parse(content)
            print(f"✅ {filepath}: синтаксис корректен")
        except SyntaxError as e:
            print(f"❌ {filepath}: ошибка синтаксиса на строке {e.lineno}")
            print(f"   {e.msg}")
            all_valid = False
    
    print()
    return all_valid


def main():
    """Запуск всех проверок"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "ПРОВЕРКА ИСПРАВЛЕНИЙ OROCHIMARU BOT" + " " * 18 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    results = {
        "Импорты": check_imports(),
        "API вызовы": check_api_calls(),
        "Константы": check_hardcoded_values(),
        "Singleton": check_singleton_pattern(),
        "Timezone": check_timezone(),
        "Синтаксис": check_syntax(),
    }
    
    print("=" * 70)
    print("ИТОГОВЫЙ РЕЗУЛЬТАТ")
    print("=" * 70)
    
    for check_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {check_name}")
    
    print()
    
    all_passed = all(results.values())
    if all_passed:
        print("🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
        print()
        print("Проект готов к запуску:")
        print("  1. Скопируйте .env.example в .env")
        print("  2. Заполните необходимые токены и ID")
        print("  3. Запустите: python -m app.server")
        return 0
    else:
        print("❌ НЕКОТОРЫЕ ПРОВЕРКИ НЕ ПРОЙДЕНЫ")
        print()
        print("Проверьте ошибки выше и исправьте проблемы.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
