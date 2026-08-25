"""Tests for RedisMemoryState's resilience to dropped Redis connections."""
import json

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.state.redis_state import RedisMemoryState


class FakeRedisClient:
    """Fails its first N calls with redis-py's own ConnectionError, then succeeds.

    Uses redis.exceptions.ConnectionError specifically — it does NOT subclass
    the builtin ConnectionError, and a prior version of this fake used the
    builtin, which masked a real bug where _run_resilient only caught the
    builtin type.
    """

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0
        self.store: dict[str, str] = {}

    def _maybe_fail(self):
        if self.calls < self.fail_times:
            self.calls += 1
            raise RedisConnectionError("Error 104 while writing to socket. Connection reset by peer.")
        self.calls += 1

    async def get(self, key):
        self._maybe_fail()
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self._maybe_fail()
        self.store[key] = value

    async def delete(self, key):
        self._maybe_fail()
        self.store.pop(key, None)


@pytest.fixture
def state_factory():
    created = []

    def make(fail_times: int = 0) -> RedisMemoryState:
        s = RedisMemoryState(redis_url="redis://fake", redis_client=FakeRedisClient(fail_times))
        created.append(s)
        return s

    yield make


class TestResilientGet:
    def test_succeeds_immediately_when_no_error(self, state_factory):
        state = state_factory(fail_times=0)
        state.set(1, 2, {"flow": "x"})
        assert state.get(1, 2) == {"flow": "x"}

    def test_recovers_after_one_dropped_connection(self, state_factory):
        state = state_factory(fail_times=0)
        state.redis_client.store["state:1:2"] = json.dumps({"flow": "x"})
        state.redis_client.fail_times = 1
        state.redis_client.calls = 0
        assert state.get(1, 2) == {"flow": "x"}

    def test_gives_up_after_two_dropped_connections_returns_none(self, state_factory):
        state = state_factory(fail_times=0)
        state.redis_client.store["state:1:2"] = json.dumps({"flow": "x"})
        state.redis_client.fail_times = 2
        state.redis_client.calls = 0
        assert state.get(1, 2) is None

    def test_set_swallows_persistent_connection_failure(self, state_factory):
        state = state_factory(fail_times=99)
        state.set(1, 2, {"flow": "x"})  # must not raise
        assert state.get(1, 2) is None
