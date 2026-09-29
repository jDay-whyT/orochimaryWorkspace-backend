import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from app.keyboards.inline import (
    nlp_orders_menu_keyboard,
    nlp_files_menu_keyboard,
    nlp_shoot_menu_keyboard,
    nlp_order_date_keyboard,
    nlp_order_confirm_keyboard,
)
from app.handlers import nlp_callbacks
from app.router.dispatcher import _handle_shoot_comment_input
from app.state.memory import MemoryState
from app.services.notion import NotionOrder, NotionPlanner
from app.utils import PAGE_SIZE


def _make_config(allowed_editors=None):
    cfg = MagicMock()
    cfg.allowed_editors = allowed_editors or set()
    cfg.db_orders = "db_orders"
    cfg.db_planner = "db_planner"
    cfg.db_accounting = "db_accounting"
    cfg.files_per_month = 200
    cfg.timezone = ZoneInfo("Europe/Brussels")
    return cfg


class TestAccessAndBackButtons:
    def test_orders_menu_hides_write_buttons_for_viewer(self):
        kb = nlp_orders_menu_keyboard(can_edit=False, has_orders=True, model_id="m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "➕ Order" not in texts
        assert "✓ Close" not in texts
        assert any("Back" in t for t in texts)

    def test_files_menu_only_actions_and_back(self):
        kb = nlp_files_menu_keyboard(can_edit=True, model_id="m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "+ Files" in texts
        assert "💬 Comment" in texts
        assert any("Back" in t for t in texts)

    def test_files_menu_viewer_only_back(self):
        kb = nlp_files_menu_keyboard(can_edit=False, model_id="m1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert texts == ["⬅ Back"]

    def test_shoot_menu_has_content_comment_back(self):
        kb = nlp_shoot_menu_keyboard(can_edit=True, model_id="m1", actions=True)
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "✅ Shot done" in texts and "✏️ Edit" in texts   # date / content / comment are under Edit
        assert any("Back" in t for t in texts)


class TestOrderCreationDateFlow:
    def test_date_keyboard_before_confirm(self):
        kb = nlp_order_date_keyboard("m1", "t1")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "✅ Create" not in texts
        assert "📅 Other date" in texts

    def test_confirm_keyboard_has_create(self):
        kb = nlp_order_confirm_keyboard("m1", "t2")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "✓ Create" in texts


class TestOrdersAggregationAndPagination:
    @pytest.mark.asyncio
    async def test_short_order_aggregated(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        memory = MemoryState()
        memory.set(1, 1, {
            "flow": "nlp_order",
            "step": "awaiting_confirm",
            "model_id": "m1",
            "model_name": "Модель",
            "order_type": "short",
            "count": 3,
            "in_date": date(2026, 2, 1).isoformat(),
        })
        recent_models = MagicMock()

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.message.chat.id = 1
        query.answer = AsyncMock()

        await nlp_callbacks._handle_order_confirm(
            query, ["nlp", "oc"], config, notion, memory, recent_models,
        )

        assert notion.create_order.call_count == 1
        call_kwargs = notion.create_order.call_args.kwargs
        assert call_kwargs["count"] == 3

    @pytest.mark.asyncio
    async def test_non_short_orders_create_multiple(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        memory = MemoryState()
        memory.set(1, 1, {
            "flow": "nlp_order",
            "step": "awaiting_confirm",
            "model_id": "m1",
            "model_name": "Модель",
            "order_type": "custom",
            "count": 2,
            "in_date": date(2026, 2, 1).isoformat(),
        })
        recent_models = MagicMock()

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.message.chat.id = 1
        query.answer = AsyncMock()

        await nlp_callbacks._handle_order_confirm(
            query, ["nlp", "oc"], config, notion, memory, recent_models,
        )

        assert notion.create_order.call_count == 2
        for call in notion.create_order.call_args_list:
            assert call.kwargs["count"] == 1

    @pytest.mark.asyncio
    async def test_orders_view_pagination(self):
        config = _make_config()
        memory = MemoryState()
        orders = [
            NotionOrder(page_id=f"o{i}", title="t", order_type="custom", in_date="2026-02-01")
            for i in range(PAGE_SIZE + 2)
        ]
        memory.set(1, 1, {
            "flow": "nlp_orders_menu",
            "step": "menu",
            "model_id": "m1",
            "model_name": "Модель",
            "orders": orders,
        })
        notion = AsyncMock()

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.message.chat.id = 1
        query.answer = AsyncMock()

        await nlp_callbacks._show_orders_view(query, config, notion, memory, page=1)

        _, kwargs = query.message.edit_text.call_args
        reply_markup = kwargs["reply_markup"]
        buttons = [btn.text for row in reply_markup.inline_keyboard for btn in row]
        assert "➡️" in buttons

    @pytest.mark.asyncio
    async def test_close_picker_pagination(self):
        config = _make_config(allowed_editors={1})
        memory = MemoryState()
        orders = [
            NotionOrder(page_id=f"o{i}", title="t", order_type="custom", in_date="2026-02-01")
            for i in range(PAGE_SIZE + 1)
        ]
        notion = AsyncMock()
        notion.query_open_orders.return_value = orders

        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.message.chat.id = 1
        query.answer = AsyncMock()

        await nlp_callbacks._show_close_picker(
            query, "m1", "Модель", config, notion, memory,
        )

        _, kwargs = query.message.edit_text.call_args
        reply_markup = kwargs["reply_markup"]
        buttons = [btn.text for row in reply_markup.inline_keyboard for btn in row]
        assert "➡️" in buttons


class TestShootContentAndComment:
    @pytest.mark.asyncio
    async def test_shoot_content_updates_notion(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        memory = MemoryState()
        memory.set(1, 1, {
            "flow": "nlp_shoot",
            "step": "awaiting_content_update",
            "shoot_id": "s1",
            "model_id": "m1",
            "model_name": "Модель",
            "content_types": ["Twitter"],
        })
        query = MagicMock()
        query.from_user.id = 1
        query.message.edit_text = AsyncMock()
        query.message.chat.id = 1
        query.answer = AsyncMock()

        await nlp_callbacks._handle_shoot_content_done(
            query, ["nlp", "scd", "done"], config, notion, memory, MagicMock(),
        )

        notion.update_shoot_content.assert_called_once_with("s1", ["Twitter"])

    @pytest.mark.asyncio
    async def test_shoot_comment_updates_notion(self):
        config = _make_config(allowed_editors={1})
        notion = AsyncMock()
        notion.get_shoot.return_value = NotionPlanner(
            page_id="s1", title="Shoot", comments="old",
        )
        memory = MemoryState()
        user_state = {
            "flow": "nlp_shoot",
            "step": "awaiting_shoot_comment",
            "shoot_id": "s1",
            "model_name": "Модель",
        }

        message = MagicMock()
        message.from_user.id = 1
        message.answer = AsyncMock()

        await _handle_shoot_comment_input(
            message, "new comment", user_state, config, notion, memory,
        )

        assert notion.update_shoot_comment.called



# ---------- shoots menu ----------

class TestShootMenu:
    @staticmethod
    def _shoot(pid, day, status="scheduled", content=("main pack",), location="home", comments=None):
        return NotionPlanner(page_id=pid, title="s", model_id="m1", date=day, status=status,
                             content=list(content), location=location, comments=comments)

    async def _render(self, monkeypatch, open_shoots, last=None):
        shown = {}

        async def fake_edit(query, text, reply_markup=None, parse_mode=None):
            shown["text"], shown["kb"] = text, reply_markup
            return None

        monkeypatch.setattr(nlp_callbacks, "safe_edit_message", fake_edit)
        monkeypatch.setattr(nlp_callbacks, "_clear_previous_screen_keyboard", AsyncMock())
        notion = MagicMock(spec=["query_upcoming_shoots", "query_last_done_shoot"])
        notion.query_upcoming_shoots = AsyncMock(return_value=open_shoots)
        notion.query_last_done_shoot = AsyncMock(return_value=last)
        memory = MemoryState()
        query = MagicMock()
        query.from_user.id = 1
        query.message.chat.id = 100
        query.message.message_id = 5
        memory.set(100, 1, {"flow": "nlp_actions", "model_id": "m1", "model_name": "ЗАПАД"})
        await nlp_callbacks._show_shoot_menu(query, _make_config({1}), notion, memory)
        buttons = [b.callback_data for row in shown["kb"].inline_keyboard for b in row]
        return shown["text"], buttons, memory.get(100, 1)

    @pytest.mark.asyncio
    async def test_one_shoot_shows_its_actions_and_the_last_done(self, monkeypatch):
        text, buttons, state = await self._render(
            monkeypatch,
            [self._shoot("s1", "2099-09-29", comments="white set\nsecond line")],
            last=self._shoot("s0", "2026-09-20", status="done", content=("reddit",)),
        )
        assert "Last: 20 Sep, Sun · done · reddit · home" in text
        assert "29 Sep, Tue · scheduled · main pack · home" in text and "💬 white set" in text
        assert "nlp:smn:close" in buttons and "nlp:smn:new" in buttons
        assert state["shoot_id"] == "s1"

    @pytest.mark.asyncio
    async def test_several_shoots_are_picked_first(self, monkeypatch):
        text, buttons, state = await self._render(
            monkeypatch, [self._shoot("s2", "2099-10-03"), self._shoot("s1", "2099-09-29")],
        )
        assert text.index("29 Sep") < text.index("3 Oct")          # by date
        assert "nlp:smn:pick0" in buttons and "nlp:smn:pick1" in buttons
        assert "nlp:smn:close" not in buttons                       # nothing acts on a hidden shoot
        assert state["shoot_ids"] == ["s1", "s2"] and state["shoot_id"] is None

    @pytest.mark.asyncio
    async def test_overdue_open_shoot_is_flagged(self, monkeypatch):
        text, _, _ = await self._render(monkeypatch, [self._shoot("s1", "2020-01-02", status="planned")])
        assert "⚠️ 2 Jan" in text

    def test_done_asks_for_confirmation(self):
        from app.keyboards.inline import nlp_shoot_done_confirm_keyboard
        buttons = [b.callback_data for row in nlp_shoot_done_confirm_keyboard().inline_keyboard for b in row]
        assert buttons == ["nlp:smn:closeok", "nlp:smn:list"]


# ---------- new shoot: day -> content -> location -> comment ----------

class TestNewShootFlow:
    @staticmethod
    def _setup(monkeypatch):
        screens = []

        async def fake_edit(query, text, reply_markup=None, parse_mode=None):
            screens.append((text, reply_markup))
            return None

        monkeypatch.setattr(nlp_callbacks, "safe_edit_message", fake_edit)
        monkeypatch.setattr(nlp_callbacks, "_safe_confirm", AsyncMock())
        monkeypatch.setattr(nlp_callbacks, "_clear_previous_screen_keyboard", AsyncMock())
        monkeypatch.setattr(nlp_callbacks, "safe_query_answer", AsyncMock())
        monkeypatch.setattr(nlp_callbacks.activity_log, "record", AsyncMock())
        memory = MemoryState()
        query = MagicMock()
        query.from_user.id = 1
        query.from_user.username = "m"
        query.message.chat.id = 100
        query.message.message_id = 5
        notion = AsyncMock()
        config = _make_config({1})
        config.timezone = ZoneInfo("Europe/Brussels")
        return screens, memory, query, notion, config

    @staticmethod
    def _callbacks(markup):
        return [b.callback_data for row in markup.inline_keyboard for b in row]

    @pytest.mark.asyncio
    async def test_day_first_then_content_location_comment(self, monkeypatch):
        screens, memory, query, notion, config = self._setup(monkeypatch)
        memory.set(100, 1, {"flow": "nlp_shoot_menu", "model_id": "m1", "model_name": "ЗАПАД"})
        await nlp_callbacks._handle_shoot_menu_action(query, ["nlp", "smn", "new"], config, notion, memory, MagicMock())
        assert "When is the shoot?" in screens[-1][0]
        assert "nlp:sn:nodate" in self._callbacks(screens[-1][1])

        await nlp_callbacks._handle_new_shoot(query, ["nlp", "sn", "d", "2099-10-03"], config, notion, memory, MagicMock())
        assert "03.10" in screens[-1][0] and "Choose content" in screens[-1][0]
        memory.update(100, 1, content_types=["main pack"])
        await nlp_callbacks._handle_shoot_content_done(query, ["nlp", "scd", "done"], config, notion, memory, MagicMock())
        assert "Location" in screens[-1][0]
        await nlp_callbacks._handle_shoot_location(query, ["nlp", "sl", "rent"], config, notion, memory, MagicMock())
        assert "Comment for the shoot" in screens[-1][0]
        notion.create_shoot.assert_not_awaited()

        await nlp_callbacks._handle_new_shoot(query, ["nlp", "sn", "skip"], config, notion, memory, MagicMock())
        kwargs = notion.create_shoot.await_args.kwargs
        assert kwargs["status"] == "scheduled" and kwargs["shoot_date"] == date(2099, 10, 3)
        assert kwargs["location"] == "rent" and kwargs["content"] == ["main pack"] and kwargs["comments"] is None

    @pytest.mark.asyncio
    async def test_no_date_yet_is_planned_without_date(self, monkeypatch):
        screens, memory, query, notion, config = self._setup(monkeypatch)
        memory.set(100, 1, {"flow": "nlp_shoot", "step": "awaiting_date", "model_id": "m1", "model_name": "M",
                            "content_types": []})
        await nlp_callbacks._handle_new_shoot(query, ["nlp", "sn", "nodate"], config, notion, memory, MagicMock())
        await nlp_callbacks._handle_shoot_content_done(query, ["nlp", "scd", "done"], config, notion, memory, MagicMock())
        await nlp_callbacks._handle_shoot_location(query, ["nlp", "sl", "home"], config, notion, memory, MagicMock())
        text = await nlp_callbacks.create_new_shoot(config, notion, query.from_user, memory.get(100, 1), "bring the red set")
        kwargs = notion.create_shoot.await_args.kwargs
        assert kwargs["status"] == "planned" and kwargs["shoot_date"] is None
        assert kwargs["comments"] == "bring the red set" and "no date" in text

    @pytest.mark.asyncio
    async def test_other_date_is_typed_then_content(self, monkeypatch):
        from app.router import dispatcher
        screens, memory, query, notion, config = self._setup(monkeypatch)
        memory.set(100, 1, {"flow": "nlp_shoot", "step": "awaiting_date", "model_id": "m1", "model_name": "M",
                            "content_types": []})
        await nlp_callbacks._handle_new_shoot(query, ["nlp", "sn", "custom"], config, notion, memory, MagicMock())
        assert "Enter date (DD.MM)" in screens[-1][0]
        assert memory.get(100, 1)["step"] == "awaiting_custom_date"

        message = MagicMock()
        message.from_user.id = 1
        message.chat.id = 100
        message.answer = AsyncMock(return_value=MagicMock(message_id=9))
        monkeypatch.setattr(dispatcher, "_clear_previous_screen_keyboard", AsyncMock())
        monkeypatch.setattr(dispatcher, "_cleanup_prompt_message", AsyncMock())
        await dispatcher._handle_custom_date_input(message, "15.10", memory.get(100, 1), config, notion, memory)
        state = memory.get(100, 1)
        assert state["step"] == "awaiting_content" and state["shoot_date"].endswith("-10-15")
        assert "Choose content" in message.answer.await_args.args[0]


# ---------- reschedule / set date ----------

@pytest.mark.asyncio
async def test_moving_a_dated_shoot_is_rescheduled():
    notion = AsyncMock()
    text = await nlp_callbacks.move_shoot(notion, "s1", "2026-09-29", date(2026, 10, 1))
    notion.reschedule_shoot.assert_awaited_with("s1", date(2026, 10, 1), status="rescheduled")
    assert text == "✅ Shoot moved: 29 Sep → 1 Oct"


@pytest.mark.asyncio
async def test_first_date_of_an_undated_shoot_is_scheduled():
    notion = AsyncMock()
    text = await nlp_callbacks.move_shoot(notion, "s1", None, date(2026, 10, 1))
    notion.reschedule_shoot.assert_awaited_with("s1", date(2026, 10, 1), status="scheduled")
    assert text == "✅ Date set: 1 Oct · scheduled"


def test_undated_shoot_offers_set_date_and_reschedule_has_today():
    from app.keyboards.inline import nlp_shoot_date_keyboard, nlp_shoot_edit_keyboard
    texts = [b.text for row in nlp_shoot_edit_keyboard(has_date=False).inline_keyboard for b in row]
    assert "📅 Set date" in texts
    texts = [b.text for row in nlp_shoot_edit_keyboard(has_date=True).inline_keyboard for b in row]
    assert texts == ["📅 Date", "🗂 Content", "💬 Comment", "← Back"]
    calls = [b.callback_data for row in nlp_shoot_date_keyboard("m1", "k").inline_keyboard for b in row]
    assert calls[:3] == ["nlp:sd:today:k", "nlp:sd:tomorrow:k", "nlp:sd:day_after:k"]


@pytest.mark.asyncio
async def test_edit_opens_date_content_comment_and_back_returns(monkeypatch):
    shown = []

    async def fake_edit(query, text, reply_markup=None, parse_mode=None):
        shown.append((text, [b.callback_data for row in reply_markup.inline_keyboard for b in row]))

    monkeypatch.setattr(nlp_callbacks, "safe_edit_message", fake_edit)
    monkeypatch.setattr(nlp_callbacks, "_clear_previous_screen_keyboard", AsyncMock())
    shoot = NotionPlanner(page_id="s1", title="s", model_id="m1", date="2099-09-29", status="scheduled",
                          content=["main pack"], location="home")
    notion = MagicMock(spec=["get_shoot", "query_upcoming_shoots", "query_last_done_shoot"])
    notion.get_shoot = AsyncMock(return_value=shoot)
    notion.query_upcoming_shoots = AsyncMock(return_value=[shoot])
    notion.query_last_done_shoot = AsyncMock(return_value=None)
    memory = MemoryState()
    memory.set(100, 1, {"flow": "nlp_shoot_menu", "model_id": "m1", "model_name": "M",
                        "shoot_ids": ["s1"], "shoot_id": "s1"})
    query = MagicMock()
    query.from_user.id = 1
    query.message.chat.id = 100
    config = _make_config({1})

    await nlp_callbacks._handle_shoot_menu_action(query, ["nlp", "smn", "edit"], config, notion, memory, MagicMock())
    assert shown[-1][0].startswith("✏️") and shown[-1][1] == [
        "nlp:smn:reschedule", "nlp:smn:content", "nlp:smn:comment", "nlp:smn:view"]
    await nlp_callbacks._handle_shoot_menu_action(query, ["nlp", "smn", "view"], config, notion, memory, MagicMock())
    assert "nlp:smn:edit" in shown[-1][1] and "nlp:smn:close" in shown[-1][1]


# ---------- orders screen ----------

def test_order_line_shows_count_received_and_overdue():
    from app.keyboards.inline import order_line
    today = date(2026, 9, 28)
    short = NotionOrder(page_id="o1", title="t", order_type="short", in_date="2026-09-22", count=8, received=5, status="Open")
    custom = NotionOrder(page_id="o2", title="t", order_type="custom", in_date="2026-09-27", count=1, status="Open")
    assert order_line(short, today) == "⚠️ short ×8 (5/8) · 22 Sep · 6d"
    assert order_line(custom, today) == "custom · 27 Sep · 1d"


@pytest.mark.asyncio
async def test_orders_screen_lists_five_oldest_and_offers_view_all(monkeypatch):
    shown = {}

    async def fake_edit(query, text, reply_markup=None, parse_mode=None):
        shown["text"] = text
        shown["buttons"] = [b.text for row in reply_markup.inline_keyboard for b in row]

    monkeypatch.setattr(nlp_callbacks, "safe_edit_message", fake_edit)
    monkeypatch.setattr(nlp_callbacks, "_clear_previous_screen_keyboard", AsyncMock())
    orders = [NotionOrder(page_id=f"o{i}", title="t", order_type="custom", in_date=f"2026-09-{10 + i:02d}",
                          count=1, status="Open") for i in range(7)]
    monkeypatch.setattr(nlp_callbacks.orders_cache, "get_cached_orders", AsyncMock(return_value=list(reversed(orders))))
    memory = MemoryState()
    memory.set(100, 1, {"flow": "nlp_actions", "model_id": "m1", "model_name": "M"})
    query = MagicMock()
    query.from_user.id = 1
    query.message.chat.id = 100
    await nlp_callbacks._show_orders_menu(query, _make_config({1}), MagicMock(), memory)
    assert "Open orders (7):" in shown["text"] and "10 Sep" in shown["text"] and "…and 2 more" in shown["text"]
    assert "16 Sep" not in shown["text"]                    # only the 5 oldest are listed
    assert "📄 View all" in shown["buttons"] and "✓ Close" in shown["buttons"]
