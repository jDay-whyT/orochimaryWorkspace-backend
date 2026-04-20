# OROCHIMARY Telegram Bot

Telegram-бот на **aiogram v3**, который управляет Notion-базами **Models / Orders / Planner / Accounting** и работает через **webhook**. Запускается в **Google Cloud Run** (stateless), все настройки приходят из ENV.

## Кратко о проекте

- Бот для управления Notion-базами: **Models**, **Orders**, **Planner**, **Accounting**
- NLP-роутер: распознаёт намерения из свободного текста без команд
- Основные флоу: **Orders**, **Planner**, **Accounting**, **Summary**, **Reddit**
- State: Redis (primary) / in-memory fallback
- Cloud Run stateless: без корректных ENV и webhook бот не отвечает

## Требования

- Python **3.12+**
- **aiogram v3**
- **Notion integration token** + database IDs
- **Telegram bot token**
- **GCP project** + **Cloud Run**
- **Redis** (опционально, рекомендуется)

## ENV переменные

> `ALLOWED_EDITORS` и `REPORT_VIEWERS` — через запятую: `"123,456"`

| Переменная | Обязательно | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен бота от @BotFather |
| `NOTION_TOKEN` | ✅ | Integration token из Notion |
| `DB_MODELS` | ✅ | ID базы **Models** (UUID) |
| `DB_ORDERS` | ✅ | ID базы **Orders** (UUID) |
| `DB_PLANNER` | ✅ | ID базы **Planner** (UUID) |
| `DB_ACCOUNTING` | ✅ | ID базы **Accounting** (UUID) |
| `ALLOWED_EDITORS` | ✅ | user_id с доступом к чтению/записи |
| `CRM_TOPIC_THREAD_ID` | ✅ | ID топика CRM в Telegram |
| `REPORT_VIEWERS` | ⚠️ | user_id для scout read-only карточек |
| `SCOUTS_CHAT_ID` | ⚠️ | chat_id скаут-чата |
| `TELEGRAM_WEBHOOK_SECRET` | ⚠️ | Секрет для X-Telegram-Bot-Api-Secret-Token |
| `TIMEZONE` | ⚠️ | Таймзона, по умолчанию `Europe/Brussels` |
| `FILES_PER_MONTH` | ⚠️ | Лимит файлов в месяц, по умолчанию `200` |
| `INTERNAL_SECRET` | ⚠️ | Секрет для `POST /internal/update-board` |
| `MANAGERS_CHAT_ID` | ⚠️ | chat_id для менеджеров |
| `MANAGERS_TOPIC_THREAD_ID` | ⚠️ | topic_thread_id для менеджеров |
| `REDIS_URL` | ⚠️ | Redis URL, например `redis://localhost:6379/0` |
| `BOARD_MESSAGE_ID` | ⚠️ | message_id борда съёмок для редактирования |

## Структура проекта
app/
├── bot.py                   # Dispatcher setup, роутеры
├── config.py                # Конфиг из ENV
├── roles.py                 # Role-based access control
├── server.py                # aiohttp webhook server
├── filters/
│   ├── flow.py              # FlowFilter
│   └── topic_access.py      # TopicAccessMessageFilter
├── handlers/
│   ├── start.py             # /start, NLP fallback
│   ├── orders.py            # Orders CRUD
│   ├── planner.py           # Planner flow
│   ├── accounting.py        # Accounting flow
│   ├── summary.py           # Summary cards
│   ├── reports.py           # Report cards
│   ├── reddit.py            # /reddit борд
│   ├── notifications.py     # /shoots борд
│   ├── nlp_callbacks.py     # inline keyboard callbacks
│   └── group_manager.py     # group triggers
├── router/
│   ├── dispatcher.py        # NLP routing pipeline
│   ├── intent_v2.py         # Intent classification
│   ├── entities_v2.py       # Entity extraction
│   ├── command_filters.py   # Intent + order type mapping
│   ├── model_resolver.py    # Fuzzy model matching
│   └── prefilter.py         # Pre-filter (gibberish, length)
├── services/
│   ├── notion.py            # Notion API client
│   ├── model_card.py        # CRM карточка модели
│   ├── scout_card.py        # Скаут карточка
│   └── accounting.py        # Accounting service
├── state/
│   ├── memory.py            # In-memory state (fallback)
│   ├── recent.py            # Recent models (in-memory)
│   ├── redis_state.py       # Redis-backed state (primary)
│   └── redis_recent.py      # Redis recent models
└── utils/
├── constants.py         # Константы (ORDER_TYPES и др.)
├── formatting.py        # Форматирование дат, текста
├── accounting.py        # Прогресс файлов
├── content_mapping.py   # content type → DB field
└── patterns.py          # Regex паттерны

## NLP команды

| Фраза | Что делает |
|---|---|
| `стейдж` | CRM карточка модели |
| `скаут стейдж` | Скаут карточка |
| `три кастома стейдж` | Создать 3 заказа custom |
| `вериф реддит стейдж` | Заказ верификации (10 шт по умолчанию) |
| `стейдж 30 файлов` | Добавить 30 файлов в учёт месяца |
| `коммент реддит стейдж` | Обновить Reddit комментарий |
| `шут стейдж` | Создать съёмку в планере |
| `репорт стейдж` | Отчёт за месяц |
| `/reddit` | Reddit борд по всем моделям |
| `/shoots` | Борд съёмок на 7 дней |

## Типы заказов (Orders)

| Тип | Описание |
|---|---|
| `custom` | Кастом (создаётся по одному) |
| `short` | Шорт (count в одну запись) |
| `verif reddit` | Верификация Reddit (default 10 шт) |
| `call` | Колл |
| `ad request` | Ad Request |

## Reddit борд (`/reddit`)

Показывает карточки по всем Reddit-моделям:
📌 Sukuna
📅 Прошлая съёмка: 01 апр · done
📅 Следующая: 28 апр · scheduled
📁 Reddit файлов (апр): 87
📋 Вериф: open · 10 шт · 15 апр
💬 комментарий менеджера

Источники: Accounting (фильтр `Content=reddit`) + Planner (новые модели → 🆕) + Orders (открытые `verif reddit`).

## Карточка модели (CRM)
📌 СТЕЙДЖ
📦 Заказы: 2 откр · 1 просрочены
📅 Съёмка: 25 апр · reddit, twitter
📁 Файлы (апр): 120/200 (60%)
Что делаем?
[📦 Заказы] [📅 Съёмка] [📁 Файлы]

## Accounting

- 1 запись на модель в месяц
- Title: `"{MODEL_NAME} {месяц_ru} {год}"` — например `"КЛЕЩ февраль 2026"`
- Поля по типам: `of_files`, `reddit_files`, `twitter_files`, `fansly_files`, `social_files`, `request_files`
- Лимит: `FILES_PER_MONTH` (default 200)

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export $(cat .env | xargs)
python -m app.server
```

Проверка:
```bash
curl http://localhost:8080/healthz
```

## Деплой в Cloud Run

```bash
docker build -t orochimary-bot .
docker tag orochimary-bot gcr.io/YOUR_PROJECT/orochimary-bot:latest
docker push gcr.io/YOUR_PROJECT/orochimary-bot:latest

gcloud run deploy orochimary-bot \
  --image gcr.io/YOUR_PROJECT/orochimary-bot:latest \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated
```

### Webhook

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://YOUR_DOMAIN/tg/webhook\",\"secret_token\":\"$TELEGRAM_WEBHOOK_SECRET\"}"
```

### Cloud Scheduler (борд съёмок, 06:00 UTC)

```bash
gcloud scheduler jobs create http orochimary-daily-board-sync \
  --location=europe-west1 \
  --schedule="0 6 * * *" \
  --uri="https://YOUR_CLOUD_RUN_URL/internal/update-board" \
  --http-method=POST \
  --headers="X-Internal-Secret=YOUR_INTERNAL_SECRET"
```

## Endpoints

| Endpoint | Описание |
|---|---|
| `GET /` | Info |
| `GET /healthz` | Healthcheck |
| `POST /tg/webhook` | Telegram webhook |
| `POST /internal/update-board` | Обновление борда съёмок |

## Troubleshooting

**Бот молчит** — проверь `ALLOWED_EDITORS`, webhook, логи Cloud Run.

**401/403 Notion** — проверь `NOTION_TOKEN` и доступ интеграции ко всем базам.

**Redis недоступен** — бот упадёт на старте если `REDIS_URL` задан но Redis не отвечает. Убери `REDIS_URL` для fallback на in-memory.

**Timeouts** — увеличь timeout или уменьши concurrency в Cloud Run.
