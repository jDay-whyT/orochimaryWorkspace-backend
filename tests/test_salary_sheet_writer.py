"""Tests for app/services/salary_sheet_writer.py."""
import pytest

from app.services.salary_report import ModelSalaryRow
from app.services.salary_sheet_writer import (
    build_new_tab_grid,
    find_manager_block,
    index_existing_tab,
    insert_new_model_row,
    plan_row_insertion,
    plan_updates_for_existing_tab,
    tab_title_for_month,
)


def _row(model_name, manager, status="work", content=None, total_files=0,
         custom_count=0, other_count=0, orders_pay=0):
    return ModelSalaryRow(
        model_id=f"id-{model_name}", model_name=model_name, manager=manager,
        status=status, content=content or [], total_files=total_files,
        custom_count=custom_count, other_count=other_count, orders_pay=orders_pay,
    )


class TestTabTitleForMonth:
    def test_july_maps_to_uppercase_russian_name(self):
        assert tab_title_for_month("2026-07") == "ИЮЛЬ"

    def test_january_maps_correctly(self):
        assert tab_title_for_month("2026-01") == "ЯНВАРЬ"


class TestBuildNewTabGrid:
    def test_header_row_matches_existing_sheet_layout(self):
        grid = build_new_tab_grid({})
        assert grid[0] == [
            "Модель", "Статус", "Контент", "Total files", "Custom",
            "Другие (short/call/verif)", "Расходы", "", "Lord", "Managers",
            "Заказы", "Оплата",
        ]

    def test_manager_formula_range_covers_exactly_its_models(self):
        report = {
            "Рони": [_row("А", "Рони"), _row("Б", "Рони"), _row("В", "Рони")],
        }
        grid = build_new_tab_grid(report)
        # row1=header, row2=manager, rows3-5=models
        assert grid[1][0] == "Рони"
        assert grid[1][-1] == "=SUM(I3:K5)"
        assert grid[2][0] == "А"
        assert grid[4][0] == "В"

    def test_two_manager_blocks_separated_by_blank_row(self):
        report = {
            "Рони": [_row("А", "Рони")],
            "Вангог": [_row("Б", "Вангог")],
        }
        grid = build_new_tab_grid(report)
        # header, Рони header, А, blank, Вангог header, Б, blank, grand total
        assert grid[3] == []
        assert grid[1][-1] == "=SUM(I3:K3)"
        assert grid[4][-1] == "=SUM(I6:K6)"

    def test_grand_total_sums_every_manager_header_l_cell(self):
        report = {
            "Рони": [_row("А", "Рони")],
            "Вангог": [_row("Б", "Вангог")],
        }
        grid = build_new_tab_grid(report)
        assert grid[-1][-1] == "=SUM(L2,L5)"

    def test_zero_counts_render_as_dash_but_pay_stays_blank(self):
        report = {"Ева": [_row("СОЛО", "Ева")]}
        grid = build_new_tab_grid(report)
        model_row = grid[2]
        assert model_row[3] == "—"  # Total files
        assert model_row[4] == "—"  # Custom
        assert model_row[5] == "—"  # Другие
        assert model_row[10] == ""  # Заказы (0 -> blank, not "0")


class TestIndexExistingTab:
    def test_finds_model_row_under_correct_manager(self):
        grid = [
            ["Модель", "Статус", "Контент", "Total files", "Custom", "Другие", "", "", "", "", "", "Оплата"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["ФИГУРА", "work", "reddit", 80, "—", "—", "", "", 20, 20],
            [],
        ]
        index = index_existing_tab(grid)
        assert index.rows_by_manager["Рони"]["фигура"] == 3

    def test_blank_row_resets_current_manager(self):
        grid = [
            ["Модель"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["ФИГУРА", "work"],
            [],
            ["АНОЛИ", "work"],  # orphaned model row after blank, no manager
        ]
        index = index_existing_tab(grid)
        assert "аноли" not in index.rows_by_manager.get("Рони", {})
        assert not any("аноли" in models for models in index.rows_by_manager.values())

    def test_split_model_row_gets_bare_name_alias(self):
        """A co-owned model split between two managers is hand-suffixed
        "  0.5" on its sheet row (e.g. "КОНАН  0.5") — Notion's report has no
        such marker, so the bare name must also resolve to that row."""
        grid = [
            ["Модель"],
            ["Какаси", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["КОНАН  0.5", "work"],
            [],
        ]
        index = index_existing_tab(grid)
        assert index.rows_by_manager["Какаси"]["конан  0.5"] == 3
        assert index.rows_by_manager["Какаси"]["конан"] == 3

    def test_split_alias_never_overwrites_a_real_distinct_model(self):
        """If a manager somehow has both "конан" and "конан  0.5" as real,
        separate rows, the bare-name alias must not clobber the real row."""
        grid = [
            ["Модель"],
            ["Какаси", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K4)"],
            ["КОНАН", "work"],
            ["КОНАН  0.5", "work"],
            [],
        ]
        index = index_existing_tab(grid)
        assert index.rows_by_manager["Какаси"]["конан"] == 3
        assert index.rows_by_manager["Какаси"]["конан  0.5"] == 4


class TestPlanUpdatesForExistingTab:
    def test_matched_model_gets_bf_and_k_range_updates(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["ФИГУРА", "new", "—", "—", "—", "—"],
            [],
        ]
        report = {"Рони": [_row("ФИГУРА", "Рони", status="work", total_files=80, orders_pay=3)]}
        updates, unmatched, unmatched_no_manager = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert unmatched == []
        assert unmatched_no_manager == []
        ranges = dict(updates)
        assert ranges["'ИЮЛЬ'!B3:F3"] == [["work", "—", 80, "—", "—"]]
        assert ranges["'ИЮЛЬ'!K3"] == [[3]]

    def test_split_model_bare_name_matches_its_0_5_suffixed_row(self):
        """КОНАН/ЖИВЧИК-style co-owned models: report has the bare name,
        sheet row is hand-suffixed "  0.5" — must match, not fall to unmatched."""
        grid = [
            ["Модель", "Статус"],
            ["Какаси", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["КОНАН  0.5", "new", "—", "—", "—", "—"],
            [],
        ]
        report = {"Какаси": [_row("КОНАН", "Какаси", status="work", total_files=40)]}
        updates, unmatched, unmatched_no_manager = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert unmatched == []
        assert unmatched_no_manager == []
        assert dict(updates)["'ИЮЛЬ'!B3:F3"][0][0] == "work"

    def test_manager_block_lookup_is_case_insensitive(self):
        """Sheet has 'FLAIR' as the manager header, report groups as 'Flair'
        (Title-cased scoutname) — must still match (Jul 29 prod incident)."""
        grid = [
            ["Модель", "Статус"],
            ["FLAIR", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["Maria Kai", "work"],
            [],
        ]
        report = {"Flair": [_row("Maria Kai", "Flair", status="work")]}
        updates, unmatched, unmatched_no_manager = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert unmatched == []
        assert unmatched_no_manager == []
        assert dict(updates)["'ИЮЛЬ'!B3:F3"][0][0] == "work"

    def test_model_not_found_but_manager_exists_is_button_eligible_unmatched(self):
        grid = [["Модель", "Статус"], ["Рони"], []]
        report = {"Рони": [_row("НОВИЧОК", "Рони")]}
        updates, unmatched, unmatched_no_manager = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert updates == []
        assert unmatched_no_manager == []
        assert len(unmatched) == 1
        assert unmatched[0].model_name == "НОВИЧОК"

    def test_manager_not_in_sheet_is_unmatched_no_manager(self):
        grid = [["Модель", "Статус"], ["Рони"], []]
        report = {"НовыйМенеджер": [_row("НОВИЧОК", "НовыйМенеджер")]}
        updates, unmatched, unmatched_no_manager = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert updates == []
        assert unmatched == []
        assert len(unmatched_no_manager) == 1
        assert unmatched_no_manager[0].model_name == "НОВИЧОК"

    def test_manual_columns_never_touched(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["ФИГУРА", "new"],
            [],
        ]
        report = {"Рони": [_row("ФИГУРА", "Рони")]}
        updates, _, _ = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        touched_ranges = [r for r, _ in updates]
        for r in touched_ranges:
            assert "!G" not in r and "!H" not in r and "!I" not in r
            assert "!J" not in r and "!L" not in r


class TestFindManagerBlock:
    def test_finds_header_and_last_row_mid_sheet(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K4)"],
            ["А", "work"],
            ["Б", "work"],
            [],
            ["Вангог", "", "", "", "", "", "", "", "", "", "", "=SUM(I7:K7)"],
            ["В", "work"],
            [],
        ]
        pos = find_manager_block(grid, "рони")
        assert pos.header_row == 2
        assert pos.last_row == 4

    def test_last_block_in_sheet_with_no_trailing_blank(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["А", "work"],
        ]
        pos = find_manager_block(grid, "Рони")
        assert pos.header_row == 2
        assert pos.last_row == 3

    def test_manager_block_with_zero_models(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", ""],
            [],
        ]
        pos = find_manager_block(grid, "Рони")
        assert pos.header_row == 2
        assert pos.last_row == 2

    def test_unknown_manager_returns_none(self):
        grid = [["Модель", "Статус"], ["Рони"], []]
        assert find_manager_block(grid, "НетТакого") is None


class TestPlanRowInsertion:
    def test_inserts_right_after_last_model_row(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K4)"],
            ["А", "work"],
            ["Б", "work"],
            [],
        ]
        plan = plan_row_insertion(grid, "Рони")
        assert plan.insert_at_row == 4  # 0-based: right after 1-based row 4
        assert plan.new_row_num == 5
        assert plan.header_row == 2

    def test_unknown_manager_returns_none(self):
        grid = [["Модель", "Статус"], ["Рони"], []]
        assert plan_row_insertion(grid, "НетТакого") is None


class FakeSheetsClient:
    def __init__(self):
        self.inserted = None
        self.updates = []

    async def insert_rows(self, spreadsheet_id, sheet_id, start_index, end_index):
        self.inserted = (spreadsheet_id, sheet_id, start_index, end_index)

    async def update_values(self, spreadsheet_id, updates):
        self.updates.append((spreadsheet_id, updates))


class TestInsertNewModelRow:
    @pytest.mark.asyncio
    async def test_inserts_row_without_touching_manager_formula(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["А", "work"],
            [],
        ]
        sheets = FakeSheetsClient()
        row = _row("НОВИЧОК", "Рони", status="work", total_files=10, orders_pay=5)
        new_row = await insert_new_model_row(sheets, "ssid", "ИЮЛЬ", 999, grid, "Рони", row)

        assert new_row == 4
        assert sheets.inserted == ("ssid", 999, 3, 4)
        ranges = dict(sheets.updates[0][1])
        assert ranges["'ИЮЛЬ'!A4:L4"][0][0] == "НОВИЧОК"
        assert "'ИЮЛЬ'!L2" not in ranges  # manager's SUM formula left untouched

    @pytest.mark.asyncio
    async def test_unknown_manager_returns_none_without_calling_sheets(self):
        grid = [["Модель", "Статус"], ["Рони"], []]
        sheets = FakeSheetsClient()
        row = _row("НОВИЧОК", "НетТакого")
        result = await insert_new_model_row(sheets, "ssid", "ИЮЛЬ", 999, grid, "НетТакого", row)
        assert result is None
        assert sheets.inserted is None
        assert sheets.updates == []
