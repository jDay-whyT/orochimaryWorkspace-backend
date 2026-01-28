import logging

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

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/tg/webhook")
    setup_application(app, dp, bot=bot)

    async def on_shutdown(_: web.Application) -> None:
        await bot.session.close()
        await notion.close()

    app.on_shutdown.append(on_shutdown)

    async def healthcheck(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/healthz", healthcheck)
    return app


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
