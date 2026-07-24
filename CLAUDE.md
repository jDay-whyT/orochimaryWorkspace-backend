# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Local development
python -m venv .venv
source .venv/bin/activate       # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt
export $(cat .env | xargs)
python -m app.server             # starts aiohttp on :8080

# Health check
curl http://localhost:8080/healthz

# Tests
pytest                           # all tests (-q by default)
pytest tests/test_nlp_router.py  # single file
pytest tests/test_nlp_router.py::test_name -v  # single test
pytest -m "not integration"      # skip real-API tests (require live Notion API)
```

## Architecture

**Telegram bot** (aiogram v3, webhook mode) managing a Notion-based CRM. Deployed as a stateless Docker container on Google Cloud Run. All config comes from ENV variables — see `app/config.py`.

### Request flow

1. Telegram sends update to `POST /tg/webhook` (aiohttp server in `app/server.py`)
2. Server deduplicates update IDs (tracks last 200), returns 200 immediately, processes async
3. aiogram dispatcher routes to a handler via filters
4. **FlowFilter** (`app/filters/flow.py`) is generic active-flow-gating infra; no router currently uses it (the routers that did — legacy `orders`/`planner`/`accounting` text menus — were removed 2026-07)
5. **NLP router** (`app/router/dispatcher.py`) handles all free-text — runs a pipeline: state check (active `nlp_*` flow?) → prefilter → entity extraction (model name only) → intent classification (SEARCH_MODEL/UNKNOWN) → model resolution → execute handler (show model card, or help text)

### Key layers

| Layer | Path | Purpose |
|---|---|---|
| Entrypoint | `app/server.py` | aiohttp server, webhook + internal endpoints |
| Bot setup | `app/bot.py` | Dispatcher, router registration order, dependency injection |
| Handlers | `app/handlers/` | `nlp_callbacks.py` is the CRM action UI (orders/shoots/files/notes via model-card buttons); plus `reddit`, `notifications`, `tango`, `group_manager`, `start` |
| NLP router | `app/router/` | Intent classification + entity extraction pipeline |
| Services | `app/services/` | Notion API clients per domain; `model_card.py` / `scout_card.py` build Telegram messages |
| State | `app/state/` | Redis (primary, TTL 30 min) or in-memory fallback; recent-models LRU cache |
| Filters | `app/filters/` | `FlowFilter` (active flow check, currently unused), `TopicAccessMessageFilter` (thread security) |
| Keyboards | `app/keyboards/` | Inline keyboard builders + date-picker calendar |
| Utils | `app/utils/` | Constants, formatting, regex patterns, content-type→DB-field mapping |

### Router registration order (app/bot.py)

Order matters — aiogram uses first-match routing:

1. `notifications` — handles `/shoots` (no flow filter)
2. `reddit` — handles `/reddit` (no flow filter)
3. `tango` — handles `/tango` (no flow filter)
4. `nlp_callbacks` — handles `nlp:` prefixed inline keyboard callbacks (the CRM action UI: orders/shoots/files/notes)
5. `group_manager` — group-level triggers
6. `start` — **LAST**: catches all remaining text via the NLP router

There used to be `orders`/`planner`/`accounting` FlowFilter routers here (a legacy text-menu system, entry points were the now-removed `SHOW_ORDERS`/`SHOW_PLANNER`/`SHOW_ACCOUNT` keyword intents). Removed 2026-07 — usage data showed 0 hits in 30 days; all CRM actions go through the `nlp_callbacks` button UI instead.

### Dependency injection

Services are injected via `dp["key"]` in `bot.py` and accessed in handlers via `data["key"]`:
- `dp["config"]` → `Config` dataclass
- `dp["notion"]` → `NotionClient` singleton
- `dp["memory_state"]` → `RedisMemoryState` or `MemoryState`
- `dp["recent_models"]` → `RedisRecentModels` or `RecentModels`

### NLP intent recognition

The bot used to run a keyword-based intent classifier here (shoot/order/files/comment
command words, ~13 intents with a priority ladder). Usage data showed 99% of real
traffic is a bare model name typed with no keyword at all, so the classifier was
removed 2026-07 (`app/router/intent_v2.py` deleted). The pipeline is now trivial:

- `extract_entities_v2` (`app/router/entities_v2.py`) strips `IGNORE_KEYWORDS`
  (still includes the old command words, so e.g. "мелиса кастом" still resolves
  model="мелиса" — the keyword is just a harmless no-op now) and fuzzy-matches
  what remains against the recent-models cache + Notion models list.
- Intent is just `SEARCH_MODEL` (a model was found) or `UNKNOWN` (it wasn't) —
  see `CommandIntent` in `app/router/command_filters.py`.
- All CRM actions (create/close orders, shoots, files, notes, comments) live
  behind the model-card buttons (`nlp:act:*` callbacks in `app/handlers/nlp_callbacks.py`),
  not behind free-text keywords.

### NLP flow states (dispatcher.py)

Active flows set `memory_state["flow"]` to one of these values, which drives subsequent text input handling. All of these are entered via the model-card buttons (`nlp:act:*`), not free-text keywords:

- `nlp_actions` — model card is showing, waiting for a button press
- `nlp_disambiguate` — model selection from multiple/fuzzy matches (Step 5 of the pipeline)
- `nlp_shoot` — shoot date/location/comment entry
- `nlp_order` — order type/date/confirm
- `nlp_close` / `nlp_close_picker` — order selection + close date
- `nlp_files` — file count + content type
- `nlp_note` — note creation
- `nlp_received` — received count tracking
- `nlp_accounting_comment` — accounting comment input

### State management

State key: `state:{chat_id}:{user_id}`, TTL 30 min. `REDIS_URL` env enables Redis backend; omitting it falls back to in-memory (single-instance only). Redis failure on startup crashes the bot if `REDIS_URL` is set.

### Notion data model

Four DB IDs are required env vars (`DB_MODELS`, `DB_ORDERS`, `DB_PLANNER`, `DB_ACCOUNTING`). `DB_FORMS` is optional.

- **Models** — one record per model (name, status, platform info)
- **Orders** — per-model orders. Types: `custom`, `short`, `verif reddit`, `call`, `ad request`. `short` and `verif reddit` support partial closure via `received` accumulation.
- **Planner** — upcoming shoots (date, content type, location)
- **Accounting** — one record per model per month. Title format: `"{MODEL_NAME} {month_ru} {year}"` (e.g. `"ШАНЕЛЬ апрель 2026"`). Fields: `of_files`, `reddit_files`, `twitter_files`, `fansly_files`, `social_files`, `request_files`. Limit: `FILES_PER_MONTH` env (default 200).

### Internal endpoints & boards

Two boards auto-update every 3 hours via Cloud Scheduler:
- `POST /internal/update-board` → shoots board (7-day forecast)
- `POST /internal/update-reddit-board` → Reddit board (all active Reddit models)

Both require `X-Internal-Secret` header matching `INTERNAL_SECRET` env var. Board message IDs are stored as `BOARD_MESSAGE_ID` / `REDDIT_BOARD_MESSAGE_ID` env vars — on first deploy these are unknown: run the command once, read the logged `message_id`, then redeploy with the value set.

### Role-based access

`app/roles.py`: `is_authorized()` always returns `True` (read access is open). `can_edit()` checks `ALLOWED_EDITORS` (comma-separated Telegram user IDs). `REPORT_VIEWERS` gates scout card access. `CRM_TOPIC_THREAD_ID` restricts CRM commands to a specific Telegram topic thread.
