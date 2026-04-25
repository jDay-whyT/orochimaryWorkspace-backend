# OROCHIMARY Telegram Bot

Telegram-бот на **aiogram v3**, который управляет Notion-базами **Models / Orders / Planner / Accounting** и работает через **webhook**. Запускается в **Google Cloud Run** (stateless), все настройки приходят из ENV.

## Кратко о проекте

- Бот для управления Notion-базами: **Models**, **Orders**, **Planner**, **Accounting**
- NLP-роутер: распознаёт намерения из свободного текста без команд
- Основные флоу: **Orders**, **Planner**, **Accounting**, **Reddit**
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
| `INTERNAL_SECRET` | ⚠️ | Секрет для internal endpoints |
| `MANAGERS_CHAT_ID` | ⚠️ | chat_id группы для борда |
| `MANAGERS_TOPIC_THREAD_ID` | ⚠️ | topic_thread_id борда съёмок |
| `REDDIT_BOARD_TOPIC_THREAD_ID` | ⚠️ | topic_thread_id Reddit борда |
| `BOARD_MESSAGE_ID` | ⚠️ | message_id закреплённого борда съёмок |
| `REDDIT_BOARD_MESSAGE_ID` | ⚠️ | message_id закреплённого Reddit борда |
| `REDIS_URL` | ⚠️ | Redis URL, например `redis://localhost:6379/0` |

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
| `шут стейдж` | Создать съёмку в планере |
| `репорт стейдж` | Отчёт за месяц |
| `/shoots` | Борд съёмок на 7 дней |
| `/reddit` | Reddit борд по всем моделям |

## Типы заказов (Orders)

| Тип | Описание |
|---|---|
| `custom` | Кастом (создаётся по одному) |
| `short` | Шорт (count в одну запись) |
| `verif reddit` | Верификация Reddit (default 10 шт) |
| `call` | Колл |
| `ad request` | Ad Request |

Для типов `short` и `verif reddit` доступно частичное закрытие через кнопку **Внести часть** — накапливает `received`. При `received >= count` заказ закрывается автоматически.

## Reddit борд (`/reddit`)

Показывает карточки по всем Reddit-моделям (источник: Accounting `Content=reddit`, `status=work`):
Reddit · апр 2026 — 14 моделей
ШАНЕЛЬ  28 апр (Пт)
└ scheduled
| last: 15 апр
▸ reddit: 90 | вериф: 7/20
💬 комментарий

Автообновление каждые 3 часа через Cloud Scheduler → `POST /internal/update-reddit-board`.

## Борд съёмок (`/shoots`)

Показывает съёмки на 7 дней вперёд. Автообновление через Cloud Scheduler → `POST /internal/update-board`.

## Скаут карточка
ШАНЕЛЬ · work · СБОРНАЯ
└ @scout → @assist
| es, eng < b1
| anal: plug, fingers  |  calls: No
| traffic: Reddit, Twitter
| rent: no
▸ content: Reddit 90
▸ last shoot: 15 апр · posting, reddit
▸ next shoot: 28 апр · twitter
orders
| done: 11  |  open: 5

## Accounting

- 1 запись на модель в месяц
- Title: `"{MODEL_NAME} {месяц_ru} {год}"` — например `"ШАНЕЛЬ апрель 2026"`
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

### Cloud Scheduler

Борд съёмок (каждые 3 часа):
```bash
gcloud scheduler jobs create http update-shoots-board \
  --location=europe-west1 \
  --schedule="0 */3 * * *" \
  --time-zone="UTC" \
  --uri="https://YOUR_CLOUD_RUN_URL/internal/update-board" \
  --http-method=POST \
  --headers="X-Internal-Secret=YOUR_INTERNAL_SECRET"
```

Reddit борд (каждые 3 часа):
```bash
gcloud scheduler jobs create http update-reddit-board \
  --location=europe-west1 \
  --schedule="0 */3 * * *" \
  --time-zone="UTC" \
  --uri="https://YOUR_CLOUD_RUN_URL/internal/update-reddit-board" \
  --http-method=POST \
  --headers="X-Internal-Secret=YOUR_INTERNAL_SECRET"
```

### Первый запуск бордов

После первого деплоя — вызови каждый endpoint вручную или через `/shoots` и `/reddit`. Бот залогирует `message_id` нового сообщения. Добавь его в Cloud Run ENV как `BOARD_MESSAGE_ID` и `REDDIT_BOARD_MESSAGE_ID` соответственно, затем задеплой снова.

## Endpoints

| Endpoint | Описание |
|---|---|
| `GET /` | Info |
| `GET /healthz` | Healthcheck |
| `POST /tg/webhook` | Telegram webhook |
| `POST /internal/update-board` | Обновление борда съёмок |
| `POST /internal/update-reddit-board` | Обновление Reddit борда |

## Troubleshooting

**Бот молчит** — проверь `ALLOWED_EDITORS`, webhook, логи Cloud Run.

**401/403 Notion** — проверь `NOTION_TOKEN` и доступ интеграции ко всем базам.

**Redis недоступен** — бот упадёт на старте если `REDIS_URL` задан но Redis не отвечает. Убери `REDIS_URL` для fallback на in-memory.

**Timeouts** — увеличь timeout или уменьши concurrency в Cloud Run.

**Борд не обновляется** — проверь `BOARD_MESSAGE_ID` / `REDDIT_BOARD_MESSAGE_ID` в ENV и что `MANAGERS_CHAT_ID` указан верно (с минусом).
