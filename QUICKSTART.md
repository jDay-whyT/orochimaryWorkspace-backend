# Quick Start Guide - OROCHIMARY Bot

Этот гайд поможет запустить бота за 5 минут.

## Шаг 1: Получите необходимые токены

### Telegram Bot Token
1. Откройте [@BotFather](https://t.me/botfather) в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям (придумайте имя и username)
4. Скопируйте полученный токен

### Notion Integration Token
1. Откройте [Notion Integrations](https://www.notion.so/my-integrations)
2. Нажмите "+ New integration"
3. Дайте название (например, "OROCHIMARY Bot")
4. Выберите workspace
5. Скопируйте "Internal Integration Token"

### Notion Database IDs
1. Откройте каждую базу данных в Notion
2. Скопируйте ID из URL:
   ```
   https://notion.so/workspace/DATABASE_NAME-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
                                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                              Это Database ID
   ```
3. Дайте интеграции доступ к каждой базе (Share → Add "OROCHIMARY Bot")

### Telegram User IDs
1. Отправьте любое сообщение боту [@userinfobot](https://t.me/userinfobot)
2. Скопируйте ваш User ID
3. Попросите других пользователей сделать то же самое

---

## Шаг 2: Настройте окружение

```bash
# Клонируйте или распакуйте проект
cd orochimaru-bot

# Создайте .env файл
cp .env.example .env

# Отредактируйте .env и заполните все токены
nano .env  # или используйте любой текстовый редактор
```

Пример заполненного `.env`:
```env
# Telegram
TELEGRAM_BOT_TOKEN=7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
TELEGRAM_WEBHOOK_SECRET=my-super-secret-string-12345

# Notion
NOTION_TOKEN=secret_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890

# Database IDs
DB_MODELS=1fc32bee-e7a0-809f-8bbe-000be8182d4d
DB_ORDERS=20b32bee-e7a0-81ab-b72b-000b78a1e78a
DB_PLANNER=1fb32bee-e7a0-815f-ae1d-000ba6995a1a
DB_ACCOUNTING=1ff32bee-e7a0-8025-a26c-000bc7008ec8

# Roles
ADMIN_IDS=123456789
EDITOR_IDS=987654321,111222333
VIEWER_IDS=444555666

# Settings
TIMEZONE=Europe/Brussels
FILES_PER_MONTH=180
```

---

## Шаг 3: Установите зависимости

### Вариант A: Локальная установка

```bash
# Создайте виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate  # Windows

# Установите зависимости
pip install -r requirements.txt
```

### Вариант B: Docker

```bash
# Соберите образ
docker build -t orochimaru-bot .
```

---

## Шаг 4: Запустите бота

### Локально (для разработки/тестирования)

```bash
# Активируйте окружение (если ещё не активировано)
source .venv/bin/activate

# Запустите сервер
python -m app.server
```

Бот запустится на `http://localhost:8080`

### В Docker

```bash
docker run -p 8080:8080 --env-file .env orochimaru-bot
```

---

## Шаг 5: Настройте webhook (для production)

⚠️ **Только для production с публичным HTTPS URL!**

Для локальной разработки пропустите этот шаг и используйте polling или ngrok.

```bash
# Установите webhook
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{
    \"url\": \"https://your-domain.com/tg/webhook\",
    \"secret_token\": \"<YOUR_WEBHOOK_SECRET>\"
  }"

# Проверьте webhook
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

### Локальная разработка с ngrok

```bash
# Установите ngrok: https://ngrok.com/download
# Запустите бота локально на порту 8080

# В другом терминале:
ngrok http 8080

# Используйте HTTPS URL из ngrok для webhook
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://xxxx-xx-xx-xxx-xxx.ngrok.io/tg/webhook" \
  -d "secret_token=<YOUR_WEBHOOK_SECRET>"
```

---

## Шаг 6: Проверьте работу

### Health Check

```bash
# Проверьте, что сервер работает
curl http://localhost:8080/healthz
# Должно вернуть: ok
```

### Telegram

1. Найдите вашего бота в Telegram
2. Отправьте `/start`
3. Вы должны увидеть приветственное сообщение и главное меню

---

## Troubleshooting

### Бот не отвечает
1. Проверьте логи: `docker logs orochimaru-bot` или вывод терминала
2. Убедитесь, что webhook установлен: `/getWebhookInfo`
3. Проверьте, что порт 8080 открыт и доступен
4. Проверьте правильность `TELEGRAM_BOT_TOKEN`

### "Access denied"
- Убедитесь, что ваш User ID добавлен в `ADMIN_IDS` или `EDITOR_IDS`
- Проверьте, что ID указан без пробелов и спецсимволов

### Ошибки Notion
1. Проверьте `NOTION_TOKEN`
2. Убедитесь, что интеграция добавлена ко всем базам данных (Share → Add integration)
3. Проверьте правильность Database IDs

### "Failed to create session"
- Это исправлено в v2.0.1
- Убедитесь, что используете последнюю версию кода

---

## Полезные команды

```bash
# Проверить синтаксис кода
python3 check_fixes.py

# Просмотреть логи
docker logs -f orochimaru-bot

# Перезапустить Docker контейнер
docker restart orochimaru-bot

# Остановить бота
# Ctrl+C (локально) или:
docker stop orochimaru-bot

# Обновить код и перезапустить
git pull  # если используете git
docker build -t orochimaru-bot .
docker stop orochimaru-bot
docker rm orochimaru-bot
docker run -d -p 8080:8080 --env-file .env --name orochimaru-bot orochimaru-bot
```

---

## Следующие шаги

После успешного запуска:

1. **Настройте роли** - добавьте других пользователей в EDITOR_IDS и VIEWER_IDS
2. **Протестируйте функционал** - создайте заказы, добавьте файлы в Accounting
3. **Настройте мониторинг** - добавьте алерты на `/healthz` endpoint
4. **Разверните на production** - см. README.md секцию "Deploy to Production"

---

## Дополнительные ресурсы

- [README.md](README.md) - Полная документация
- [FIXES_REPORT.md](FIXES_REPORT.md) - Детальный отчёт об исправлениях
- [.env.example](.env.example) - Пример конфигурации

Если возникли проблемы, проверьте [Troubleshooting](#troubleshooting) или откройте issue.
