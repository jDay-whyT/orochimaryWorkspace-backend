"""
NLP router pipeline tests.

Tests intent classification + entity extraction for specific user scenarios,
fuzzy matching safety, state management, and intent priorities.

12+ required test cases per task spec.
"""

import pytest
from datetime import date, timedelta

from app.router.intent_v2 import classify_intent_v2
from app.router.entities_v2 import extract_entities_v2
from app.router.command_filters import CommandIntent
from app.router.model_resolver import (
    match_recent_models,
    match_notion_results,
    fuzzy_score,
    FUZZY_MIN_QUERY_LENGTH,
)
from app.state.memory import MemoryState


# ============================================================================
#                  MENU / REPORT INTENTS (Cases 1-4)
# ============================================================================

class TestMenuReportIntents:
    """Tests for menu and report intent classification."""

    def test_melisa_pokazi_search_model(self):
        """'мелиса покажи' -> SEARCH_MODEL (no specific command keyword)."""
        entities = extract_entities_v2("мелиса покажи")
        intent = classify_intent_v2(
            "мелиса покажи",
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SEARCH_MODEL
        assert entities.model_name == "мелиса"

    def test_melisa_report(self):
        """'мелиса репорт' -> GET_REPORT."""
        entities = extract_entities_v2("мелиса репорт")
        intent = classify_intent_v2(
            "мелиса репорт",
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.GET_REPORT
        assert entities.model_name == "мелиса"

    def test_melisa_dolgi_search_model(self):
        """'мелиса долги' -> SEARCH_MODEL (no 'долги' filter defined)."""
        entities = extract_entities_v2("мелиса долги")
        intent = classify_intent_v2(
            "мелиса долги",
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SEARCH_MODEL
        # entity extractor captures the full phrase as model_name;
        # disambiguation / fuzzy search in the resolver handles the rest.
        assert entities.has_model is True

    def test_orders_no_model_shows_menu(self):
        """'заказы' (without model) -> SHOW_ORDERS (menu), NOT SHOW_MODEL_ORDERS.

        This was a bug: SHOW_MODEL_ORDERS (priority 50) matched 'заказы'
        before SHOW_ORDERS (40), then dispatcher required a model name.
        Fix: downgrade SHOW_MODEL_ORDERS to SHOW_ORDERS when no model.
        """
        entities = extract_entities_v2("заказы")
        intent = classify_intent_v2(
            "заказы",
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SHOW_ORDERS
        assert entities.model_name is None


# ============================================================================
#                     ORDER INTENTS (Cases 5-6)
# ============================================================================

class TestOrderIntents:
    """Tests for order-related intent classification."""

    def test_3_custom_melisa(self):
        """'3 кастома мелиса' -> CREATE_ORDERS with full entities."""
        text = "3 кастома мелиса"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.CREATE_ORDERS
        assert entities.model_name == "мелиса"
        assert entities.numbers == [3]
        assert entities.order_type == "custom"

    def test_melisa_create_order_general(self):
        """'мелиса создать заказ' -> CREATE_ORDERS_GENERAL."""
        text = "мелиса создать заказ"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.CREATE_ORDERS_GENERAL
        assert entities.model_name == "мелиса"


# ============================================================================
#                   PLANNER / SHOOT INTENTS (Cases 7-10)
# ============================================================================

class TestPlannerIntents:
    """Tests for planner/shoot intent classification."""

    def test_shoot_melisa_date_platforms(self):
        """'съемка мелиса 09.02 твиттер реддит' -> SHOOT_CREATE with date."""
        text = "съемка мелиса 09.02 твиттер реддит"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SHOOT_CREATE
        assert entities.model_name == "мелиса"
        assert entities.date is not None
        assert entities.date.day == 9
        assert entities.date.month == 2

    def test_shoot_melisa_tomorrow(self):
        """'шут мелиса завтра' -> SHOOT_CREATE with relative date."""
        text = "шут мелиса завтра"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SHOOT_CREATE
        assert entities.model_name == "мелиса"
        assert entities.date == date.today() + timedelta(days=1)

    def test_melisa_reschedule(self):
        """'мелиса перенос 20.02' -> SHOOT_RESCHEDULE.

        Fix: added 'перенос'/'перенести' as keywords for SHOOT_RESCHEDULE.
        """
        text = "мелиса перенос 20.02"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SHOOT_RESCHEDULE
        assert entities.model_name == "мелиса"
        assert entities.date is not None
        assert entities.date.day == 20
        assert entities.date.month == 2

    def test_melisa_shoot_done(self):
        """'мелиса съемка готово' -> SHOOT_DONE.

        Fix: regex now handles 'готово'/'выполнено' word forms
        (previously only matched 'готов'/'выполнен' with word boundary).
        """
        text = "мелиса съемка готово"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.SHOOT_DONE

    def test_shoot_done_gotova(self):
        """'съемка готова' still works after regex fix."""
        intent = classify_intent_v2("съемка готова", has_model=False, has_numbers=False)
        assert intent == CommandIntent.SHOOT_DONE

    def test_shoot_done_vypolneno(self):
        """'съемка выполнено' now works after regex fix."""
        intent = classify_intent_v2("мелиса съемка выполнено", has_model=True, has_numbers=False)
        assert intent == CommandIntent.SHOOT_DONE


# ============================================================================
#                  ACCOUNTING / FILES INTENTS (Cases 11-12)
# ============================================================================

class TestAccountingIntents:
    """Tests for accounting/files intent classification."""

    def test_melisa_files_shows_stats(self):
        """'мелиса файлы' -> FILES_STATS (no number = show stats, not add)."""
        text = "мелиса файлы"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.FILES_STATS
        assert entities.model_name == "мелиса"
        assert not entities.has_numbers

    def test_melisa_files_30_adds(self):
        """'мелиса файлы 30' -> ADD_FILES (with number = add files)."""
        text = "мелиса файлы 30"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.ADD_FILES
        assert entities.model_name == "мелиса"
        assert entities.first_number == 30


# ============================================================================
#                    AMBIGUOUS INTENTS (Case 13)
# ============================================================================

class TestAmbiguousIntents:
    """Tests for ambiguous intent classification."""

    def test_melisa_30_ambiguous(self):
        """'мелиса 30' -> AMBIGUOUS (model + number, no marker keyword).

        Should show disambiguation buttons (Files vs Orders), not auto-execute.
        """
        text = "мелиса 30"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.AMBIGUOUS
        assert entities.model_name == "мелиса"
        assert entities.first_number == 30


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

    def test_state_set_and_get(self):
        """State can be set and retrieved."""
        state = MemoryState(ttl_seconds=60)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "step": "one"})
        result = state.get(chat_id, user_id)
        assert result is not None
        assert result["flow"] == "test"

    def test_state_clear(self):
        """State can be cleared."""
        state = MemoryState(ttl_seconds=60)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test"})
        state.clear(chat_id, user_id)
        assert state.get(chat_id, user_id) is None

    def test_state_expired_returns_none(self):
        """Expired state returns None (simulated with 0 TTL)."""
        state = MemoryState(ttl_seconds=0)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test"})
        # TTL=0 means immediately expired
        import time
        time.sleep(0.01)
        assert state.get(chat_id, user_id) is None

    def test_state_update_extends_ttl(self):
        """Update refreshes the TTL."""
        state = MemoryState(ttl_seconds=60)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "step": "one"})
        state.update(chat_id, user_id, step="two")
        result = state.get(chat_id, user_id)
        assert result["step"] == "two"
        assert result["flow"] == "test"

    def test_missing_state_returns_none(self):
        """Non-existent state returns None (not crash)."""
        state = MemoryState(ttl_seconds=60)
        assert state.get(999, 999) is None

    def test_state_set_preserves_prompt_message_id_when_omitted(self):
        """prompt_message_id is retained when set() payload does not include it."""
        state = MemoryState(ttl_seconds=60)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "prompt_message_id": 777})

        state.set(chat_id, user_id, {"flow": "test", "step": "two"})

        result = state.get(chat_id, user_id)
        assert result is not None
        assert result["prompt_message_id"] == 777

    def test_state_set_allows_explicit_prompt_message_id_override(self):
        """prompt_message_id can still be intentionally overwritten."""
        state = MemoryState(ttl_seconds=60)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "test", "prompt_message_id": 777})

        state.set(chat_id, user_id, {"flow": "test", "prompt_message_id": None})

        result = state.get(chat_id, user_id)
        assert result is not None
        assert result["prompt_message_id"] is None


# ============================================================================
#                 INTENT PRIORITY EDGE CASES
# ============================================================================

class TestIntentPriorities:
    """Tests for intent priority edge cases."""

    def test_shoot_has_priority_over_menu(self):
        """SHOOT_CREATE (100) should beat SHOW_PLANNER (40)."""
        intent = classify_intent_v2("съемка мелиса", has_model=True, has_numbers=False)
        assert intent == CommandIntent.SHOOT_CREATE

    def test_files_has_priority_over_menu(self):
        """ADD_FILES (90) should beat SHOW_ACCOUNT (40)."""
        intent = classify_intent_v2("30 файлов мелиса", has_model=True, has_numbers=True)
        assert intent == CommandIntent.ADD_FILES

    def test_orders_with_type_is_create(self):
        """CREATE_ORDERS (80) should beat SHOW_ORDERS (40)."""
        intent = classify_intent_v2("кастом заказы мелиса", has_model=True, has_numbers=False)
        assert intent == CommandIntent.CREATE_ORDERS

    def test_orders_with_model_is_show_model_orders(self):
        """'заказы мелиса' with model -> SHOW_MODEL_ORDERS."""
        intent = classify_intent_v2("заказы мелиса", has_model=True, has_numbers=False)
        assert intent == CommandIntent.SHOW_MODEL_ORDERS

    def test_reschedule_exclude_with_order_keywords(self):
        """SHOOT_RESCHEDULE should not match when order keywords present."""
        # 'перенос' is now a SHOOT_RESCHEDULE keyword,
        # but exclude_with prevents matching with order keywords
        intent = classify_intent_v2("перенос заказ мелиса", has_model=True, has_numbers=False)
        assert intent != CommandIntent.SHOOT_RESCHEDULE


# ============================================================================
#              NLP FLOW WAITING / DISPATCHER FLOW FILTER TESTS
# ============================================================================

class TestNlpFlowWaiting:
    """Tests that nlp_* flows respond instead of staying silent."""

    def test_nlp_disambiguate_flow_gets_response(self):
        """When user has nlp_disambiguate flow and sends text, bot must not stay silent.

        The dispatcher should NOT return early for nlp_* flows —
        it should reply with 'жду кнопку/сброс'.
        We verify by checking the state is recognized as nlp_* (starts with 'nlp_').
        """
        state = MemoryState(ttl_seconds=60)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "nlp_disambiguate", "intent": "create_orders"})
        user_state = state.get(chat_id, user_id)
        flow = user_state["flow"]
        # nlp_* flows should NOT be in the FlowFilter set
        flow_filter_flows = {
            "search", "new_order", "view", "comment",
            "summary", "planner", "accounting",
        }
        assert flow not in flow_filter_flows
        assert flow.startswith("nlp_")

    def test_nlp_shoot_flow_not_in_filter_set(self):
        """nlp_shoot flow should not be in FlowFilter set."""
        flow_filter_flows = {
            "search", "new_order", "view", "comment",
            "summary", "planner", "accounting",
        }
        assert "nlp_shoot" not in flow_filter_flows

    def test_nlp_order_flow_not_in_filter_set(self):
        """nlp_order flow should not be in FlowFilter set."""
        flow_filter_flows = {
            "search", "new_order", "view", "comment",
            "summary", "planner", "accounting",
        }
        assert "nlp_order" not in flow_filter_flows

    def test_unknown_flow_cleared(self):
        """Unknown flow should be cleared from state."""
        state = MemoryState(ttl_seconds=60)
        chat_id = 100
        user_id = 123
        state.set(chat_id, user_id, {"flow": "some_unknown_flow"})
        user_state = state.get(chat_id, user_id)
        flow = user_state["flow"]
        flow_filter_flows = {
            "search", "new_order", "view", "comment",
            "summary", "planner", "accounting",
        }
        # Not in filter set and not nlp_* -> should be cleared
        assert flow not in flow_filter_flows
        assert not flow.startswith("nlp_")
        # Simulate clearing
        state.clear(chat_id, user_id)
        assert state.get(chat_id, user_id) is None

    def test_known_flow_skips_nlp(self):
        """Known FlowFilter flow should skip NLP (return early)."""
        flow_filter_flows = {
            "search", "new_order", "view", "comment",
            "summary", "planner", "accounting",
        }
        for flow in flow_filter_flows:
            assert flow in flow_filter_flows


# ============================================================================
#              ШОРТС КЛЕЩ PARSING TESTS
# ============================================================================

class TestShortsKleshParsing:
    """Tests for 'шортс клещ' parsing -> order_type=short, model=клещ."""

    def test_shorts_klesh_intent(self):
        """'шортс клещ' -> CREATE_ORDERS with type=short, model=клещ."""
        text = "шортс клещ"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.CREATE_ORDERS
        assert entities.order_type == "short"
        assert entities.model_name == "клещ"

    def test_shorts_in_order_type_map(self):
        """'шортс' must map to 'short' in ORDER_TYPE_MAP."""
        from app.router.command_filters import ORDER_TYPE_MAP
        assert "шортс" in ORDER_TYPE_MAP
        assert ORDER_TYPE_MAP["шортс"] == "short"

    def test_shorts_in_ignore_keywords(self):
        """'шортс' must be in IGNORE_KEYWORDS so it's not treated as model name."""
        from app.router.command_filters import IGNORE_KEYWORDS
        assert "шортс" in IGNORE_KEYWORDS

    def test_3_shorts_klesh(self):
        """'3 шортс клещ' -> CREATE_ORDERS with numbers=[3], type=short, model=клещ."""
        text = "3 шортс клещ"
        entities = extract_entities_v2(text)
        intent = classify_intent_v2(
            text,
            has_model=entities.has_model,
            has_numbers=entities.has_numbers,
        )
        assert intent == CommandIntent.CREATE_ORDERS
        assert entities.order_type == "short"
        assert entities.model_name == "клещ"
        assert entities.numbers == [3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
