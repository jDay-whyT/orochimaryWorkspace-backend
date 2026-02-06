import logging
import os

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.bot import create_dispatcher
from app.config import load_config

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

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
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

    async def telegram_webhook(request: web.Request) -> web.StreamResponse:
        try:
            body = await request.json()
            update_type = (
                "message" if "message" in body
                else "callback_query" if "callback_query" in body
                else "edited_message" if "edited_message" in body
                else f"other({list(body.keys())})"
            )
            LOGGER.info(
                "Webhook request received: update_id=%s type=%s",
                body.get("update_id"), update_type,
            )
        except Exception:
            LOGGER.info("Webhook request received (non-JSON body)")
        secret = config.telegram_webhook_secret
        if secret:
            header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header_secret != secret:
                LOGGER.warning("Webhook secret mismatch")
                return web.Response(status=403, text="forbidden")
        return await webhook_handler.handle(request)

    app.router.add_get("/", root)
    app.router.add_get("/healthz", healthcheck)
    app.router.add_post("/tg/webhook", telegram_webhook)
    
    LOGGER.info("HTTP endpoints registered: GET /, GET /healthz, POST /tg/webhook")
    return app


def main() -> None:
    """Run the server."""
    port = int(os.environ.get("PORT", "8080"))
    LOGGER.info("Starting server on port %s  GIT_SHA=%s", port, GIT_SHA)
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
