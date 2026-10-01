import asyncio
import hmac
import logging
import os
import pathlib
from collections import deque

from aiohttp import web
from aiogram.webhook.aiohttp_server import setup_application

from app.api.scout import api_scout_model_card, api_scout_models
from app.bot import create_dispatcher
from app.config import load_config
from app.handlers.notifications import update_board
from app.handlers import models as models_list
from app.services import access, activity_log
from app.services.forms_watch import run_forms_watch
from app.services.reminders import run_daily_reminders
from app.services.status_sync import run_status_sync
from app.services.wml_scheduled import run_wml_export
from app.services.wml_sync import run_wml_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)

# How long the webhook request stays open while the update is processed. Cloud Run only gives the
# container CPU while a request is in flight (cpu-throttling), so an update handled after an instant
# 200 can stall for tens of seconds. Held open it runs at full speed; past this limit we answer 200
# anyway (Telegram would retry on its own timeout) and the update keeps going in the background.
WEBHOOK_HOLD_SECONDS = 25.0
SHUTDOWN_DRAIN_SECONDS = 8.0  # Cloud Run gives SIGTERM -> SIGKILL ~10 s


def _update_task_done(tasks: set, task: asyncio.Task) -> None:
    tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        LOGGER.error("Update processing failed", exc_info=task.exception())

GIT_SHA = os.environ.get("GIT_SHA", "unknown")


async def create_app() -> web.Application:
    """Create aiohttp application."""
    config = load_config()
    bot, dp, notion, memory_state, recent_models = create_dispatcher(config)

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app["notion"] = notion
    app["config"] = config

    # Redis client for scout identity cache (permanent keys, no TTL).
    # Reuses REDIS_URL from existing config — separate connection pool.
    if config.redis_url:
        from redis.asyncio import Redis as AioRedis
        app["redis"] = AioRedis.from_url(config.redis_url, decode_responses=True)
        LOGGER.info("Scout Redis client initialized")
    dp["redis"] = app.get("redis")  # exposes the same client to aiogram handler DI
    activity_log.init(app.get("redis"))
    models_list.init(app.get("redis"))

    async def warm_models(_app: web.Application) -> None:
        # the first message after a cold start should not wait for the full Models scan
        _app["models_warmup"] = asyncio.create_task(models_list.warm_up(config.db_models, notion))

    app.on_startup.append(warm_models)

    # Managers approved in the bot (/start -> owner button) join the env access lists.
    async def access_middleware(handler, event, data):
        await access.refresh(config, app.get("redis"))
        return await handler(event, data)

    dp.update.outer_middleware(access_middleware)

    # Deduplication: track last 200 update_ids to skip Telegram re-deliveries.
    # deque(maxlen=200) keeps insertion order so we can evict the oldest ID
    # from the companion set before it is silently dropped by the deque.
    app["_seen_update_ids_deque"] = deque(maxlen=200)
    app["_seen_update_ids_set"]: set[int] = set()
    app["_update_tasks"] = set()  # updates still being processed (past the webhook hold, or in flight)

    setup_application(app, dp, bot=bot)

    async def on_shutdown(_app: web.Application) -> None:
        LOGGER.info("Shutting down...")
        pending = set(_app["_update_tasks"])
        if pending:  # let in-flight updates finish before their sessions are closed under them
            LOGGER.info("Waiting for %d in-flight update(s)", len(pending))
            await asyncio.wait(pending, timeout=SHUTDOWN_DRAIN_SECONDS)
        await bot.session.close()
        from app.services.notion import NotionClient
        await NotionClient.close_all()
        redis = _app.get("redis")
        if redis:
            await redis.aclose()
        LOGGER.info("Shutdown complete")

    app.on_shutdown.append(on_shutdown)

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="OROCHIMARY Bot v2.0")

    async def healthcheck(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def internal_update_board(request: web.Request) -> web.Response:
        secret = config.internal_secret
        if not secret or not hmac.compare_digest(request.headers.get("X-Internal-Secret", ""), secret):
            return web.json_response({"ok": False}, status=403)
        await update_board(request.app["bot"], request.app["config"], request.app["notion"])
        return web.json_response({"ok": True})

    async def internal_scrape_wml(request: web.Request) -> web.Response:
        secret = config.internal_secret
        if not secret or not hmac.compare_digest(request.headers.get("X-Internal-Secret", ""), secret):
            return web.json_response({"ok": False}, status=403)
        await run_wml_sync(request.app["bot"], request.app["config"], request.app["notion"], request.app.get("redis"))
        # Independent of WML: run even if the scrape failed.
        await run_forms_watch(request.app["bot"], request.app["config"], request.app["notion"], request.app.get("redis"))
        await run_status_sync(request.app["bot"], request.app["config"], request.app["notion"], request.app.get("redis"))
        return web.json_response({"ok": True})

    async def internal_activity_digest(request: web.Request) -> web.Response:
        secret = config.internal_secret
        if not secret or not hmac.compare_digest(request.headers.get("X-Internal-Secret", ""), secret):
            return web.json_response({"ok": False}, status=403)
        await access.refresh(request.app["config"], request.app.get("redis"), force=True)
        await activity_log.send_daily_digest(request.app["bot"], request.app["config"])
        return web.json_response({"ok": True})

    async def internal_daily_reminders(request: web.Request) -> web.Response:
        secret = config.internal_secret
        if not secret or not hmac.compare_digest(request.headers.get("X-Internal-Secret", ""), secret):
            return web.json_response({"ok": False}, status=403)
        await access.refresh(request.app["config"], request.app.get("redis"), force=True)
        await run_daily_reminders(request.app["bot"], request.app["config"], request.app["notion"])
        return web.json_response({"ok": True})

    async def internal_wml_export(request: web.Request) -> web.Response:
        secret = config.internal_secret
        if not secret or not hmac.compare_digest(request.headers.get("X-Internal-Secret", ""), secret):
            return web.json_response({"ok": False}, status=403)
        await run_wml_export(request.app["bot"], request.app["config"], request.app["notion"], request.app.get("redis"))
        return web.json_response({"ok": True})

    async def telegram_webhook(request: web.Request) -> web.Response:
        # Validate secret first (before parsing body, to fail fast on bad actors).
        secret = config.telegram_webhook_secret
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secret or not hmac.compare_digest(header_secret, secret):
            LOGGER.warning("Webhook secret missing or mismatched")
            return web.Response(status=403, text="forbidden")

        try:
            body = await request.json()
        except Exception:
            LOGGER.warning("Webhook received non-JSON body — ignoring")
            return web.Response(status=200, text="ok")

        update_id = body.get("update_id")
        update_type = (
            "message" if "message" in body
            else "callback_query" if "callback_query" in body
            else "edited_message" if "edited_message" in body
            else f"other({list(body.keys())})"
        )
        LOGGER.info(
            "Webhook request received: update_id=%s type=%s",
            update_id, update_type,
        )

        # Deduplication: skip updates that were already processed.
        if update_id is not None:
            seen_deque: deque = request.app["_seen_update_ids_deque"]
            seen_set: set[int] = request.app["_seen_update_ids_set"]

            if update_id in seen_set:
                LOGGER.info("Duplicate update_id=%s skipped", update_id)
                return web.Response(status=200, text="ok")

            # Evict the oldest entry from the set before the deque drops it.
            if len(seen_deque) == seen_deque.maxlen:
                seen_set.discard(seen_deque[0])

            seen_deque.append(update_id)
            seen_set.add(update_id)

        # Process the update while the request is open (CPU is allocated only then), but never
        # keep Telegram waiting longer than WEBHOOK_HOLD_SECONDS: after that answer 200 and let
        # the task finish in the background. A failing update never turns into a non-200.
        bot = request.app["bot"]
        dp = request.app["dp"]
        task = asyncio.create_task(dp.feed_raw_update(bot=bot, update=body))
        tasks = request.app["_update_tasks"]
        tasks.add(task)
        task.add_done_callback(lambda t: _update_task_done(tasks, t))
        await asyncio.wait({task}, timeout=WEBHOOK_HOLD_SECONDS)

        return web.Response(status=200, text="ok")

    app.router.add_get("/healthz", healthcheck)
    app.router.add_post("/tg/webhook", telegram_webhook)
    app.router.add_post("/internal/update-board", internal_update_board)
    app.router.add_post("/internal/scrape-wml", internal_scrape_wml)
    app.router.add_post("/internal/activity-digest", internal_activity_digest)
    app.router.add_post("/internal/daily-reminders", internal_daily_reminders)
    app.router.add_post("/internal/wml-export", internal_wml_export)

    # Scout Mini App API
    app.router.add_post("/api/scout/models", api_scout_models)
    app.router.add_get("/api/scout/model/{name}", api_scout_model_card)

    # Static mini-app frontend — must come LAST among GET routes.
    # GET /{tail:.*} below is a wildcard that catches every unmatched GET.
    # Any new GET API route added after this block will be shadowed by it.
    # Docker: /app/static/   Local build: frontend/dist/
    _static_candidates = [
        pathlib.Path("/app/static"),
        pathlib.Path(__file__).parent.parent / "frontend" / "dist",
    ]
    _static_dir = next((p for p in _static_candidates if (p / "index.html").exists()), None)
    if _static_dir:
        assets_dir = _static_dir / "assets"
        if assets_dir.is_dir():
            app.router.add_static("/assets", str(assets_dir), name="mini_app_assets")

        async def mini_app_index(_: web.Request) -> web.FileResponse:
            return web.FileResponse(_static_dir / "index.html")

        app.router.add_get("/", mini_app_index)
        app.router.add_get("/{tail:.*}", mini_app_index)
        LOGGER.info("Mini-app static files served from %s", _static_dir)
    else:
        app.router.add_get("/", root)
        LOGGER.info("Mini-app static dir not found — frontend not yet built")

    LOGGER.info(
        "HTTP endpoints registered: GET /, GET /healthz, "
        "POST /tg/webhook, POST /internal/update-board, "
        "POST /internal/scrape-wml, "
        "POST /api/scout/models, GET /api/scout/model/{name}"
    )
    return app


def main() -> None:
    """Run the server."""
    port = int(os.environ.get("PORT", "8080"))
    LOGGER.info("Starting server on port %s  GIT_SHA=%s", port, GIT_SHA)
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
