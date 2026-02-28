# OROCHIMARY Telegram Bot

Telegram-бот на **aiogram v3**, который управляет Notion-базами **Models / Orders / Planner / Accounting** и работает через **webhook**. Запускается в **Google Cloud Run**, где сервис **stateless**, поэтому все настройки приходят из **ENV** и критичны правильный webhook и переменные окружения.

## Кратко о проекте

- Бот для управления Notion-базами: **Models**, **Orders**, **Planner**, **Accounting**.
- Основные флоу: **Orders** (CRUD заказов), **Planner** (планирование), **Accounting** (учёт), **Summary** (сводка по модели).
- Cloud Run stateless: без корректных ENV и webhook бот не отвечает.

## Требования

- Python **3.12+**
- **aiogram v3**
- **Notion integration token** + **database IDs**
- **Telegram bot token**
- **GCP project** + **Cloud Run**

## ENV переменные

> Формат списка `ALLOWED_EDITORS`: `"123,456"` (через запятую, без пробелов или с ними — ок).

| Переменная | Обязательно | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен бота от @BotFather |
| `NOTION_TOKEN` | ✅ | Integration token из Notion |
| `DB_MODELS` | ✅ | ID базы **Models** (UUID) |
| `DB_ORDERS` | ✅ | ID базы **Orders** (UUID) |
| `DB_PLANNER` | ✅ | ID базы **Planner** (UUID) |
| `DB_ACCOUNTING` | ✅ | ID базы **Accounting** (UUID) |
| `ALLOWED_EDITORS` | ✅ | Список user_id с доступом к чтению/записи |
| `CRM_TOPIC_THREAD_ID` | ✅ | ID топика CRM в Telegram (целое число > 0) |
| `TELEGRAM_WEBHOOK_SECRET` | ⚠️ | Секрет для проверки заголовка `X-Telegram-Bot-Api-Secret-Token` |
| `TIMEZONE` | ⚠️ | Таймзона, по умолчанию `Europe/Brussels` |
| `FILES_PER_MONTH` | ⚠️ | Лимит файлов в месяц, по умолчанию `200` |
| `INTERNAL_SECRET` | ⚠️ | Секрет для вызова `POST /internal/update-board` |
| `MANAGERS_CHAT_ID` | ⚠️ | Telegram chat_id для менеджеров |
| `MANAGERS_TOPIC_THREAD_ID` | ⚠️ | Telegram topic_thread_id для менеджеров |

> Бот валидирует конфиг при старте: если обязательные переменные не заданы, процесс завершится с ошибкой.

### Авторизация по user_id

- Пользователи из `ALLOWED_EDITORS` имеют доступ к чтению и записи.
- Остальные пользователи могут читать, но не видят кнопки записи и получают ответ “нет доступа” при попытке записи.
- Узнать свой `user_id` можно:
  - Через бота **@userinfobot**.
  - Либо попросить администратора посмотреть лог входящего апдейта.

## Локальный запуск

### Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### ENV через .env

Создайте файл `.env` и заполните значениями:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
NOTION_TOKEN=...
DB_MODELS=...
DB_ORDERS=...
DB_PLANNER=...
DB_ACCOUNTING=...
ALLOWED_EDITORS=123,456
CRM_TOPIC_THREAD_ID=123
TIMEZONE=Europe/Brussels
FILES_PER_MONTH=200
INTERNAL_SECRET=...
```

Затем экспортируйте:

```bash
export $(cat .env | xargs)
```

### ENV через export (Linux/macOS)

```bash
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_WEBHOOK_SECRET=...
export NOTION_TOKEN=...
export DB_MODELS=...
export DB_ORDERS=...
export DB_PLANNER=...
export DB_ACCOUNTING=...
export ALLOWED_EDITORS="123,456"
export CRM_TOPIC_THREAD_ID=123
export TIMEZONE="Europe/Brussels"
export FILES_PER_MONTH=200
export INTERNAL_SECRET=...
```

### ENV через PowerShell

```powershell
$env:TELEGRAM_BOT_TOKEN="..."
$env:TELEGRAM_WEBHOOK_SECRET="..."
$env:NOTION_TOKEN="..."
$env:DB_MODELS="..."
$env:DB_ORDERS="..."
$env:DB_PLANNER="..."
$env:DB_ACCOUNTING="..."
$env:ALLOWED_EDITORS="123,456"
$env:CRM_TOPIC_THREAD_ID="123"
$env:TIMEZONE="Europe/Brussels"
$env:FILES_PER_MONTH="200"
$env:INTERNAL_SECRET="..."
```

### Запуск

```bash
python -m app.server
```

### Проверка

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/
```

В Telegram отправьте `/start` вашему боту.

## Деплой в Cloud Run

### Build & Push

```bash
docker build -t orochimary-bot .
docker tag orochimary-bot gcr.io/YOUR_PROJECT/orochimary-bot:latest
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

> Если хотите ограничить доступ, уберите `--allow-unauthenticated` и настройте IAM.

### Задать ENV в Cloud Run

**Через gcloud:**

```bash
gcloud run services update orochimary-bot \
  --region europe-west1 \
  --set-env-vars "TELEGRAM_BOT_TOKEN=..." \
  --set-env-vars "TELEGRAM_WEBHOOK_SECRET=..." \
  --set-env-vars "NOTION_TOKEN=..." \
  --set-env-vars "ALLOWED_EDITORS=123,456" \
  --set-env-vars "DB_MODELS=..." \
  --set-env-vars "DB_ORDERS=..." \
  --set-env-vars "DB_PLANNER=..." \
  --set-env-vars "DB_ACCOUNTING=..." \
  --set-env-vars "CRM_TOPIC_THREAD_ID=123" \
  --set-env-vars "TIMEZONE=Europe/Brussels" \
  --set-env-vars "FILES_PER_MONTH=200"
```

**Через Console:**

Cloud Run → Service → Edit & Deploy New Revision → **Variables & Secrets**.

### Настройка Webhook

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://YOUR_DOMAIN/tg/webhook\",\"secret_token\":\"$TELEGRAM_WEBHOOK_SECRET\"}"
```

### Проверка

```bash
curl https://YOUR_DOMAIN/healthz
curl https://YOUR_DOMAIN/

curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

### Доступные endpoints

- `GET /` — короткая инфо-страница
- `GET /healthz` — healthcheck
- `POST /tg/webhook` — Telegram webhook
- `POST /internal/update-board` — внутреннее обновление доски (по `X-Internal-Secret`)

## Troubleshooting

### “Бот молчит”

1) **Проверь доступ**: `ALLOWED_EDITORS`.
2) **Проверь webhook**: `/tg/webhook` доступен и Telegram действительно шлёт апдейты.
3) **Проверь логи Cloud Run**: должны быть строки вида `Webhook request received` и `Update handled`.
4) **Проверь fallback-хендлер**: в idle режиме должен отвечать.

### “Update handled, но нет ответа”

Частая ошибка — обработчики вида `@router.message(F.text)` без ограничений по FlowFilter.
Такие хендлеры **глотают все тексты** и не дают другим флоу обработать сообщение.
Используйте ограничения по состояниям/флоу и более узкие фильтры.

### “401/403 в Notion”

- Проверь `NOTION_TOKEN`.
- Проверь, что интеграция имеет доступ ко всем четырём базам.

### “Timeouts”

- Увеличь timeout или уменьши concurrency в Cloud Run.
- Проверь, нет ли долгих операций в обработчиках.

## Структура проекта

```
app/
├── bot.py                 # Dispatcher setup
├── config.py              # Конфиг из ENV
├── roles.py               # Role-based access control
├── server.py              # aiohttp webhook server
├── filters/
│   └── flow.py            # Flow фильтры
├── handlers/
│   ├── start.py           # /start и меню
│   ├── orders.py          # Orders CRUD
│   ├── planner.py         # Planner flow
│   ├── accounting.py      # Accounting flow
│   └── summary.py         # Summary cards
├── services/
│   └── notion.py          # Notion API client
├── state/
│   ├── memory.py          # User state storage
│   └── recent.py          # Recent models
└── utils/
    ├── constants.py       # Константы
    └── formatting.py      # Форматирование
```

## Примеры фраз (NLP)

| Фраза | Что делает |
|---|---|
| `мелиса` | Открыть карточку модели (CRM) |
| `три кастома мелиса` | Создать 3 заказа типа «custom» |
| `мелиса 30 файлов` | Добавить 30 файлов в учёт |
| `мелиса файлы` | Показать статистику файлов |
| `репорт мелиса` | Отчёт за месяц |
| `сводка` | Меню сводки |
| `заказы` | Меню заказов |
| `планировщик` | Меню планировщика |
| `аккаунт` | Меню учёта файлов |

### Карточка модели (CRM)

При вводе имени модели бот показывает карточку:

```
📌 Мелиса
📦 Заказы: open 3
📅 Съёмка: 14.02 (scheduled)
📁 Файлы (фев): 120/200 (60%)

Что делаем?
[➕ Заказ] [📅 Съёмка] [📁 Файлы]
[📋 Заказы] [✓ Закрыть] [📊 Репорт]
```

### Accounting (1 запись/месяц)

- Лимит: `FILES_MONTH_LIMIT = 200`
- Title: `"{MODEL_NAME} · accounting {YYYY-MM}"`
- Кнопки: `+15 / +30 / +50 / Ввод`
- Ручной ввод: 1–500
- Отображение: `X/200 (Y%) +over`

### Planner (контент + статус)

- При создании съёмки: выбор контента (Twitter/Reddit/Main/SFC/Posting/Fansly)
- Автостатус: `scheduled` (дата + контент), `planned` (без одного из них)
- Для существующей ближайшей съёмки: `✅ Done / ↩️ Перенос / 💬 Коммент`

## Безопасность

- **Не коммитьте** токены и секреты.
- По желанию используйте **Secret Manager** + привязку переменных в Cloud Run.
