# OROCHIMARY Telegram Bot

Telegram-бот на **aiogram v3** для работы с Notion-базами **Models / Orders / Planner / Accounting** через webhook.
Приложение разворачивается в **Google Cloud Run** и работает как stateless-сервис: вся конфигурация задаётся через ENV.

## Возможности

- Управление карточками моделей и быстрый доступ к CRM-потокам.
- Orders flow: создание и сопровождение заказов.
- Planner flow: планирование съёмок и контента.
- Accounting flow: учёт файлов и контроль лимитов.
- NLP/intent-маршрутизация для текстовых команд.

## Технологии

- Python 3.12+
- aiogram 3
- aiohttp (webhook server)
- Notion API
- pytest

## Конфигурация (ENV)

Ниже переменные, которые реально читает `app/config.py`.

| Переменная | Обязательно | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен Telegram-бота |
| `NOTION_TOKEN` | ✅ | Integration token из Notion |
| `DB_MODELS` | ✅ | ID базы Models |
| `DB_ORDERS` | ✅ | ID базы Orders |
| `DB_PLANNER` | ✅ | ID базы Planner |
| `DB_ACCOUNTING` | ✅ | ID базы Accounting |
| `ALLOWED_EDITORS` | ✅ | Список Telegram user_id через запятую, например `123,456` |
| `CRM_TOPIC_THREAD_ID` | ✅ | ID треда (topic) для CRM-сообщений, положительное целое |
| `TELEGRAM_WEBHOOK_SECRET` | ⚠️ | Секрет заголовка `X-Telegram-Bot-Api-Secret-Token` |
| `FILES_PER_MONTH` | ⚠️ | Месячный лимит файлов (по умолчанию `200`) |
| `TIMEZONE` | ⚠️ | Таймзона (по умолчанию `Europe/Brussels`) |
| `PORT` | ⚠️ | Порт HTTP-сервера (по умолчанию `8080`) |

> Важно: приложение валидирует конфиг при старте и завершится с ошибкой, если обязательные значения не заданы.

## Локальный запуск

### 1) Установка зависимостей

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Создайте `.env`

```env
TELEGRAM_BOT_TOKEN=...
NOTION_TOKEN=...
DB_MODELS=...
DB_ORDERS=...
DB_PLANNER=...
DB_ACCOUNTING=...
ALLOWED_EDITORS=123,456
CRM_TOPIC_THREAD_ID=12345
TELEGRAM_WEBHOOK_SECRET=...
FILES_PER_MONTH=200
TIMEZONE=Europe/Brussels
```

### 3) Экспортируйте переменные

```bash
export $(grep -v '^#' .env | xargs)
```

### 4) Запустите сервер

```bash
python -m app.server
```

Сервис поднимет endpoints:
- `GET /`
- `GET /healthz`
- `POST /tg/webhook`

## Проверка локально

```bash
curl http://localhost:8080/
curl http://localhost:8080/healthz
```

Если нужен внешний webhook для локальной проверки, используйте `ngrok`/аналог и выставьте webhook в Telegram API.

## Деплой в Cloud Run

### Build & Push

```bash
docker build -t gcr.io/YOUR_PROJECT/orochimary-bot:latest .
docker push gcr.io/YOUR_PROJECT/orochimary-bot:latest
```

### Deploy

```bash
gcloud run deploy orochimary-bot \
  --image gcr.io/YOUR_PROJECT/orochimary-bot:latest \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated
```

### Настройка переменных окружения

Добавьте все обязательные ENV (`TELEGRAM_BOT_TOKEN`, `NOTION_TOKEN`, `DB_*`, `ALLOWED_EDITORS`, `CRM_TOPIC_THREAD_ID`) и опциональные по необходимости.

### Настройка webhook

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://YOUR_DOMAIN/tg/webhook\",\"secret_token\":\"$TELEGRAM_WEBHOOK_SECRET\"}"
```

### Проверка после деплоя

```bash
curl https://YOUR_DOMAIN/healthz
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

## Тесты и проверки

```bash
pytest -q
python -m compileall app
```

## Структура проекта

```text
app/
├── bot.py
├── config.py
├── server.py
├── handlers/
├── services/
├── router/
├── filters/
├── keyboards/
├── middlewares/
├── state/
└── utils/
```

## Безопасность

- Не коммитьте токены и секреты в репозиторий.
- Для продакшна рекомендуется хранить секреты в Secret Manager.
