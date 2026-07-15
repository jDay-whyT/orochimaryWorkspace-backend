"""Tests for Tango schedule parser: app/services/tango_schedule.py."""
from app.services.tango_schedule import (
    TangoRawRow,
    build_tomorrow_schedule,
    find_entries,
    is_cancelled_red,
    is_paused_row,
    sort_key,
)

WHITE = {"red": 1, "green": 1, "blue": 1}
GRAY = {"red": 0.6, "green": 0.6, "blue": 0.6}
RED = {"red": 0.8, "green": 0.1, "blue": 0.1}


class TestFindEntries:
    def test_parses_single_entry(self):
        entries = find_entries("14.07 — 20:00")
        assert len(entries) == 1
        assert entries[0]["date"] == "14.07"
        assert entries[0]["time"] == "20:00"
        assert entries[0]["hour"] == 20

    def test_parses_multiple_entries_dirty_whitespace(self):
        cell = "13.07 — 20:00\n14.07  —  20:00\n15.07 —20:00\n16.07— 20:00"
        entries = find_entries(cell)
        dates = [e["date"] for e in entries]
        assert dates == ["13.07", "14.07", "15.07", "16.07"]

    def test_no_entries_returns_empty(self):
        assert find_entries("—") == []
        assert find_entries("") == []

    def test_entry_offsets_are_correct(self):
        cell = "xx 14.07 — 20:00"
        entries = find_entries(cell)
        assert entries[0]["start"] == 3


class TestSortKey:
    def test_normal_hours_unchanged(self):
        assert sort_key(9) == 9
        assert sort_key(21) == 21
        assert sort_key(6) == 6

    def test_early_morning_pushed_to_end(self):
        assert sort_key(0) == 24
        assert sort_key(1) == 25
        assert sort_key(5) == 29

    def test_ordering_matches_expected_stream_day(self):
        hours = [9, 22, 1, 21, 10]
        ordered = sorted(hours, key=sort_key)
        assert ordered == [9, 10, 21, 22, 1]


class TestIsCancelledRed:
    def test_red_text_detected(self):
        assert is_cancelled_red({"foregroundColor": RED}) is True

    def test_black_text_not_red(self):
        assert is_cancelled_red({"foregroundColor": {"red": 0, "green": 0, "blue": 0}}) is False

    def test_missing_color_not_red(self):
        assert is_cancelled_red({}) is False


class TestIsPausedRow:
    def test_gray_background_is_paused(self):
        assert is_paused_row(GRAY) is True

    def test_white_background_not_paused(self):
        assert is_paused_row(WHITE) is False

    def test_missing_background_not_paused(self):
        assert is_paused_row(None) is False

    def test_colored_non_gray_not_paused(self):
        assert is_paused_row(RED) is False


class TestBuildTomorrowSchedule:
    def test_filters_to_tomorrow_only(self):
        rows = [
            TangoRawRow(
                name="Танго 1",
                name_background=None,
                week_text="13.07 — 20:00\n14.07 — 20:00\n15.07 — 20:00",
                week_text_format_runs=None,
            )
        ]
        result = build_tomorrow_schedule(rows, "14.07")
        assert len(result) == 1
        assert result[0].time == "20:00"
        assert result[0].model_name == "Танго 1"

    def test_excludes_strikethrough_entry(self):
        cell = "14.07 — 20:00"
        runs = [{"startIndex": 0, "format": {"strikethrough": True}}]
        rows = [TangoRawRow(name="Танго 1", name_background=None, week_text=cell, week_text_format_runs=runs)]
        assert build_tomorrow_schedule(rows, "14.07") == []

    def test_excludes_red_cancelled_entry(self):
        cell = "14.07 — 20:00"
        runs = [{"startIndex": 0, "format": {"foregroundColor": RED}}]
        rows = [TangoRawRow(name="Танго 1", name_background=None, week_text=cell, week_text_format_runs=runs)]
        assert build_tomorrow_schedule(rows, "14.07") == []

    def test_only_matching_substring_excluded_not_whole_cell(self):
        # first entry (13.07) struck through, second (14.07) is normal — offsets matter
        cell = "13.07 — 20:00\n14.07 — 21:00"
        runs = [
            {"startIndex": 0, "format": {"strikethrough": True}},
            {"startIndex": 14, "format": {}},
        ]
        rows = [TangoRawRow(name="Танго 1", name_background=None, week_text=cell, week_text_format_runs=runs)]
        result = build_tomorrow_schedule(rows, "14.07")
        assert len(result) == 1
        assert result[0].time == "21:00"

    def test_excludes_paused_model_entirely(self):
        rows = [
            TangoRawRow(name="Нига", name_background=GRAY, week_text="14.07 — 11:00", week_text_format_runs=None)
        ]
        assert build_tomorrow_schedule(rows, "14.07") == []

    def test_sorts_by_stream_day_with_early_morning_last(self):
        rows = [
            TangoRawRow(name="A", name_background=None, week_text="14.07 — 22:00", week_text_format_runs=None),
            TangoRawRow(name="B", name_background=None, week_text="14.07 — 09:00", week_text_format_runs=None),
            TangoRawRow(name="C", name_background=None, week_text="15.07 — 01:00", week_text_format_runs=None),
        ]
        result = build_tomorrow_schedule(rows, "14.07", "15.07")
        assert [e.model_name for e in result] == ["B", "A", "C"]

    def test_pulls_in_early_morning_tail_from_day_after(self):
        # Shift starts 14.07 evening, tail logged as 15.07 01:00 — belongs to 14.07's day
        rows = [
            TangoRawRow(name="Смайл", name_background=None, week_text="15.07 — 01:00", week_text_format_runs=None)
        ]
        result = build_tomorrow_schedule(rows, "14.07", "15.07")
        assert len(result) == 1
        assert result[0].time == "01:00"
        assert result[0].sort_hour == 25

    def test_day_after_entry_at_or_after_6am_excluded(self):
        rows = [
            TangoRawRow(name="Смайл", name_background=None, week_text="15.07 — 06:00", week_text_format_runs=None)
        ]
        assert build_tomorrow_schedule(rows, "14.07", "15.07") == []

    def test_day_after_not_provided_ignores_next_day_entries(self):
        rows = [
            TangoRawRow(name="Смайл", name_background=None, week_text="15.07 — 01:00", week_text_format_runs=None)
        ]
        assert build_tomorrow_schedule(rows, "14.07") == []

    def test_same_date_early_morning_entry_excluded_belongs_to_previous_day(self):
        # A "14.07 — 02:00" entry is the tail of 13.07's stream day, not 14.07's own —
        # it would only show up when building *13.07*'s schedule (day_after="14.07").
        rows = [
            TangoRawRow(name="B", name_background=None, week_text="14.07 — 02:00", week_text_format_runs=None),
        ]
        assert build_tomorrow_schedule(rows, "14.07", "15.07") == []

    def test_day_and_its_tail_ordered_correctly(self):
        rows = [
            TangoRawRow(name="A", name_background=None, week_text="14.07 — 20:00", week_text_format_runs=None),
            TangoRawRow(name="C", name_background=None, week_text="15.07 — 03:00", week_text_format_runs=None),
        ]
        result = build_tomorrow_schedule(rows, "14.07", "15.07")
        assert [(e.model_name, e.time) for e in result] == [("A", "20:00"), ("C", "03:00")]

    def test_daily_recurring_early_slot_shows_once_not_twice(self):
        # g_grace-style: same model streams at 01:00 every single date. The 14.07 entry
        # belongs to 13.07's list; only the 15.07 (day-after) entry belongs to 14.07's.
        rows = [
            TangoRawRow(
                name="Танго 23",
                name_background=None,
                week_text="13.07 — 01:00\n14.07 — 01:00\n15.07 — 01:00\n16.07 — 01:00",
                week_text_format_runs=None,
            )
        ]
        result = build_tomorrow_schedule(rows, "14.07", "15.07")
        assert len(result) == 1
        assert result[0].time == "01:00"

    def test_url_carried_through_to_entry(self):
        rows = [
            TangoRawRow(
                name="Танго 1",
                name_background=None,
                week_text="14.07 — 20:00",
                week_text_format_runs=None,
                url="https://www.tango.me/miaacarter",
            )
        ]
        result = build_tomorrow_schedule(rows, "14.07")
        assert result[0].url == "https://www.tango.me/miaacarter"

    def test_missing_url_defaults_to_empty(self):
        rows = [
            TangoRawRow(name="Танго 1", name_background=None, week_text="14.07 — 20:00", week_text_format_runs=None)
        ]
        result = build_tomorrow_schedule(rows, "14.07")
        assert result[0].url == ""

    def test_multiple_models_multiple_entries(self):
        rows = [
            TangoRawRow(
                name="Танго 1",
                name_background=None,
                week_text="13.07 — 20:00\n14.07 — 20:00\n15.07 — 20:00",
                week_text_format_runs=None,
            ),
            TangoRawRow(
                name="Ханами",
                name_background=None,
                week_text="14.07 — 12:00\n15.07 — 12:00",
                week_text_format_runs=None,
            ),
        ]
        result = build_tomorrow_schedule(rows, "14.07")
        assert [(e.model_name, e.time) for e in result] == [("Ханами", "12:00"), ("Танго 1", "20:00")]
