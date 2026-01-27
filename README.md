# OROCHIMARY Telegram Orders Bot (MVP)

Backend Telegram bot for managing Notion Orders database with aiogram v3 and webhook deployment on Google Cloud Run.

## What it does
- **Create flow** (`/orders_create`): select model → choose type → qty → in date → comments → create orders in Notion.
- **Close flow** (`/orders_close`): select model → list open orders → close today (editors only).

## Env vars
- `TELEGRAM_BOT_TOKEN`
- `NOTION_TOKEN`
- `NOTION_ORDERS_DB_ID`
- `NOTION_MODELS_DB_ID`
- `ALLOWED_EDITORS` (comma-separated Telegram user IDs)
- `TIMEZONE` (optional, default `UTC`)

Example `.env`:
```
TELEGRAM_BOT_TOKEN=123456:abc
NOTION_TOKEN=secret_notion_token
NOTION_ORDERS_DB_ID=aaaaaaaaaaaaaaaaaaaa
NOTION_MODELS_DB_ID=bbbbbbbbbbbbbbbbbbbb
ALLOWED_EDITORS=123,456
TIMEZONE=Europe/Moscow
```

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export $(cat .env | xargs)
python -m app.server
```

Server starts at `http://localhost:8080`.

### Receive webhook locally
Expose your local server and point Telegram to it:

**ngrok**
```bash
ngrok http 8080
```

**Cloudflared**
```bash
cloudflared tunnel --url http://localhost:8080
```

## Set Telegram webhook
After deploy (or after starting ngrok/cloudflared), set webhook to `/tg/webhook`:
```bash
curl -X POST \
  "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-service-xyz.a.run.app/tg/webhook", "secret_token": "your-secret"}'
```

## Deploy to Cloud Run
```bash
gcloud builds submit --tag gcr.io/$PROJECT_ID/orochimary-bot
gcloud run deploy orochimary-bot \
  --image gcr.io/$PROJECT_ID/orochimary-bot \
  --platform managed \
  --region $REGION \
  --set-env-vars TELEGRAM_BOT_TOKEN=...,NOTION_TOKEN=...,NOTION_ORDERS_DB_ID=...,NOTION_MODELS_DB_ID=...,ALLOWED_EDITORS=...
```

## Deploy via GitHub Actions (WIF)
Workflow deploys only from the GitHub Actions UI (manual trigger).

Required secrets for Workload Identity Federation:
- `GCP_WIF_PROVIDER`
- `GCP_SA_EMAIL`
- `GCP_PROJECT`
- `GCP_REGION`
- `CLOUD_RUN_SERVICE`
- `TELEGRAM_BOT_TOKEN`
- `NOTION_TOKEN`
- `NOTION_ORDERS_DB_ID`
- `NOTION_MODELS_DB_ID`
- `ALLOWED_EDITORS`

Optional secrets:
- `TIMEZONE` (default `UTC` if omitted)

Manual deploy steps:
1. Open **Actions** → **Deploy to Cloud Run**.
2. Click **Run workflow**.
3. (Optional) Provide `region` and/or `service` inputs to override the defaults.

Публичный URL сервиса можно узнать в Cloud Run после деплоя, затем установить webhook:
```bash
curl -X POST https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook \
  -d "url=https://<cloud-run-url>/tg/webhook"
```

## Notes
- Orders DB property names must match (open, model, type, in, out, status, count, comments).
- Models DB uses standard title property name `Name`.
