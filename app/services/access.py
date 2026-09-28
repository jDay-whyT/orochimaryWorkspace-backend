"""Managers approved by the owner in the bot, on top of the env-configured ones.

An unknown user presses /start in DM -> the owner gets a request with one button
per Accounting `assist` value -> approving stores the user in Redis. Approved
users are merged into config.allowed_editors / manager_targets (DM reminders
for their `assist`) / digest_user_ids. Env values (ALLOWED_EDITORS etc.) stay
the base and are never removed from here. Without Redis nothing is added.

Several Cloud Run instances may run at once, so every instance re-reads the
Redis hash at most every REFRESH_SECONDS (and right away after its own change).
"""

import json
import logging
import time
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import Config

LOGGER = logging.getLogger(__name__)

MANAGERS_KEY = "access:managers"          # hash user_id -> json {assist, username, name, approved_at}
REQUEST_KEY = "access:request:{user_id}"  # json of a pending/rejected request
REQUEST_TTL_SECONDS = 7 * 24 * 60 * 60    # no repeat requests to the owner within a week
REFRESH_SECONDS = 30
NO_ASSIST = "-"                           # approved for access only, no reminders


@dataclass
class _Base:
    ref: weakref.ref
    editors: set[int]
    targets: dict[str, tuple[int, int | None]]
    digest: set[int]
    last_refresh: float = float("-inf")


# keyed by id(config): Config is frozen, so the env snapshot can't live on it
_bases: dict[int, _Base] = {}


def _base(config: Config) -> _Base:
    """Env-configured values, captured once per config object before any merge."""
    base = _bases.get(id(config))
    if base is None or base.ref() is not config:
        base = _Base(weakref.ref(config), set(config.allowed_editors), dict(config.manager_targets),
                     set(config.digest_user_ids))
        _bases[id(config)] = base
    return base


def is_env_editor(user_id: int, config: Config) -> bool:
    return user_id in _base(config).editors


def apply(config: Config, managers: dict[int, dict[str, Any]]) -> None:
    """Rebuild the config access sets as env base + approved managers (in place)."""
    base = _base(config)
    editors = set(base.editors) | set(managers)
    targets = dict(base.targets)
    digest = set(base.digest) | set(managers)
    for user_id, info in managers.items():
        assist = (info.get("assist") or "").strip().lower()
        if assist and assist != NO_ASSIST and assist not in base.targets:
            targets[assist] = (user_id, None)
    config.allowed_editors.clear()
    config.allowed_editors.update(editors)
    config.manager_targets.clear()
    config.manager_targets.update(targets)
    config.digest_user_ids.clear()
    config.digest_user_ids.update(digest)


async def load(redis: Any) -> dict[int, dict[str, Any]]:
    raw = await redis.hgetall(MANAGERS_KEY)
    managers: dict[int, dict[str, Any]] = {}
    for key, value in (raw or {}).items():
        try:
            managers[int(key)] = json.loads(value)
        except (TypeError, ValueError):
            LOGGER.warning("access: bad manager entry %r", key)
    return managers


async def refresh(config: Config, redis: Any, force: bool = False) -> None:
    """Merge approved managers into config; cheap to call on every update. Never raises."""
    if redis is None:
        return
    base = _base(config)
    now = time.monotonic()
    if not force and now - base.last_refresh < REFRESH_SECONDS:
        return
    base.last_refresh = now
    try:
        apply(config, await load(redis))
    except Exception:
        LOGGER.exception("access: refresh failed, keeping current access lists")


async def save_request(redis: Any, user_id: int, username: str | None, name: str) -> bool:
    """Store a request; False if one from this user is already pending or was rejected recently."""
    payload = json.dumps({"username": username or "", "name": name, "status": "pending"}, ensure_ascii=False)
    created = await redis.set(REQUEST_KEY.format(user_id=user_id), payload, ex=REQUEST_TTL_SECONDS, nx=True)
    return bool(created)


async def get_request(redis: Any, user_id: int) -> dict[str, Any] | None:
    raw = await redis.get(REQUEST_KEY.format(user_id=user_id))
    return json.loads(raw) if raw else None


async def approve(config: Config, redis: Any, user_id: int, assist: str) -> dict[str, Any]:
    request = await get_request(redis, user_id) or {}
    info = {
        "assist": assist,
        "username": request.get("username", ""),
        "name": request.get("name", ""),
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    await redis.hset(MANAGERS_KEY, str(user_id), json.dumps(info, ensure_ascii=False))
    await redis.delete(REQUEST_KEY.format(user_id=user_id))
    await refresh(config, redis, force=True)
    return info


async def reject(redis: Any, user_id: int) -> dict[str, Any]:
    """Keep the request as rejected until it expires, so the owner is not asked again."""
    request = await get_request(redis, user_id) or {}
    request["status"] = "rejected"
    await redis.set(REQUEST_KEY.format(user_id=user_id), json.dumps(request, ensure_ascii=False),
                    ex=REQUEST_TTL_SECONDS)
    return request


async def revoke(config: Config, redis: Any, user_id: int) -> dict[str, Any] | None:
    managers = await load(redis)
    info = managers.get(user_id)
    await redis.hdel(MANAGERS_KEY, str(user_id))
    await refresh(config, redis, force=True)
    return info


def label(user_id: int, info: dict[str, Any]) -> str:
    """@username, else name, else ID."""
    if info.get("username"):
        return f"@{info['username']}"
    return info.get("name") or str(user_id)
