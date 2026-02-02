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

> Формат списков ролей: `"123,456"` (через запятую, без пробелов или с ними — ок).

| Переменная | Обязательно | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Токен бота от @BotFather |
| `NOTION_TOKEN` | ✅ | Integration token из Notion |
| `NOTION_DB_MODELS_ID` | ✅ | ID базы **Models** |
| `NOTION_DB_ORDERS_ID` | ✅ | ID базы **Orders** |
| `NOTION_DB_PLANNER_ID` | ✅ | ID базы **Planner** |
| `NOTION_DB_ACCOUNTING_ID` | ✅ | ID базы **Accounting** |
| `ADMIN_IDS` | ✅ | Список user_id с полным доступом |
| `EDITOR_IDS` | ✅ | Список user_id с доступом к CRUD (Orders/Planner/Accounting) |
| `VIEWER_IDS` | ✅ | Список user_id только на чтение (Summary) |
| `WEBHOOK_SECRET` | ⚠️ | Секрет для проверки заголовка `X-Telegram-Bot-Api-Secret-Token` |
| `LOG_LEVEL` | ⚠️ | Уровень логирования (например `INFO`, `DEBUG`) |

> В коде используются имена: `DB_MODELS`, `DB_ORDERS`, `DB_PLANNER`, `DB_ACCOUNTING`, а также `TELEGRAM_WEBHOOK_SECRET`. Ниже в примерах показано, как задать переменные в обоих форматах (удобно при деплое).

### Авторизация по user_id

- Если `user_id` пользователя **не входит** ни в один список ролей (`ADMIN_IDS`, `EDITOR_IDS`, `VIEWER_IDS`) — бот отвечает **“Access denied”**.
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
ADMIN_IDS=123,456
EDITOR_IDS=
VIEWER_IDS=
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
export ADMIN_IDS="123,456"
export EDITOR_IDS=""
export VIEWER_IDS=""
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
$env:ADMIN_IDS="123,456"
$env:EDITOR_IDS=""
$env:VIEWER_IDS=""
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
  --set-env-vars "ADMIN_IDS=123,456" \
  --set-env-vars "EDITOR_IDS=" \
  --set-env-vars "VIEWER_IDS=" \
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

1) **Проверь роли**: `ADMIN_IDS/EDITOR_IDS/VIEWER_IDS`.
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

## Безопасность

- **Не коммитьте** токены и секреты.
- По желанию используйте **Secret Manager** + привязку переменных в Cloud Run.

