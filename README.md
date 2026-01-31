# OROCHIMARY Telegram Bot v2.0.1

✅ **Production Ready** - All critical issues fixed

Telegram bot for managing Notion databases: Models, Orders, Planner, Accounting.

## 🎯 Status

| Feature | Status | Notes |
|---------|--------|-------|
| Orders | ✅ Complete | Full CRUD functionality |
| Accounting | ✅ Complete | Add files, view stats |
| Summary | ✅ Complete | Model cards, quick actions |
| Planner | ⚠️ Stub | Informative message, awaiting implementation |

## 🔧 Recent Fixes (v2.0.1)

- ✅ Fixed critical API mismatch: `get_recent()` → `get()`
- ✅ Added missing import: `RecentModels` in `start.py`
- ✅ Implemented Singleton pattern for `NotionClient` (prevents session leaks)
- ✅ Fixed hardcoded `FILES_PER_MONTH` value
- ✅ Changed default timezone to `Europe/Brussels` (europe-west1)
- ✅ Improved Planner stub with informative message
- ✅ Added proper shutdown hooks for resource cleanup

See [FIXES_REPORT.md](FIXES_REPORT.md) for detailed changelog.

## Architecture

```
app/
├── server.py           # aiohttp webhook server
├── config.py           # Configuration from env
├── bot.py              # Dispatcher setup
├── roles.py            # Role-based access control
├── handlers/
│   ├── start.py        # /start and main menu
│   ├── orders.py       # Orders CRUD
│   ├── planner.py      # Planner CRUD (Phase 3)
│   ├── accounting.py   # Accounting CRUD (Phase 4)
│   └── summary.py      # Model summary cards
├── services/
│   └── notion.py       # Notion API client
├── state/
│   ├── memory.py       # User state storage
│   └── recent.py       # Recent models tracking
├── keyboards/
│   ├── main.py         # Reply keyboards
│   ├── inline.py       # Inline keyboards
│   └── calendar.py     # Inline calendar
└── utils/
    ├── constants.py    # Constants
    └── formatting.py   # Date/text formatting
```

## Databases

| Database | Collection ID | Purpose |
|----------|--------------|---------|
| Models | `1fc32bee-e7a0-809f-8bbe-000be8182d4d` | Models (model, status, project, winrate) |
| Orders | `20b32bee-e7a0-81ab-b72b-000b78a1e78a` | Orders (open, model, type, in, out, status, count, comments) |
| Planner | `1fb32bee-e7a0-815f-ae1d-000ba6995a1a` | Shoots (model, date, status, content, location, comments) |
| Accounting | `1ff32bee-e7a0-8025-a26c-000bc7008ec8` | Files (model, %, amount, content, status, comments) |

## Roles

| Role | Access |
|------|--------|
| Admin | Full access |
| Editor | CRUD for Orders/Planner/Accounting |
| Viewer | Only Summary (read-only) |

## Features

### Core ✅
- Project structure
- Config with database IDs
- Role-based access control (Admin/Editor/Viewer)
- Main menu navigation
- Notion API client with Singleton pattern (prevents resource leaks)
- Recent models tracking

### Orders ✅
- View open orders with pagination
- Close order (with date selection: today/yesterday)
- Add comments to orders
- Create new order flow:
  - Select model (from recent history or search)
  - Select type (short, ad request, call, custom)
  - Select quantity
  - Select date (today/yesterday)
  - Add optional comment
  - Confirmation screen

### Accounting ✅
- View current month records
- Add files to models
- Update content types
- Add comments
- View statistics

### Summary ✅
- Model summary cards with full stats
- Quick actions:
  - View debts (unpaid orders)
  - View all orders
  - Quick add files
- Recent models tracking

### Planner ⚠️
- Currently showing informative stub message
- Planned features:
  - View upcoming shoots
  - Create new shoot with calendar
  - Mark shoots as done/reschedule/cancel

## Environment Variables

```env
# Telegram
TELEGRAM_BOT_TOKEN=           # Get from @BotFather
TELEGRAM_WEBHOOK_SECRET=      # Random string for webhook security

# Notion
NOTION_TOKEN=                 # Notion Integration Token

# Database IDs (Collection IDs from Notion)
DB_MODELS=1fc32bee-e7a0-809f-8bbe-000be8182d4d
DB_ORDERS=20b32bee-e7a0-81ab-b72b-000b78a1e78a
DB_PLANNER=1fb32bee-e7a0-815f-ae1d-000ba6995a1a
DB_ACCOUNTING=1ff32bee-e7a0-8025-a26c-000bc7008ec8

# Roles (comma-separated Telegram user IDs)
ADMIN_IDS=123456              # Full access
EDITOR_IDS=111111,222222      # CRUD for Orders/Planner/Accounting
VIEWER_IDS=333333,444444      # Read-only Summary access

# Settings
TIMEZONE=Europe/Brussels      # Default for europe-west1 region (UTC+1/+2)
FILES_PER_MONTH=180          # For accounting percentage calculations
```

**Note:** `TIMEZONE` supports any valid IANA timezone (e.g., `Europe/Paris`, `UTC`, `America/New_York`)

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values
export $(cat .env | xargs)
python -m app.server
```

## Deploy to Production

### Prerequisites
- Docker installed
- Cloud Run or similar container platform
- Domain with HTTPS

### Build Docker Image

```bash
docker build -t orochimaru-bot .
docker tag orochimaru-bot gcr.io/YOUR_PROJECT/orochimaru-bot:latest
docker push gcr.io/YOUR_PROJECT/orochimaru-bot:latest
```

### Deploy to Cloud Run (europe-west1)

```bash
gcloud run deploy orochimaru-bot \
  --image gcr.io/YOUR_PROJECT/orochimaru-bot:latest \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN" \
  --set-env-vars "TELEGRAM_WEBHOOK_SECRET=$TELEGRAM_WEBHOOK_SECRET" \
  --set-env-vars "NOTION_TOKEN=$NOTION_TOKEN" \
  --set-env-vars "TIMEZONE=Europe/Brussels"
  # ... add other env vars
```

### Set Telegram Webhook

After deployment, configure the webhook:

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{
    \"url\": \"https://YOUR_DOMAIN/tg/webhook\",
    \"secret_token\": \"$TELEGRAM_WEBHOOK_SECRET\"
  }"
```

### Verify Deployment

```bash
# Check health
curl https://YOUR_DOMAIN/healthz
# Should return: ok

# Check info
curl https://YOUR_DOMAIN/
# Should return: OROCHIMARY Bot v2.0

# Check Telegram webhook
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

## Monitoring

### Health Check Endpoint
- `GET /healthz` - Returns "ok" if service is running

### Logs
```bash
# Cloud Run logs
gcloud run logs tail orochimaru-bot --region europe-west1

# Docker logs
docker logs -f orochimaru-bot
```
