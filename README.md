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

> `ALLOWED_EDITORS` — через запятую: `"123,456"`

| Переменная | Обязательно | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен бота от @BotFather |
| `NOTION_TOKEN` | ✅ | Integration token из Notion |
| `DB_MODELS` | ✅ | ID базы **Models** (UUID) |
| `DB_ORDERS` | ✅ | ID базы **Orders** (UUID) |
| `DB_PLANNER` | ✅ | ID базы **Planner** (UUID) |
| `DB_ACCOUNTING` | ✅ | ID базы **Accounting** (UUID) |
| `ARCHIVE_PAGE_ID` | ⚠️ | ID архивной страницы Notion для поиска прошлых Reddit accounting баз |
| `ALLOWED_EDITORS` | ✅ | user_id с доступом к чтению/записи |
| `CRM_TOPIC_THREAD_ID` | ✅ | ID топика CRM в Telegram |
| `MINI_APP_VIEWERS` | ⚠️ | user_id для просмотра мини-апп (все модели, без доступа к боту) |
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

```
app/
├── bot.py                   # Dispatcher setup, роутеры
├── config.py                # Конфиг из ENV
├── roles.py                 # Role-based access control
├── server.py                # aiohttp webhook server + mini-app + internal endpoints
├── api/
│   ├── auth.py               # Telegram Mini App initData HMAC-SHA256 валидация
│   └── scout.py               # Scout Mini App API handlers
├── filters/
│   ├── flow.py               # FlowFilter
│   └── topic_access.py        # TopicAccessMessageFilter / TopicAccessCallbackFilter
├── handlers/
│   ├── start.py               # /start, NLP fallback
│   ├── models.py              # Model search handlers для NLP роутинга
│   ├── nlp_callbacks.py       # CRM action UI: orders/shoots/files/notes через кнопки карточки модели
│   ├── reddit.py               # /reddit борд
│   ├── notifications.py        # /shoots борд
│   ├── tango.py                # /tango расписание (Google Sheets)
│   └── group_manager.py        # group triggers
├── router/
│   ├── dispatcher.py          # NLP routing pipeline (model-name search only)
│   ├── entities_v2.py          # Entity extraction (model name)
│   ├── command_filters.py      # IGNORE_KEYWORDS + CommandIntent (SEARCH_MODEL/UNKNOWN)
│   ├── model_resolver.py       # Fuzzy model matching
│   └── prefilter.py            # Pre-filter (gibberish, length)
├── services/
│   ├── notion.py               # Notion API client
│   ├── models.py                # Models service (поиск/чтение карточек моделей)
│   ├── orders.py                 # Orders: TTL-кеш открытых заказов
│   ├── planner.py                # Planner: TTL-кеш съёмок
│   ├── accounting.py              # Accounting: TTL-кеш месячных записей
│   ├── model_card.py             # CRM карточка модели
│   ├── scout_card.py              # Скаут карточка
│   ├── sheets.py                   # Google Sheets client (для /tango)
│   └── tango_schedule.py            # Парсинг расписания из Sheets
├── keyboards/
│   ├── inline.py               # Все inline-клавиатуры NLP-флоу
│   └── calendar.py              # Календарь для выбора дат
├── state/
│   ├── memory.py                # In-memory state (fallback)
│   ├── recent.py                 # Recent models (in-memory)
│   ├── redis_state.py            # Redis-backed state (primary)
│   ├── redis_recent.py            # Redis recent models
│   └── token.py                   # Anti-stale token helpers (k) для NLP-клавиатур
└── utils/
    ├── constants.py             # Константы (статусы заказов/планера/аккаунтинга и др.)
    ├── formatting.py             # Форматирование дат, текста
    ├── accounting.py              # Прогресс файлов
    ├── content_mapping.py          # content type → DB field
    ├── patterns.py                 # Regex паттерны
    ├── telegram.py                  # safe_answer/safe_edit_message — flood-control retry
    └── locks.py                      # per-(chat,user) asyncio.Lock, общий для текста и callback
```

## Архитектура: state, локи, кеш

Это не просто справочник — это инварианты, которые ловили реальные продовые баги (2026-07-27), так что при добавлении нового флоу их нужно соблюдать:

1. **Один lock на пользователя для текста и callback.** `route_message` (текстовые сообщения) и `handle_nlp_callback` (нажатия inline-кнопок) — два разных роутера, но оба читают/пишут один и тот же `memory_state` для данного `(chat_id, user_id)`. Без общего лока (`app/utils/locks.get_user_lock`) быстрое сообщение + нажатие кнопки от одного юзера обрабатываются параллельными корутинами и могут перезаписать состояние друг друга — например, подтверждение заказа читает `model_id`, который параллельный текстовый поиск уже заменил на другую модель (или очистил). Оба хендлера оборачивают всё тело в `async with get_user_lock(chat_id, user_id):`.
2. **Каждая запись в Notion → clear_cache.** `orders.py` / `planner.py` / `accounting.py` держат in-memory TTL-кеш (60с) на модель. Любой `notion.create_/update_/close_/reschedule_*` вызов обязан сопровождаться соответствующим `*_cache.clear_cache(model_id, ...)` сразу после успешной записи — иначе бот до 60 секунд показывает старые данные (заказ, помеченный закрытым, всё ещё выглядит открытым).
3. **Новая клавиатура — гаси старую.** Перед тем как открыть новый экран (`memory_state.set(...)` с новым токеном `k`), вызови `_clear_previous_screen_keyboard(...)`, читая текущий `screen_message_id` из состояния **до** его перезаписи. Иначе старая клавиатура остаётся кликабельной, а нажатие на неё после смены токена валится в "Сессия устарела, откройте модель заново".

## NLP команды

Free-text intent recognition used to have ~13 keyword-based intents (кастом/шорт/
съемка/файлы/etc). Usage data (30 days, July 2026) showed 99% of real traffic was
just a bare model name, so the keyword classifier was removed. Now:

| Фраза | Что делает |
|---|---|
| `стейдж` (любое имя модели) | CRM карточка модели — с неё кнопками создаются заказы, съёмки, файлы, заметки |
| `/shoots` | Борд съёмок на 7 дней |
| `/reddit` | Reddit борд по всем моделям |

Старые keyword-команды (`три кастома стейдж`, `стейдж 30 файлов`, `шут стейдж` и
т.п.) больше не выполняют действие напрямую — слова из старого словаря просто
игнорируются при поиске имени модели (`IGNORE_KEYWORDS`), так что "стейдж 30
файлов" по-прежнему находит модель "стейдж" и показывает карточку.

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

```
Reddit · апр 2026 — 14 моделей
ШАНЕЛЬ  28 апр (Пт)
└ scheduled
| last: 15 апр
▸ reddit: 90 | вериф: 7/20
💬 комментарий
```

Автообновление каждые 3 часа через Cloud Scheduler → `POST /internal/update-reddit-board`.

## Борд съёмок (`/shoots`)

Показывает съёмки на 7 дней вперёд. Автообновление через Cloud Scheduler → `POST /internal/update-board`.

## Скаут карточка

```
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
```

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
  --set-env-vars ARCHIVE_PAGE_ID=22332beee7a08089b33ed051a223f63f \
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
| `POST /api/scout/models` | Mini App: список моделей для скаута |
| `GET /api/scout/model/{name}` | Mini App: карточка модели по имени |
| `POST /api/scout/verify` | Mini App: HMAC-валидация Telegram initData (`app/api/auth.py`) |
| `GET /` `GET /{tail:.*}` | Раздача Scout Mini App (статика + SPA fallback), если собран `frontend/dist` (или `/app/static` в Docker) |

## Troubleshooting

**Бот молчит** — проверь `ALLOWED_EDITORS`, webhook, логи Cloud Run.

**401/403 Notion** — проверь `NOTION_TOKEN` и доступ интеграции ко всем базам.

**Redis недоступен** — бот упадёт на старте если `REDIS_URL` задан но Redis не отвечает. Убери `REDIS_URL` для fallback на in-memory.

**Timeouts** — увеличь timeout или уменьши concurrency в Cloud Run.

**Борд не обновляется** — проверь `BOARD_MESSAGE_ID` / `REDDIT_BOARD_MESSAGE_ID` в ENV и что `MANAGERS_CHAT_ID` указан верно (с минусом).

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
