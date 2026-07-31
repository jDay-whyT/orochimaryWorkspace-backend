"""Tests for app/api/scout.py — Mini App scout endpoints.

Previously had zero test coverage, including the api_scout_verify IDOR fix
(caller could bind an arbitrary handle to their own user id) — see
[[project_security_review_jul2026]]. Handlers are called directly against
real aiohttp Request objects (aiohttp.test_utils.make_mocked_request) rather
than through a live server, matching the request.app dict-access pattern
the handlers use (a plain dict satisfies both `request.app["x"]` and
`request.app.get("x")`).
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import make_mocked_request

from app.api import scout

BOT_TOKEN = "123456:test-bot-token"


def _init_data(user: dict, bot_token: str = BOT_TOKEN) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


def _config(**overrides):
    cfg = MagicMock()
    cfg.telegram_bot_token = BOT_TOKEN
    cfg.owner_telegram_id = 0
    cfg.allowed_editors = set()
    cfg.mini_app_viewer_ids = set()
    cfg.mini_app_viewer_handles = set()
    cfg.db_models = "db_models_id"
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _request(user: dict | None, app: dict, method="GET", path="/api/scout/models",
             match_info=None, json_body=None, no_auth=False):
    headers = {} if no_auth else {"Authorization": f"tma {_init_data(user)}"}
    req = make_mocked_request(method, path, headers=headers, app=app, match_info=match_info or {})
    if json_body is not None:
        async def _json():
            return json_body
        req.json = _json
    return req


class TestApiScoutModels:
    @pytest.mark.asyncio
    async def test_no_auth_header_returns_401(self):
        req = _request(None, {"config": _config(), "notion": MagicMock()}, no_auth=True)
        resp = await scout.api_scout_models(req)
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_owner_gets_full_model_list(self):
        notion = MagicMock()
        model = MagicMock(page_id="p1", title="Model A", project="OF", status="active", scout="@a")
        notion.query_models = AsyncMock(return_value=[model])
        cfg = _config(owner_telegram_id=42)
        req = _request({"id": 42}, {"config": cfg, "notion": notion}, path="/api/scout/models")
        resp = await scout.api_scout_models(req)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["scout"] is None
        assert body["models"][0]["name"] == "Model A"
        notion.query_models.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scout_with_cached_handle_queries_models_by_scout(self):
        notion = MagicMock()
        model = MagicMock(page_id="p1", title="Model B", project="OF", status="active", scout="@scout1")
        notion.query_models_by_scout = AsyncMock(return_value=[model])
        redis = MagicMock()
        redis.get = AsyncMock(return_value="@scout1")
        cfg = _config()
        req = _request({"id": 7, "username": "scout1"}, {"config": cfg, "notion": notion, "redis": redis})
        resp = await scout.api_scout_models(req)
        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["scout"] == "@scout1"
        notion.query_models_by_scout.assert_awaited_once_with("db_models_id", "@scout1")

    @pytest.mark.asyncio
    async def test_unverified_scout_returns_status_unverified(self):
        notion = MagicMock()
        notion.query_models_by_scout = AsyncMock(return_value=[])
        cfg = _config()
        req = _request({"id": 7, "username": "nobody"}, {"config": cfg, "notion": notion})
        resp = await scout.api_scout_models(req)
        assert resp.status == 200
        assert json.loads(resp.body) == {"status": "unverified"}


class TestApiScoutModelCard:
    @pytest.mark.asyncio
    async def test_forbidden_when_model_not_in_scouts_list(self):
        notion = MagicMock()
        allowed_model = MagicMock(title="Allowed Model")
        notion.query_models_by_scout = AsyncMock(return_value=[allowed_model])
        cfg = _config()
        req = _request({"id": 7, "username": "scout1"}, {"config": cfg, "notion": notion},
                        match_info={"name": "Other Model"})
        resp = await scout.api_scout_model_card(req)
        assert resp.status == 403

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, monkeypatch):
        notion = MagicMock()
        cfg = _config(owner_telegram_id=42)
        monkeypatch.setattr("app.services.scout_card.build_scout_report_card_json", AsyncMock(return_value=None))
        req = _request({"id": 42}, {"config": cfg, "notion": notion}, match_info={"name": "Ghost"})
        resp = await scout.api_scout_model_card(req)
        assert resp.status == 404


class TestApiScoutVerify:
    @pytest.mark.asyncio
    async def test_own_handle_binds_successfully(self):
        notion = MagicMock()
        model = MagicMock()
        notion.query_models_by_scout = AsyncMock(return_value=[model])
        redis = MagicMock()
        redis.set = AsyncMock()
        cfg = _config()
        req = _request({"id": 7, "username": "scout1"}, {"config": cfg, "notion": notion, "redis": redis},
                        method="POST", path="/api/scout/verify", json_body={"handle": "scout1"})
        resp = await scout.api_scout_verify(req)
        assert resp.status == 200
        assert json.loads(resp.body) == {"status": "ok", "scout": "@scout1"}
        redis.set.assert_awaited_once_with("scout:7", "@scout1", ex=86400)

    @pytest.mark.asyncio
    async def test_other_users_handle_is_rejected_idor(self):
        """Regression test for the IDOR fix: submitting someone else's handle
        must be rejected before any Notion lookup happens."""
        notion = MagicMock()
        notion.query_models_by_scout = AsyncMock()
        cfg = _config()
        req = _request({"id": 7, "username": "scout1"}, {"config": cfg, "notion": notion},
                        method="POST", path="/api/scout/verify", json_body={"handle": "someone_elses_scout"})
        resp = await scout.api_scout_verify(req)
        assert resp.status == 403
        notion.query_models_by_scout.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_telegram_username_rejected(self):
        cfg = _config()
        req = _request({"id": 7}, {"config": cfg, "notion": MagicMock()},
                        method="POST", path="/api/scout/verify", json_body={"handle": "scout1"})
        resp = await scout.api_scout_verify(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_invalid_json_body_rejected(self):
        cfg = _config()
        req = make_mocked_request(
            "POST", "/api/scout/verify",
            headers={"Authorization": f"tma {_init_data({'id': 7, 'username': 'scout1'})}"},
            app={"config": cfg, "notion": MagicMock()},
        )
        async def _bad_json():
            raise ValueError("not json")
        req.json = _bad_json
        resp = await scout.api_scout_verify(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_handle_not_found_in_notion_returns_404(self):
        notion = MagicMock()
        notion.query_models_by_scout = AsyncMock(return_value=[])
        cfg = _config()
        req = _request({"id": 7, "username": "scout1"}, {"config": cfg, "notion": notion},
                        method="POST", path="/api/scout/verify", json_body={"handle": "scout1"})
        resp = await scout.api_scout_verify(req)
        assert resp.status == 404
