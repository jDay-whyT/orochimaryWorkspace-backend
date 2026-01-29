import logging
import os

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.bot import create_dispatcher
from app.config import load_config

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


async def create_app() -> web.Application:
    config = load_config()
    bot, dp, notion, _state = create_dispatcher(config)

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app["notion"] = notion
    app["config"] = config

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    setup_application(app, dp, bot=bot)

    async def on_shutdown(_: web.Application) -> None:
        await bot.session.close()
        await notion.close()

    app.on_shutdown.append(on_shutdown)

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def healthcheck(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def telegram_webhook(request: web.Request) -> web.StreamResponse:
        LOGGER.info("Webhook request received")
        secret = config.telegram_webhook_secret
        if secret:
            header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header_secret != secret:
                LOGGER.warning("Webhook secret failed")
                return web.Response(status=403, text="forbidden")
            LOGGER.info("Webhook secret ok")
        else:
            LOGGER.info("Webhook secret not configured; skipping check")
        return await webhook_handler.handle(request)

    app.router.add_get("/", root)
    app.router.add_get("/healthz", healthcheck)
    app.router.add_post("/tg/webhook", telegram_webhook)
    LOGGER.info("HTTP endpoints: GET /, GET /healthz, POST /tg/webhook")
    LOGGER.info("Webhook path: /tg/webhook")
    LOGGER.info("CREATE_QTY_MODE=manual")
    return app


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
