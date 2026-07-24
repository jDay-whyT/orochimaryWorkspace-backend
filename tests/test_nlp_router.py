"""
NLP router pipeline tests.

Fuzzy matching safety and state management (TTL, backends) for the
model-resolution step of the NLP router. Keyword-intent classification
tests were removed along with the keyword classifier — see
app/router/command_filters.py for why.
"""

import pytest
import time

from app.router.model_resolver import (
    match_recent_models,
    match_notion_results,
    fuzzy_score,
    FUZZY_MIN_QUERY_LENGTH,
)
from app.state.memory import MemoryState
from app.state.redis_state import RedisMemoryState


class FakeAsyncRedis:
    """Tiny async Redis stub for state backend tests."""

    def __init__(self):
        self._storage: dict[str, tuple[str, float | None]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._storage.get(key)
        if not entry:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at <= time.time():
            self._storage.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        expires_at = None if ex is None else time.time() + ex
        self._storage[key] = (value, expires_at)
        return True

    async def delete(self, key: str) -> int:
        return 1 if self._storage.pop(key, None) is not None else 0


@pytest.fixture(params=["memory", "redis"])
def state_backend(request):
    if request.param == "memory":
        return MemoryState(ttl_seconds=60)
    return RedisMemoryState(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=60,
        redis_client=FakeAsyncRedis(),
    )


# ============================================================================
#                  FUZZY MATCHING SAFETY TESTS
# ============================================================================

class TestFuzzyMatcherSafety:
    """Tests that fuzzy matching is properly gated."""

    def test_short_query_no_fuzzy_in_recent(self):
        """Queries shorter than FUZZY_MIN_QUERY_LENGTH should not fuzzy match."""
        recent = [("id1", "мелиса"), ("id2", "мелисса")]
        # "мел" is 3 chars, below FUZZY_MIN_QUERY_LENGTH=4
        matches = match_recent_models("мел", recent)
        # Should only get substring matches, not fuzzy
        for m in matches:
            assert m["match_type"] in ("exact", "substring"), \
                f"Short query got fuzzy match: {m}"

    def test_exact_match_has_correct_type(self):
        """Exact matches should have match_type='exact'."""
        recent = [("id1", "мелиса")]
        matches = match_recent_models("мелиса", recent)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "exact"
        assert matches[0]["score"] == 1.0

    def test_substring_match_has_correct_type(self):
        """Substring matches should have match_type='substring'."""
        recent = [("id1", "мелиса")]
        matches = match_recent_models("мели", recent)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "substring"

    def test_fuzzy_allowed_for_long_query(self):
        """Fuzzy matching allowed when query >= FUZZY_MIN_QUERY_LENGTH."""
        assert FUZZY_MIN_QUERY_LENGTH == 4
        # "мелис" (5 chars) should be able to fuzzy match "мелиса"
        recent = [("id1", "мелиса")]
        matches = match_recent_models("мелис", recent)
        # Could be substring or fuzzy, but fuzzy is allowed
        assert len(matches) >= 1

    def test_notion_fuzzy_gated_by_length(self):
        """Notion results fuzzy matching gated by FUZZY_MIN_QUERY_LENGTH."""
        models = [{"id": "1", "name": "мелиса", "aliases": []}]
        # "мел" (3 chars) — should NOT get fuzzy matches
        scored = match_notion_results("мел", models)
        fuzzy_matches = [m for m in scored if m.get("match_type") == "fuzzy"]
        assert len(fuzzy_matches) == 0

    def test_notion_exact_not_gated(self):
        """Exact matches in Notion results work regardless of query length."""
        models = [{"id": "1", "name": "ал", "aliases": []}]
        scored = match_notion_results("ал", models)
        assert len(scored) == 1
        assert scored[0]["match_type"] == "exact"


# ============================================================================
#                     STATE MANAGEMENT TESTS
# ============================================================================

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
            redis_client=FakeAsyncRedis(),
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
