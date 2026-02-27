import asyncio
import logging
import os
from collections import deque

from aiohttp import web
from aiogram.webhook.aiohttp_server import setup_application

from app.bot import create_dispatcher
from app.config import load_config
from app.handlers.notifications import update_board

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)

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

    # Deduplication: track last 200 update_ids to skip Telegram re-deliveries.
    # deque(maxlen=200) keeps insertion order so we can evict the oldest ID
    # from the companion set before it is silently dropped by the deque.
    app["_seen_update_ids_deque"] = deque(maxlen=200)
    app["_seen_update_ids_set"]: set[int] = set()

    setup_application(app, dp, bot=bot)

    async def on_shutdown(_: web.Application) -> None:
        LOGGER.info("Shutting down...")
        await bot.session.close()
        # Close all NotionClient singleton instances
        from app.services.notion import NotionClient
        await NotionClient.close_all()
        LOGGER.info("Shutdown complete")

    app.on_shutdown.append(on_shutdown)

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="OROCHIMARY Bot v2.0")

    async def healthcheck(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def internal_update_board(request: web.Request) -> web.Response:
        secret = config.internal_secret
        if not secret:
            return web.json_response({"ok": False}, status=403)
        if request.headers.get("X-Internal-Secret", "") != secret:
            return web.json_response({"ok": False}, status=403)
        await update_board(request.app["bot"], request.app["config"], request.app["notion"])
        return web.json_response({"ok": True})

    async def telegram_webhook(request: web.Request) -> web.Response:
        # Validate secret first (before parsing body, to fail fast on bad actors).
        secret = config.telegram_webhook_secret
        if secret:
            header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header_secret != secret:
                LOGGER.warning("Webhook secret mismatch")
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

        # Fire-and-forget: return 200 immediately so Telegram never retries,
        # then process the update in a background task.
        bot = request.app["bot"]
        dp = request.app["dp"]
        asyncio.create_task(dp.feed_raw_update(bot=bot, update=body))

        return web.Response(status=200, text="ok")

    app.router.add_get("/", root)
    app.router.add_get("/healthz", healthcheck)
    app.router.add_post("/tg/webhook", telegram_webhook)
    app.router.add_post("/internal/update-board", internal_update_board)

    LOGGER.info("HTTP endpoints registered: GET /, GET /healthz, POST /tg/webhook, POST /internal/update-board")
    return app


def main() -> None:
    """Run the server."""
    port = int(os.environ.get("PORT", "8080"))
    LOGGER.info("Starting server on port %s  GIT_SHA=%s", port, GIT_SHA)
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
