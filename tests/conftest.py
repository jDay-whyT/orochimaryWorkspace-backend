"""Shared test fixtures: one FakeRedis, the card config mock, per-test cache/lock resets."""
import time
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest


class FakeRedis:
    """Async Redis stub covering what the app and tests use: strings (nx, ex), hashes, sets, lists."""

    def __init__(self, **kv):
        self.kv: dict[str, str] = dict(kv)
        self.expires: dict[str, float] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}

    def _alive(self, key: str) -> bool:
        if key in self.kv and self.expires.get(key, float("inf")) <= time.time():
            self.kv.pop(key, None)
            self.expires.pop(key, None)
        return key in self.kv

    async def get(self, key):
        return self.kv[key] if self._alive(key) else None

    async def set(self, key, value, ex=None, nx=False):
        if nx and self._alive(key):
            return None
        self.kv[key] = value
        if ex is None:
            self.expires.pop(key, None)
        else:
            self.expires[key] = time.time() + ex
        return True

    async def delete(self, key):
        self.expires.pop(key, None)
        return 1 if self.kv.pop(key, None) is not None else 0

    async def hget(self, key, field_):
        return self.hashes.get(key, {}).get(field_)

    async def hset(self, key, field_, value):
        self.hashes.setdefault(key, {})[field_] = value

    async def hdel(self, key, field_):
        self.hashes.get(key, {}).pop(field_, None)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def sismember(self, key, value):
        return value in self.sets.get(key, set())

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    async def expire(self, key, seconds):
        pass


@pytest.fixture
def card_config():
    """Config for model-card tests; tests override single attributes where they need to."""
    cfg = MagicMock()
    cfg.timezone = ZoneInfo("Europe/Brussels")
    cfg.files_per_month = 200
    cfg.db_orders = "db_orders"
    cfg.db_planner = "db_planner"
    cfg.db_accounting = "db_accounting"
    return cfg


@pytest.fixture(autouse=True)
def _clear_card_cache():
    from app.services.model_card import clear_card_cache
    clear_card_cache()
    yield
    clear_card_cache()


@pytest.fixture(autouse=True)
def _clear_in_memory_locks():
    from app.utils import locks as locks_module
    locks_module._in_flight_locks.clear()
    yield
    locks_module._in_flight_locks.clear()
