"""Scout Mini App API route handlers."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from aiohttp import web

from app.api.auth import validate_init_data
from app.services import access

LOGGER = logging.getLogger(__name__)

# WARNING: dev bypass skips HMAC validation when ENV=development and no initData
# is provided. NEVER set ENV=development in production (Cloud Run).
_DEV_BYPASS = os.getenv("ENV", "").lower() == "development"
_DEV_USER: dict = {"id": -1, "username": "dev", "first_name": "Developer"}


def _extract_user(request: web.Request) -> dict | None:
    """Validate Authorization: tma <initData> header. Returns user dict or None."""
    header = request.headers.get("Authorization", "")
    if _DEV_BYPASS and not header.startswith("tma "):
        LOGGER.warning("DEV BYPASS: skipping initData validation (ENV=development)")
        return _DEV_USER
    if not header.startswith("tma "):
        return None
    config = request.app["config"]
    return validate_init_data(header[4:], config.telegram_bot_token)


def _is_full_access(user_id: int, config, username: str | None = None) -> bool:
    if _DEV_BYPASS and user_id == -1:
        return True
    if access.manager_assist(user_id, config):
        return False  # managers see only their own models
    if user_id == config.owner_telegram_id or user_id in config.allowed_editors:
        return True
    if user_id in config.mini_app_viewer_ids:
        return True
    if username:
        handle = f"@{username.lower().lstrip('@')}"
        if handle in config.mini_app_viewer_handles:
            return True
    return False


_MANAGER_CACHE_SECONDS = 60
_manager_cache: dict = {}  # {"at", "assist_of": model key -> assist, "models"}; shared by all managers


async def _manager_models(request: web.Request, assist: str) -> list:
    """Models whose working Accounting record has `assist` = this manager."""
    from app.services.accounting import working_records

    config = request.app["config"]
    notion = request.app["notion"]
    cache = _manager_cache
    now = time.monotonic()
    if now - cache.get("at", float("-inf")) > _MANAGER_CACHE_SECONDS:
        records = await notion.query_all_accounting(config.db_accounting)
        working, _ = working_records(records, datetime.now(config.timezone).strftime("%Y-%m"))
        cache["assist_of"] = {key: (r.assist or "").strip().lower() for key, r in working.items()}
        cache["models"] = await notion.query_models(config.db_models, "", limit=200)
        cache["at"] = now
    assist = assist.strip().lower()
    return [m for m in cache["models"] if cache["assist_of"].get(m.page_id.replace("-", "")) == assist]


async def _resolve_scout_handle(
    request: web.Request,
    user_id: int,
    username: str | None,
) -> tuple[str | None, list | None]:
    """
    Return (handle, models) for scout.
    Resolution order: Redis cache → Notion query (if username present) → (None, None).
    models is None when resolved from cache (caller must query Notion for models).
    """
    redis = request.app.get("redis")
    cache_key = f"scout:{user_id}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            handle = cached if isinstance(cached, str) else cached.decode()
            return handle, None  # cache hit — caller queries models separately

    if not username:
        return None, None

    handle = f"@{username.lower().lstrip('@')}"
    notion = request.app["notion"]
    config = request.app["config"]

    models = await notion.query_models_by_scout(config.db_models, handle)
    if not models:
        return None, None

    if redis:
        await redis.set(cache_key, handle, ex=86400)

    return handle, models


async def api_scout_models(request: web.Request) -> web.Response:
    """POST /api/scout/models — list models accessible to the authenticated scout."""
    user = _extract_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    user_id = user.get("id")
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    config = request.app["config"]
    notion = request.app["notion"]
    await access.refresh(config, request.app.get("redis"))

    username = user.get("username")
    assist = access.manager_assist(user_id, config)
    if assist:
        models = await _manager_models(request, assist)
        return web.json_response({
            "scout": None,
            "models": [
                {"id": m.page_id, "name": m.title, "project": m.project, "status": m.status, "scout": m.scout}
                for m in models
            ],
        })
    if _is_full_access(user_id, config, username):
        models = await notion.query_models(config.db_models, "", limit=200)
        if len(models) >= 200:
            LOGGER.warning("query_models returned 200 results — list may be truncated")
        return web.json_response({
            "scout": None,
            "models": [
                {"id": m.page_id, "name": m.title, "project": m.project, "status": m.status, "scout": m.scout}
                for m in models
            ],
        })

    handle, models = await _resolve_scout_handle(request, user_id, username)

    if handle and models is None:
        models = await notion.query_models_by_scout(config.db_models, handle)
        if not models:
            # Cached handle whose models were all reassigned — drop the stale binding.
            redis = request.app.get("redis")
            if redis:
                await redis.delete(f"scout:{user_id}")

    if not handle or not models:
        # Access = being the scout of at least one model in Notion.
        return web.json_response({
            "status": "no_access",
            "reason": "no_models" if username else "no_username",
            "username": f"@{username}" if username else None,
        })

    return web.json_response({
        "scout": handle,
        "models": [
            {"id": m.page_id, "name": m.title, "project": m.project, "status": m.status, "scout": m.scout}
            for m in models
        ],
    })


async def api_scout_model_card(request: web.Request) -> web.Response:
    """GET /api/scout/model/{name} — full card JSON for one model."""
    user = _extract_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    user_id = user.get("id")
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    model_name = request.match_info["name"]
    config = request.app["config"]
    notion = request.app["notion"]
    await access.refresh(config, request.app.get("redis"))

    username = user.get("username")
    assist = access.manager_assist(user_id, config)
    if assist:
        allowed = {m.title.lower() for m in await _manager_models(request, assist)}
        if model_name.lower() not in allowed:
            return web.json_response({"error": "forbidden"}, status=403)
    elif not _is_full_access(user_id, config, username):
        handle, scout_models = await _resolve_scout_handle(request, user_id, username)
        if not handle:
            return web.json_response({"error": "unauthorized"}, status=401)

        if scout_models is None:
            scout_models = await notion.query_models_by_scout(config.db_models, handle)
        allowed = {m.title.lower() for m in scout_models}
        if model_name.lower() not in allowed:
            return web.json_response({"error": "forbidden"}, status=403)

    from app.services.scout_card import build_scout_report_card_json
    card = await build_scout_report_card_json(model_name, notion, config)
    if not card:
        return web.json_response({"error": "not found"}, status=404)

    return web.json_response(card)
