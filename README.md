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
Expose your local server and point Telegram to it. cloudflared/ngrok are only needed so Telegram can reach your local `/tg/webhook` endpoint.

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
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://<PUBLIC_URL>/tg/webhook"
```

## Manual deploy via GitHub Actions (WIF + Docker)
Manual deploy only: no auto-deploys on push.

Run via **Actions** → workflow **Manual Deploy — Cloud Run (Docker, WIF)** → **Run workflow**.

Workflow does:
- builds a Docker image
- pushes it to Artifact Registry
- deploys to Cloud Run

Required secrets for Workload Identity Federation:
- `GCP_WIF_PROVIDER`
- `GCP_SA_EMAIL`
- `TELEGRAM_BOT_TOKEN`
- `NOTION_TOKEN`
- `NOTION_ORDERS_DB_ID`
- `NOTION_MODELS_DB_ID`

ALLOWED_EDITORS and TIMEZONE are managed in Cloud Run → Edit & deploy new revision → Variables & secrets,
and the workflow does not overwrite them.

Webhook endpoint path: `/tg/webhook`. After deploy, set the webhook (replace the URL with your Cloud Run service URL):
```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://<PUBLIC_URL>/tg/webhook"
```

## Notes
- Orders DB property names must match (open, model, type, in, out, status, count, comments).
- Models DB uses standard title property name `Name`.
