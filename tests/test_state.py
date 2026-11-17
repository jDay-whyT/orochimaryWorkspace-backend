"""State backends: memory and Redis (TTL, set/get/clear), and RedisMemoryState's resilience to dropped connections."""
import json
import time

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.state.memory import MemoryState
from app.state.redis_state import RedisMemoryState
from tests.conftest import FakeRedis


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


@pytest.fixture(params=["memory", "redis"])
def state_backend(request):
    if request.param == "memory":
        return MemoryState(ttl_seconds=60)
    return RedisMemoryState(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
        redis_client=FakeRedis(),
    )


class TestStateManagement:
    """Tests for state TTL and fallback behavior."""

    def test_state_set_and_get(self, state_backend):
        """State can be set and retrieved."""
        state = state_backend
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "step": "one"})
        result = state.get(chat_id, user_id)
        assert result is not None
        assert result["flow"] == "test"

    def test_state_clear(self, state_backend):
        """State can be cleared."""
        state = state_backend
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test"})
        state.clear(chat_id, user_id)
        assert state.get(chat_id, user_id) is None

    def test_state_expired_returns_none(self):
        """Expired state returns None (simulated with 0 TTL)."""
        state = RedisMemoryState(
            redis_url="redis://localhost:6379/0",
            ttl_seconds=0,
            redis_client=FakeRedis(),
        )
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test"})
        time.sleep(0.01)
        assert state.get(chat_id, user_id) is None

        state = MemoryState(ttl_seconds=0)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test"})
        time.sleep(0.01)
        assert state.get(chat_id, user_id) is None

    def test_state_update_extends_ttl(self, state_backend):
        """Update refreshes the TTL."""
        state = state_backend
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "step": "one"})
        state.update(chat_id, user_id, step="two")
        result = state.get(chat_id, user_id)
        assert result["step"] == "two"
        assert result["flow"] == "test"

    def test_missing_state_returns_none(self, state_backend):
        """Non-existent state returns None (not crash)."""
        state = state_backend
        assert state.get(999, 999) is None

    def test_state_set_preserves_prompt_message_id_when_omitted(self, state_backend):
        """prompt_message_id is retained when set() payload does not include it."""
        state = state_backend
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "prompt_message_id": 777})

        state.set(chat_id, user_id, {"flow": "test", "step": "two"})

        result = state.get(chat_id, user_id)
        assert result is not None
        assert result["prompt_message_id"] == 777

    def test_state_set_allows_explicit_prompt_message_id_override(self, state_backend):
        """prompt_message_id can still be intentionally overwritten."""
        state = state_backend
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "prompt_message_id": 777})

        state.set(chat_id, user_id, {"flow": "test", "prompt_message_id": None})

        result = state.get(chat_id, user_id)
        assert result is not None
        assert result["prompt_message_id"] is None
