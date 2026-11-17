"""
Model resolver tests: fuzzy matching safety and typo-tolerant search for the
model-resolution step of the NLP router. Keyword-intent classification
tests were removed along with the keyword classifier — see
app/router/command_filters.py for why.
"""

import pytest

from app.router.model_resolver import (
    match_recent_models,
    match_notion_results,
    fuzzy_score,
    FUZZY_MIN_QUERY_LENGTH,
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
#                     TYPO-TOLERANT MODEL SEARCH
# ============================================================================

_MODELS = [
    {"id": str(i), "name": n, "aliases": a} for i, (n, a) in enumerate([
        ("КЛЕЩ", []), ("ТангоКлещ", []), ("КАПРИ", ["kapri"]), ("БЕРЛИН", ["berlín", "berlin"]),
        ("ВЕНА", []), ("ВЕСНА", []), ("МОНА ЛИЗА", ["мона", "лиза"]), ("Танго 8", []), ("Танго 18", []),
        ("ТВИКСИ", []), ("ТЕЙСТИ", []),
    ])
]


async def _resolve(query, recent=None):
    from unittest.mock import AsyncMock, patch
    from app.router.model_resolver import resolve_model

    class _Recent:
        def get(self, user_id):
            return recent or []

    with patch("app.handlers.models.list_models", AsyncMock(return_value=_MODELS)):
        return await resolve_model(query, 1, "db", None, _Recent())


class TestTypoTolerantSearch:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query,name", [
        ("клещ", "КЛЕЩ"), ("kapri", "КАПРИ"), ("Berlin", "БЕРЛИН"), ("berlín", "БЕРЛИН"),
        ("вена", "ВЕНА"), ("весна", "ВЕСНА"), ("мона", "МОНА ЛИЗА"), ("танго 8", "Танго 8"), ("танго8", "Танго 8"),
    ])
    async def test_exact_title_or_alias_is_found(self, query, name):
        res = await _resolve(query)
        assert res["status"] == "found" and res["model"]["name"] == name

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query,name", [
        ("клеш", "КЛЕЩ"),      # wrong letter
        ("клещь", "КЛЕЩ"),     # extra letter
        ("твиски", "ТВИКСИ"),  # swapped letters
        ("тести", "ТЕЙСТИ"),   # missing letter
        ("capri", "КАПРИ"),    # typo in an alias
    ])
    async def test_one_typo_asks_for_confirmation(self, query, name):
        res = await _resolve(query)
        assert res["status"] == "confirm" and res["model"]["name"] == name

    @pytest.mark.asyncio
    async def test_typo_does_not_jump_to_a_recent_model(self):
        # "вена" is spelled exactly -> ВЕНА, even though ВЕСНА (1 letter away) was opened recently
        res = await _resolve("вена", recent=[("5", "ВЕСНА")])
        assert res["model"]["name"] == "ВЕНА"

    @pytest.mark.asyncio
    async def test_far_off_query_offers_nearest_or_nothing(self):
        assert (await _resolve("xyzw"))["status"] == "not_found"
        res = await _resolve("твиксик")
        found = [res["model"]["name"]] if res["model"] else [m["name"] for m in res["models"]]
        assert "ТВИКСИ" in found

    @pytest.mark.asyncio
    async def test_recent_substring_does_not_beat_exact_title(self):
        # ТангоКлещ was opened recently, but "клещ" is exactly КЛЕЩ
        res = await _resolve("клещ", recent=[("1", "ТангоКлещ")])
        assert res["status"] == "found" and res["model"]["name"] == "КЛЕЩ"

    @pytest.mark.asyncio
    async def test_short_piece_of_a_name_is_confirmed(self):
        res = await _resolve("тви")
        assert res["status"] == "confirm" and res["model"]["name"] == "ТВИКСИ"

    def test_normalization_keeps_short_i(self):
        from app.router.model_resolver import normalize_model_name
        assert normalize_model_name("МАЙЯ") != normalize_model_name("МАИЯ")
        assert normalize_model_name("Berlín") == "berlin"
        assert normalize_model_name("Ёлка") == "елка"

    @pytest.mark.asyncio
    async def test_same_alias_on_two_models_asks(self):
        from unittest.mock import AsyncMock, patch
        from app.router.model_resolver import resolve_model

        models = [{"id": "1", "name": "КАПРИ", "aliases": ["kapri"]}, {"id": "2", "name": "КАПРИ 2", "aliases": ["kapri"]}]
        with patch("app.handlers.models.list_models", AsyncMock(return_value=models)):
            res = await resolve_model("kapri", 1, "db", None, type("R", (), {"get": lambda self, u: []})())
        assert res["status"] == "multiple" and len(res["models"]) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
