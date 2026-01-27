# OROCHIMARY Telegram Orders Bot (MVP)

Backend Telegram bot for managing Notion Orders database with aiogram v3 and webhook deployment on Google Cloud Run.

## Features
- Webhook-based Telegram bot (no long polling).
- Order creation flow: `/orders_create`.
- Order closing flow: `/orders_close`.
- Read-only access for users not in `ALLOWED_EDITORS`.

## Requirements
- Python 3.11+
- Notion integration token with access to Orders and Models databases.
- Telegram bot token.

## Environment variables
- `TELEGRAM_BOT_TOKEN`
- `NOTION_TOKEN`
- `NOTION_ORDERS_DB_ID`
- `NOTION_MODELS_DB_ID`
- `ALLOWED_EDITORS` (comma-separated Telegram user IDs)
- `TIMEZONE` (optional, default `UTC`)

## Local запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...
export NOTION_TOKEN=...
export NOTION_ORDERS_DB_ID=...
export NOTION_MODELS_DB_ID=...
export ALLOWED_EDITORS=123,456
python -m app.server
```

Сервер стартует на `http://localhost:8080`.

## Установка webhook
После деплоя на Cloud Run получите публичный URL (например `https://your-service-xyz.a.run.app`).

```bash
curl -X POST \
  "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-service-xyz.a.run.app/tg/webhook"}'
```

## Notes
- Orders DB property names должны совпадать с требованиями (open, model, type, in, out, status, count, comments).
- Models DB использует стандартное название title property `Name`.
