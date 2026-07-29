"""Tests for app/services/salary_sheet_writer.py."""
from app.services.salary_report import ModelSalaryRow
from app.services.salary_sheet_writer import (
    build_new_tab_grid,
    index_existing_tab,
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


class TestPlanUpdatesForExistingTab:
    def test_matched_model_gets_bf_and_k_range_updates(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["ФИГУРА", "new", "—", "—", "—", "—"],
            [],
        ]
        report = {"Рони": [_row("ФИГУРА", "Рони", status="work", total_files=80, orders_pay=3)]}
        updates, unmatched = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert unmatched == []
        ranges = dict(updates)
        assert ranges["'ИЮЛЬ'!B3:F3"] == [["work", "—", 80, "—", "—"]]
        assert ranges["'ИЮЛЬ'!K3"] == [[3]]

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
        updates, unmatched = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert unmatched == []
        assert dict(updates)["'ИЮЛЬ'!B3:F3"][0][0] == "work"

    def test_model_not_found_in_sheet_is_reported_unmatched(self):
        grid = [["Модель", "Статус"], ["Рони"], []]
        report = {"Рони": [_row("НОВИЧОК", "Рони")]}
        updates, unmatched = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        assert updates == []
        assert len(unmatched) == 1
        assert unmatched[0].model_name == "НОВИЧОК"

    def test_manual_columns_never_touched(self):
        grid = [
            ["Модель", "Статус"],
            ["Рони", "", "", "", "", "", "", "", "", "", "", "=SUM(I3:K3)"],
            ["ФИГУРА", "new"],
            [],
        ]
        report = {"Рони": [_row("ФИГУРА", "Рони")]}
        updates, _ = plan_updates_for_existing_tab(grid, report, "ИЮЛЬ")
        touched_ranges = [r for r, _ in updates]
        for r in touched_ranges:
            assert "!G" not in r and "!H" not in r and "!I" not in r
            assert "!J" not in r and "!L" not in r
