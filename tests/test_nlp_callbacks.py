"""
Tests for NLP callback validation, anti-stale token system, and custom date logic.

Scenarios:
1. Full order flow: model -> act:order -> ot:custom -> oq:2 -> od:today -> oc
2. Stale token: pressing oq with old k after new k → rejected
3. Flow/step mismatch: pressing oq when step is awaiting_type → rejected
4. Custom date: "05.02" when today=06.02 → same year, not next year
5. Custom date: "10.01" when today=06.02 → same year (within 90 days)
6. Token generation produces 4-char base36 strings
7. ORDER_TYPE_CB_MAP mapping correctness
8. Keyboard functions include token in callback_data
"""

import re
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock

from app.state.memory import MemoryState
from app.state.token import generate_token
from app.keyboards.inline import (
    ORDER_TYPE_CB_MAP,
    ORDER_TYPE_CB_REVERSE,
    ORDER_TYPE_DISPLAY,
    nlp_order_type_keyboard,
    nlp_order_qty_keyboard,
    nlp_order_confirm_keyboard,
    nlp_model_actions_keyboard,
    nlp_shoot_date_keyboard,
    nlp_close_order_date_keyboard,
    nlp_disambiguate_keyboard,
    nlp_stale_keyboard,
    nlp_files_qty_keyboard,
    nlp_report_keyboard,
    nlp_confirm_model_keyboard,
    nlp_model_selection_keyboard,
    nlp_not_found_keyboard,
)
from app.handlers.nlp_callbacks import (
    _validate_token,
    _validate_flow_step,
    _FLOW_STEP_RULES,
)


# ============================================================================
#                     TOKEN GENERATION TESTS
# ============================================================================

class TestTokenGeneration:
    """Tests for anti-stale token generation."""

    def test_token_length(self):
        """Token should be 4 characters by default."""
        token = generate_token()
        assert len(token) == 4

    def test_token_is_base36(self):
        """Token characters should be lowercase letters and digits."""
        for _ in range(50):
            token = generate_token()
            assert re.match(r'^[a-z0-9]{4}$', token), f"Invalid token: {token}"

    def test_tokens_are_unique(self):
        """Tokens should be different (with very high probability)."""
        tokens = {generate_token() for _ in range(100)}
        # With 36^4 ≈ 1.7M possibilities, 100 tokens should all be unique
        assert len(tokens) == 100

    def test_custom_length(self):
        """Token length can be customized."""
        token = generate_token(length=6)
        assert len(token) == 6
        assert re.match(r'^[a-z0-9]{6}$', token)


# ============================================================================
#                   ORDER_TYPE MAPPING TESTS
# ============================================================================

class TestOrderTypeMapping:
    """Tests for centralized order type callback<->internal mapping."""

    def test_ad_request_callback_no_space(self):
        """Callback data for 'ad request' must use 'ad_request' (no spaces)."""
        assert "ad_request" in ORDER_TYPE_CB_MAP
        assert ORDER_TYPE_CB_MAP["ad_request"] == "ad request"

    def test_reverse_mapping(self):
        """Internal 'ad request' maps back to callback 'ad_request'."""
        assert ORDER_TYPE_CB_REVERSE["ad request"] == "ad_request"

    def test_all_types_mapped(self):
        """All four order types are in the callback map."""
        expected = {"custom", "short", "call", "ad_request"}
        assert set(ORDER_TYPE_CB_MAP.keys()) == expected

    def test_display_names(self):
        """Display names are correct for callback values."""
        assert ORDER_TYPE_DISPLAY["custom"] == "Кастом"
        assert ORDER_TYPE_DISPLAY["short"] == "Шорт"
        assert ORDER_TYPE_DISPLAY["call"] == "Колл"
        assert ORDER_TYPE_DISPLAY["ad_request"] == "Ad Request"

    def test_order_type_keyboard_no_spaces_in_callback(self):
        """nlp_order_type_keyboard callback_data must not contain spaces."""
        kb = nlp_order_type_keyboard("test")
        for row in kb.inline_keyboard:
            for btn in row:
                assert " " not in btn.callback_data, \
                    f"Space in callback_data: {btn.callback_data}"


# ============================================================================
#                   TOKEN VALIDATION TESTS
# ============================================================================

class TestTokenValidation:
    """Tests for _validate_token logic."""

    def test_cancel_action_always_valid(self):
        """Cancel (x) action should always pass token validation."""
        assert _validate_token(None, ["nlp", "x", "c"], "x") is True
        assert _validate_token({}, ["nlp", "x", "c"], "x") is True

    def test_no_state_rejects(self):
        """No state should reject non-cancel actions."""
        assert _validate_token(None, ["nlp", "oq", "2", "abc1"], "oq") is False

    def test_legacy_state_without_token_allows(self):
        """State without 'k' key should pass (legacy compatibility)."""
        state = {"flow": "nlp_order", "step": "awaiting_count"}
        assert _validate_token(state, ["nlp", "oq", "2"], "oq") is True

    def test_matching_token_allows(self):
        """Matching token should pass."""
        state = {"flow": "nlp_order", "step": "awaiting_count", "k": "ab12"}
        assert _validate_token(state, ["nlp", "oq", "2", "ab12"], "oq") is True

    def test_mismatched_token_rejects(self):
        """Mismatched token should reject."""
        state = {"flow": "nlp_order", "step": "awaiting_count", "k": "ab12"}
        assert _validate_token(state, ["nlp", "oq", "2", "zzzz"], "oq") is False

    def test_stale_scenario(self):
        """Simulate stale: user pressed button from old keyboard after new one was sent."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # First keyboard sends with token "aaaa"
        memory.set(user_id, {"flow": "nlp_order", "step": "awaiting_count", "k": "aaaa"})

        # Second keyboard sends with new token "bbbb" (replaces state)
        memory.update(user_id, k="bbbb")

        state = memory.get(user_id)
        # User presses button from first keyboard (token "aaaa")
        old_parts = ["nlp", "oq", "2", "aaaa"]
        assert _validate_token(state, old_parts, "oq") is False, \
            "Old token should be rejected after new token was set"

        # User presses button from second keyboard (token "bbbb")
        new_parts = ["nlp", "oq", "2", "bbbb"]
        assert _validate_token(state, new_parts, "oq") is True


# ============================================================================
#                  FLOW/STEP VALIDATION TESTS
# ============================================================================

class TestFlowStepValidation:
    """Tests for _validate_flow_step logic."""

    def test_ot_requires_nlp_order_awaiting_type(self):
        """ot action requires flow=nlp_order, step=awaiting_type."""
        state = {"flow": "nlp_order", "step": "awaiting_type"}
        assert _validate_flow_step(state, "ot") is True

        # Wrong step
        state2 = {"flow": "nlp_order", "step": "awaiting_count"}
        assert _validate_flow_step(state2, "ot") is False

        # Wrong flow
        state3 = {"flow": "nlp_shoot", "step": "awaiting_type"}
        assert _validate_flow_step(state3, "ot") is False

    def test_oq_requires_nlp_order_awaiting_count(self):
        """oq action requires flow=nlp_order, step=awaiting_count."""
        state = {"flow": "nlp_order", "step": "awaiting_count"}
        assert _validate_flow_step(state, "oq") is True

        state2 = {"flow": "nlp_order", "step": "awaiting_type"}
        assert _validate_flow_step(state2, "oq") is False

    def test_od_oc_require_awaiting_date(self):
        """od and oc require flow=nlp_order, step=awaiting_date."""
        state = {"flow": "nlp_order", "step": "awaiting_date"}
        assert _validate_flow_step(state, "od") is True
        assert _validate_flow_step(state, "oc") is True

        state2 = {"flow": "nlp_order", "step": "awaiting_count"}
        assert _validate_flow_step(state2, "od") is False
        assert _validate_flow_step(state2, "oc") is False

    def test_sd_requires_nlp_shoot(self):
        """sd action requires flow=nlp_shoot with specific steps."""
        for step in ("awaiting_date", "awaiting_new_date", "awaiting_custom_date"):
            state = {"flow": "nlp_shoot", "step": step}
            assert _validate_flow_step(state, "sd") is True

        # Wrong flow
        state2 = {"flow": "nlp_order", "step": "awaiting_date"}
        assert _validate_flow_step(state2, "sd") is False

    def test_cd_requires_nlp_close(self):
        """cd action requires flow=nlp_close (any step)."""
        state = {"flow": "nlp_close"}
        assert _validate_flow_step(state, "cd") is True

        state2 = {"flow": "nlp_close", "step": "awaiting_custom_date"}
        assert _validate_flow_step(state2, "cd") is True

        state3 = {"flow": "nlp_order"}
        assert _validate_flow_step(state3, "cd") is False

    def test_act_requires_nlp_actions_with_model_id(self):
        """act action requires flow=nlp_actions and model_id present."""
        state = {"flow": "nlp_actions", "model_id": "page-123"}
        assert _validate_flow_step(state, "act") is True

        # Missing model_id
        state2 = {"flow": "nlp_actions"}
        assert _validate_flow_step(state2, "act") is False

        # Wrong flow
        state3 = {"flow": "nlp_order", "model_id": "page-123"}
        assert _validate_flow_step(state3, "act") is False

    def test_no_state_rejects_flow_checked_actions(self):
        """None state should reject all flow-checked actions."""
        for action in _FLOW_STEP_RULES:
            assert _validate_flow_step(None, action) is False

    def test_unregulated_actions_always_pass(self):
        """Actions without flow/step rules should always pass."""
        for action in ("sm", "df", "do", "ro", "ra", "af", "co", "ct", "cmo"):
            assert _validate_flow_step(None, action) is True
            assert _validate_flow_step({"flow": "any"}, action) is True


# ============================================================================
#                     KEYBOARD TOKEN EMBEDDING TESTS
# ============================================================================

class TestKeyboardTokenEmbedding:
    """Tests that keyboard functions embed token in callback_data."""

    def test_order_type_keyboard_has_token(self):
        """nlp_order_type_keyboard should include token in callback_data."""
        kb = nlp_order_type_keyboard("ab12")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        token_callbacks = [c for c in callbacks if c.startswith("nlp:ot:")]
        for cb in token_callbacks:
            assert cb.endswith(":ab12"), f"Missing token in {cb}"

    def test_order_qty_keyboard_has_token(self):
        """nlp_order_qty_keyboard should include token."""
        kb = nlp_order_qty_keyboard("x1y2")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        qty_callbacks = [c for c in callbacks if c.startswith("nlp:oq:")]
        for cb in qty_callbacks:
            assert cb.endswith(":x1y2"), f"Missing token in {cb}"

    def test_order_confirm_keyboard_has_token(self):
        """nlp_order_confirm_keyboard should include token."""
        kb = nlp_order_confirm_keyboard("t3st")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        od_callbacks = [c for c in callbacks if c.startswith("nlp:od:") or c.startswith("nlp:oc")]
        for cb in od_callbacks:
            assert cb.endswith(":t3st"), f"Missing token in {cb}"

    def test_model_actions_keyboard_has_token(self):
        """nlp_model_actions_keyboard should include token."""
        kb = nlp_model_actions_keyboard("zz99")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        act_callbacks = [c for c in callbacks if c.startswith("nlp:act:")]
        for cb in act_callbacks:
            assert cb.endswith(":zz99"), f"Missing token in {cb}"

    def test_cancel_button_has_no_token(self):
        """Cancel button should NOT have a token (always allowed)."""
        kb = nlp_order_type_keyboard("ab12")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        cancel_callbacks = [c for c in callbacks if c.startswith("nlp:x:")]
        for cb in cancel_callbacks:
            assert cb == "nlp:x:c", f"Cancel button has extra data: {cb}"

    def test_keyboard_without_token_works(self):
        """Keyboards should work without token (backwards compat)."""
        kb = nlp_order_type_keyboard()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        ot_callbacks = [c for c in callbacks if c.startswith("nlp:ot:")]
        # Without token, should have exactly 3 parts: nlp:ot:type
        for cb in ot_callbacks:
            parts = cb.split(":")
            assert len(parts) == 3, f"Expected 3 parts without token: {cb}"

    def test_callback_data_under_64_bytes(self):
        """All callback_data should be under 64 bytes."""
        long_token = "zzzz"
        keyboards = [
            nlp_order_type_keyboard(long_token),
            nlp_order_qty_keyboard(long_token),
            nlp_order_confirm_keyboard(long_token),
            nlp_model_actions_keyboard(long_token),
            nlp_shoot_date_keyboard(long_token),
            nlp_close_order_date_keyboard(long_token),
            nlp_disambiguate_keyboard(999, long_token),
            nlp_files_qty_keyboard(long_token),
            nlp_report_keyboard(long_token),
        ]
        for kb in keyboards:
            for row in kb.inline_keyboard:
                for btn in row:
                    data = btn.callback_data
                    assert len(data.encode("utf-8")) < 64, \
                        f"callback_data too long ({len(data.encode('utf-8'))} bytes): {data}"


# ============================================================================
#                   FULL ORDER FLOW SCENARIO TEST
# ============================================================================

class TestOrderFlowScenario:
    """Simulates a full order flow to verify state transitions and validation."""

    def test_full_order_flow_state_transitions(self):
        """model -> act:order -> ot:custom -> oq:2 -> od:today -> oc.
        Verify that state transitions are correct at each step.
        """
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # Step 1: Model selected → nlp_actions
        k1 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_actions",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k1,
        })
        state = memory.get(user_id)
        assert _validate_flow_step(state, "act") is True
        assert _validate_token(state, ["nlp", "act", "order", k1], "act") is True

        # Step 2: act:order → nlp_order, awaiting_type
        k2 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_type",
            "model_id": "page-123",
            "model_name": "мелиса",
            "k": k2,
        })
        state = memory.get(user_id)
        assert _validate_flow_step(state, "ot") is True
        assert _validate_token(state, ["nlp", "ot", "custom", k2], "ot") is True
        # oq should NOT be valid at this step
        assert _validate_flow_step(state, "oq") is False

        # Step 3: ot:custom → awaiting_count
        k3 = generate_token()
        memory.update(user_id, step="awaiting_count", order_type="custom", k=k3)
        state = memory.get(user_id)
        assert _validate_flow_step(state, "oq") is True
        assert _validate_token(state, ["nlp", "oq", "2", k3], "oq") is True
        # Old k2 should be rejected
        assert _validate_token(state, ["nlp", "oq", "2", k2], "oq") is False
        # ot should NOT be valid anymore
        assert _validate_flow_step(state, "ot") is False

        # Step 4: oq:2 → awaiting_date
        k4 = generate_token()
        memory.update(user_id, step="awaiting_date", count=2, k=k4)
        state = memory.get(user_id)
        assert _validate_flow_step(state, "od") is True
        assert _validate_flow_step(state, "oc") is True
        assert _validate_token(state, ["nlp", "od", "today", k4], "od") is True
        # oq should NOT be valid anymore
        assert _validate_flow_step(state, "oq") is False

        # Step 5: od:today or oc → order created, state cleared
        memory.clear(user_id)
        assert memory.get(user_id) is None


# ============================================================================
#               STALE TOKEN SCENARIO TEST
# ============================================================================

class TestStaleTokenScenario:
    """Tests the anti-stale token rejection mechanism."""

    def test_stale_oq_after_new_keyboard(self):
        """Press oq with old k after new k → should be rejected."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # First keyboard with k1
        k1 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_count",
            "model_id": "page-123",
            "k": k1,
        })

        # New keyboard sent (e.g., user went back) with k2
        k2 = generate_token()
        memory.update(user_id, k=k2)

        state = memory.get(user_id)

        # Old button press
        old_callback_parts = ["nlp", "oq", "2", k1]
        assert _validate_token(state, old_callback_parts, "oq") is False

        # New button press
        new_callback_parts = ["nlp", "oq", "2", k2]
        assert _validate_token(state, new_callback_parts, "oq") is True

    def test_stale_after_flow_change(self):
        """When flow changes entirely, old callbacks should fail validation."""
        memory = MemoryState(ttl_seconds=60)
        user_id = 42

        # Was in order flow
        k1 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_order",
            "step": "awaiting_count",
            "model_id": "page-123",
            "k": k1,
        })

        # User starts new flow (shoot)
        k2 = generate_token()
        memory.set(user_id, {
            "flow": "nlp_shoot",
            "step": "awaiting_date",
            "model_id": "page-123",
            "k": k2,
        })

        state = memory.get(user_id)

        # Old order button should fail both flow AND token checks
        assert _validate_flow_step(state, "oq") is False
        assert _validate_token(state, ["nlp", "oq", "2", k1], "oq") is False


# ============================================================================
#                    CUSTOM DATE LOGIC TESTS
# ============================================================================

class TestCustomDateLogic:
    """Tests for the date parsing logic (fixes datetime.resolution * 90 bug)."""

    def test_jan10_when_today_feb06_is_same_year(self):
        """'10.01' when today=06.02 → should be 10 Jan of CURRENT year, not next.

        The bug was using datetime.resolution * 90 (microseconds) instead of
        timedelta(days=90), causing any past date to jump to next year.
        """
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("10.01", base_date=today)
        assert result is not None
        assert result == date(2026, 1, 10), \
            f"Expected 2026-01-10, got {result}"

    def test_feb05_when_today_feb06_is_same_year(self):
        """'05.02' when today=06.02 → should be 05 Feb of CURRENT year.

        Only 1 day in the past, well within 90-day threshold.
        """
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("05.02", base_date=today)
        assert result is not None
        assert result == date(2026, 2, 5), \
            f"Expected 2026-02-05, got {result}"

    def test_close_date_custom_05_02_at_06_02(self):
        """nlp_close cd:custom → input '05.02' (today=06.02) → 05.02 current year."""
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("05.02", base_date=today)
        assert result == date(2026, 2, 5)

    def test_date_far_past_jumps_to_next_year(self):
        """Date more than 90 days in the past should jump to next year.

        E.g., '01.10' when today=06.02 → Oct 1 is ~128 days ago → next year.
        """
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("01.10", base_date=today)
        assert result is not None
        assert result == date(2026, 10, 1), \
            f"Expected 2026-10-01, got {result}"

    def test_date_exactly_90_days_ago(self):
        """Date exactly 90 days in the past should NOT jump."""
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        # 90 days before 2026-02-06 = 2025-11-08
        past_90 = today - timedelta(days=90)
        date_str = f"{past_90.day:02d}.{past_90.month:02d}"
        result = parse_date_ru(date_str, base_date=today)
        assert result is not None
        assert result.year == today.year, \
            f"Date 90 days ago should stay same year: {result}"

    def test_date_more_than_90_days_ago_jumps(self):
        """Date more than 90 days in the past should jump to next year.

        Use today=2026-06-15, date_str='01.02' → 2026-02-01 is ~134 days ago
        → should become 2027-02-01.
        """
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 6, 15)
        result = parse_date_ru("01.02", base_date=today)
        assert result is not None
        assert result == date(2027, 2, 1), \
            f"Expected 2027-02-01, got {result}"

    def test_future_date_same_year(self):
        """Future date should always be same year."""
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("15.03", base_date=today)
        assert result == date(2026, 3, 15)

    def test_today_date(self):
        """Today's date should be same year."""
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("06.02", base_date=today)
        assert result == date(2026, 2, 6)

    def test_yesterday_date(self):
        """Yesterday's date should be same year."""
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("05.02", base_date=today)
        assert result == date(2026, 2, 5)

    def test_invalid_date_returns_none(self):
        """Invalid date like 31.02 should return None."""
        from app.router.entities_v2 import parse_date_ru

        today = date(2026, 2, 6)
        result = parse_date_ru("31.02", base_date=today)
        assert result is None


# ============================================================================
#                 KEYBOARD STRUCTURE TESTS
# ============================================================================

class TestKeyboardStructure:
    """Tests for keyboard structural properties."""

    def test_stale_keyboard_has_menu_and_reset(self):
        """Stale keyboard should have Меню and Сброс buttons."""
        kb = nlp_stale_keyboard()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "nlp:x:m" in callbacks
        assert "nlp:x:c" in callbacks

    def test_order_type_ad_request_has_underscore(self):
        """Ad Request button should use 'ad_request' (no space) in callback."""
        kb = nlp_order_type_keyboard("test")
        found = False
        for row in kb.inline_keyboard:
            for btn in row:
                if "Ad Request" in btn.text:
                    assert "ad_request" in btn.callback_data
                    assert "ad request" not in btn.callback_data
                    found = True
        assert found, "Ad Request button not found in keyboard"

    def test_confirm_model_keyboard_has_token(self):
        """nlp_confirm_model_keyboard should embed token."""
        kb = nlp_confirm_model_keyboard("page-123", "мелиса", "ab12")
        yes_btn = kb.inline_keyboard[0][0]
        assert yes_btn.callback_data.endswith(":ab12")

    def test_model_selection_keyboard_has_token(self):
        """nlp_model_selection_keyboard should embed token."""
        models = [{"id": "p1", "name": "Модель 1"}, {"id": "p2", "name": "Модель 2"}]
        kb = nlp_model_selection_keyboard(models, "zz99")
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data.startswith("nlp:sm:"):
                    assert btn.callback_data.endswith(":zz99")


# ============================================================================
#              DISPATCHER DATE FIX INTEGRATION TEST
# ============================================================================

class TestDispatcherDateFix:
    """Tests that the dispatcher date logic uses timedelta(days=90)."""

    def test_dispatcher_uses_timedelta_not_resolution(self):
        """Verify the dispatcher code uses timedelta(days=90), not datetime.resolution."""
        import inspect
        from app.router import dispatcher

        source = inspect.getsource(dispatcher._handle_custom_date_input)
        assert "timedelta(days=90)" in source, \
            "Expected timedelta(days=90) in _handle_custom_date_input"
        assert "datetime.resolution" not in source, \
            "datetime.resolution should be replaced with timedelta(days=90)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
