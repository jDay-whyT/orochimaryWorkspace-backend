"""HTTP server routing tests.

Verifies route priority after the /mini-app → / migration:
- /healthz and API routes are not shadowed by the SPA wildcard /{tail:.*}
- Static frontend is served from / when frontend/dist exists
- Fallback root handler fires when no static dir is present
"""
import pathlib
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config():
    cfg = MagicMock()
    cfg.redis_url = ""
    cfg.internal_secret = ""
    cfg.telegram_webhook_secret = ""
    cfg.telegram_bot_token = "fake:token"
    cfg.owner_telegram_id = 0
    cfg.allowed_editors = set()
    cfg.db_models = "db_models_id"
    return cfg


def _make_dispatcher_tuple():
    bot = MagicMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock()
    dp = MagicMock()
    dp.feed_raw_update = AsyncMock()
    return bot, dp, MagicMock(), MagicMock(), MagicMock()


_BASE_PATCHES = dict(
    load_config="app.server.load_config",
    create_dispatcher="app.server.create_dispatcher",
    setup_application="app.server.setup_application",
)


async def _build_app():
    """create_app() with heavy dependencies mocked. Uses real static dir if present."""
    from app.server import create_app
    with (
        patch("app.server.load_config", return_value=_make_config()),
        patch("app.server.create_dispatcher", return_value=_make_dispatcher_tuple()),
        patch("app.server.setup_application"),
    ):
        return await create_app()


async def _build_app_no_static():
    """create_app() with static candidates forced to appear absent."""
    from app.server import create_app

    orig_exists = pathlib.Path.exists

    def _hide_index(self: pathlib.Path):
        if self.name == "index.html":
            return False
        return orig_exists(self)

    with (
        patch("app.server.load_config", return_value=_make_config()),
        patch("app.server.create_dispatcher", return_value=_make_dispatcher_tuple()),
        patch("app.server.setup_application"),
        patch.object(pathlib.Path, "exists", _hide_index),
    ):
        return await create_app()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def frontend_dist():
    """Ensure frontend/dist/index.html + a known test asset exist for the test."""
    import app.server as _srv_module

    dist = pathlib.Path(_srv_module.__file__).parent.parent / "frontend" / "dist"
    already_existed = dist.exists()

    if not already_existed:
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html>Scout App</html>")

    assets = dist / "assets"
    assets.mkdir(exist_ok=True)
    # Always inject a fixed-name asset so the test doesn't depend on hashed filenames.
    test_asset = assets / "_test_routing_asset.js"
    test_asset.write_text("// routing test asset")

    yield dist

    test_asset.unlink(missing_ok=True)
    if not already_existed:
        shutil.rmtree(dist)


# ---------------------------------------------------------------------------
# Without static dir
# ---------------------------------------------------------------------------

class TestNoStaticDir:
    """When no index.html is found the bot banner is served at /."""

    @pytest.mark.asyncio
    async def test_healthz_200(self):
        app = await _build_app_no_static()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/healthz")
            assert resp.status == 200
            assert await resp.text() == "ok"

    @pytest.mark.asyncio
    async def test_root_returns_bot_banner(self):
        app = await _build_app_no_static()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 200
            assert "OROCHIMARY" in await resp.text()


# ---------------------------------------------------------------------------
# With static dir
# ---------------------------------------------------------------------------

class TestWithStaticDir:
    """When frontend/dist exists the SPA is served from /."""

    @pytest.mark.asyncio
    async def test_healthz_not_shadowed(self, frontend_dist):
        """/healthz plain route must win over /{tail:.*} wildcard."""
        app = await _build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/healthz")
            assert resp.status == 200
            assert await resp.text() == "ok"

    @pytest.mark.asyncio
    async def test_root_serves_html(self, frontend_dist):
        app = await _build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 200
            assert "<html" in await resp.text()

    @pytest.mark.asyncio
    async def test_spa_deep_route_serves_html(self, frontend_dist):
        """React Router paths like /scout/123 must get index.html."""
        app = await _build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/scout/123")
            assert resp.status == 200
            assert "<html" in await resp.text()

    @pytest.mark.asyncio
    async def test_assets_served(self, frontend_dist):
        app = await _build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/assets/_test_routing_asset.js")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_api_model_card_not_shadowed_by_wildcard(self, frontend_dist):
        """GET /api/scout/model/{name} registered before /{tail:.*} — must reach the API handler, not serve HTML."""
        app = await _build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/scout/model/test")
            # No auth header → 401 from the real API handler, not 200 + HTML
            assert resp.status == 401
            assert "<html" not in await resp.text()

    @pytest.mark.asyncio
    async def test_post_webhook_accepted(self, frontend_dist):
        """POST /tg/webhook must still return 200 (fire-and-forget)."""
        app = await _build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/tg/webhook",
                json={"update_id": 99, "message": {"text": "hi"}},
            )
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_get_webhook_served_as_spa(self, frontend_dist):
        """GET /tg/webhook — POST-only route; GET is caught by /{tail:.*} wildcard.

        Documents intentional SPA behavior: the wildcard wins over the 405 that
        a strict API server would return. Telegram only POSTs, so no practical impact.
        """
        app = await _build_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/tg/webhook")
            assert resp.status == 200
            assert "<html" in await resp.text()
