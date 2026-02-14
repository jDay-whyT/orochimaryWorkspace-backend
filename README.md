# OROCHIMARY Telegram Bot

Telegram-бот на **aiogram v3**, который управляет Notion-базами **Models / Orders / Planner / Accounting** и работает через **webhook**. Запускается в **Google Cloud Run**, где сервис **stateless**, поэтому все настройки приходят из **ENV** и критичны правильный webhook и переменные окружения.

## Кратко о проекте

- Бот для управления Notion-базами: **Models**, **Orders**, **Planner**, **Accounting**.
- Основные флоу: **Orders** (CRUD заказов), **Planner** (планирование), **Accounting** (учёт), **Summary** (сводка по модели).
- Cloud Run stateless: без корректных ENV и webhook бот не отвечает.

## Что нового в README

- Обновлена структура проекта под текущее состояние репозитория.
- Добавлены команды для проверки качества (тесты и линтеры).
- Добавлен раздел с быстрыми командами для разработки.

## Требования

- Python **3.12+**
- **aiogram v3**
- **Notion integration token** + **database IDs**
- **Telegram bot token**
- **GCP project** + **Cloud Run**

## ENV переменные

> Формат списка ALLOWED_EDITORS: `"123,456"` (через запятую, без пробелов или с ними — ок).

| Переменная | Обязательно | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен бота от @BotFather |
| `NOTION_TOKEN` | ✅ | Integration token из Notion |
| `NOTION_DB_MODELS_ID` | ✅ | ID базы **Models** |
| `NOTION_DB_ORDERS_ID` | ✅ | ID базы **Orders** |
| `NOTION_DB_PLANNER_ID` | ✅ | ID базы **Planner** |
| `NOTION_DB_ACCOUNTING_ID` | ✅ | ID базы **Accounting** |
| `ALLOWED_EDITORS` | ✅ | Список user_id с доступом к чтению/записи |
| `WEBHOOK_SECRET` | ⚠️ | Секрет для проверки заголовка `X-Telegram-Bot-Api-Secret-Token` |
| `LOG_LEVEL` | ⚠️ | Уровень логирования (например `INFO`, `DEBUG`) |

> В коде используются имена: `DB_MODELS`, `DB_ORDERS`, `DB_PLANNER`, `DB_ACCOUNTING`, а также `TELEGRAM_WEBHOOK_SECRET`. Ниже в примерах показано, как задать переменные в обоих форматах (удобно при деплое).

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
NOTION_TOKEN=...
NOTION_DB_MODELS_ID=...
NOTION_DB_ORDERS_ID=...
NOTION_DB_PLANNER_ID=...
NOTION_DB_ACCOUNTING_ID=...
ALLOWED_EDITORS=123,456
WEBHOOK_SECRET=...
LOG_LEVEL=INFO

# Маппинг на реальные env, которые читает код
DB_MODELS=${NOTION_DB_MODELS_ID}
DB_ORDERS=${NOTION_DB_ORDERS_ID}
DB_PLANNER=${NOTION_DB_PLANNER_ID}
DB_ACCOUNTING=${NOTION_DB_ACCOUNTING_ID}
TELEGRAM_WEBHOOK_SECRET=${WEBHOOK_SECRET}
```

Затем экспортируйте:

```bash
export $(cat .env | xargs)
```

### ENV через export (Linux/macOS)

```bash
export TELEGRAM_BOT_TOKEN=...
export NOTION_TOKEN=...
export NOTION_DB_MODELS_ID=...
export NOTION_DB_ORDERS_ID=...
export NOTION_DB_PLANNER_ID=...
export NOTION_DB_ACCOUNTING_ID=...
export ALLOWED_EDITORS="123,456"
export WEBHOOK_SECRET=...

export DB_MODELS=$NOTION_DB_MODELS_ID
export DB_ORDERS=$NOTION_DB_ORDERS_ID
export DB_PLANNER=$NOTION_DB_PLANNER_ID
export DB_ACCOUNTING=$NOTION_DB_ACCOUNTING_ID
export TELEGRAM_WEBHOOK_SECRET=$WEBHOOK_SECRET
```

### ENV через PowerShell

```powershell
$env:TELEGRAM_BOT_TOKEN="..."
$env:NOTION_TOKEN="..."
$env:NOTION_DB_MODELS_ID="..."
$env:NOTION_DB_ORDERS_ID="..."
$env:NOTION_DB_PLANNER_ID="..."
$env:NOTION_DB_ACCOUNTING_ID="..."
$env:ALLOWED_EDITORS="123,456"
$env:WEBHOOK_SECRET="..."

$env:DB_MODELS=$env:NOTION_DB_MODELS_ID
$env:DB_ORDERS=$env:NOTION_DB_ORDERS_ID
$env:DB_PLANNER=$env:NOTION_DB_PLANNER_ID
$env:DB_ACCOUNTING=$env:NOTION_DB_ACCOUNTING_ID
$env:TELEGRAM_WEBHOOK_SECRET=$env:WEBHOOK_SECRET
```

### Запуск

```bash
python -m app.server
```

Если нужен локальный webhook-тест, можно пробросить порт через `ngrok` и выставить webhook на публичный URL вида `https://<id>.ngrok-free.app/tg/webhook`.

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
  --set-env-vars "NOTION_TOKEN=..." \
  --set-env-vars "ALLOWED_EDITORS=123,456" \
  --set-env-vars "NOTION_DB_MODELS_ID=..." \
  --set-env-vars "NOTION_DB_ORDERS_ID=..." \
  --set-env-vars "NOTION_DB_PLANNER_ID=..." \
  --set-env-vars "NOTION_DB_ACCOUNTING_ID=..." \
  --set-env-vars "WEBHOOK_SECRET=..." \
  --set-env-vars "DB_MODELS=..." \
  --set-env-vars "DB_ORDERS=..." \
  --set-env-vars "DB_PLANNER=..." \
  --set-env-vars "DB_ACCOUNTING=..." \
  --set-env-vars "TELEGRAM_WEBHOOK_SECRET=..."
```

**Через Console:**

Cloud Run → Service → Edit & Deploy New Revision → **Variables & Secrets**.

### Настройка Webhook

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://YOUR_DOMAIN/tg/webhook\",\"secret_token\":\"$WEBHOOK_SECRET\"}"
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
├── keyboards/             # Inline/Reply клавиатуры
├── middlewares/           # Middleware (в т.ч. проверка webhook secret)
├── filters/
│   └── flow.py            # Flow фильтры
├── handlers/
│   ├── start.py           # /start и меню
│   ├── models.py          # Карточки и операции по моделям
│   ├── orders.py          # Orders CRUD
│   ├── planner.py         # Planner flow
│   ├── accounting.py      # Accounting flow
│   ├── reports.py         # Отчёты
│   ├── nlp_callbacks.py   # NLP callbacks
│   └── summary.py         # Summary cards
├── services/
│   ├── notion.py          # Notion API client
│   ├── models.py          # Работа с базой Models
│   ├── orders.py          # Работа с базой Orders
│   ├── planner.py         # Работа с базой Planner
│   ├── accounting.py      # Работа с базой Accounting
│   └── model_card.py      # Агрегация данных карточки модели
├── state/
│   ├── memory.py          # User state storage
│   └── recent.py          # Recent models
└── utils/
    ├── constants.py       # Константы
    └── formatting.py      # Форматирование
```

## Проверки и качество

```bash
pytest -q
python -m compileall app
```

## Быстрые команды разработки

```bash
# запуск сервера
python -m app.server

# проверка webhook локально
curl -X POST http://localhost:8080/tg/webhook

# healthcheck
curl http://localhost:8080/healthz
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
