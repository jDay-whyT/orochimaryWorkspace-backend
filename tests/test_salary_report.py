"""Tests for salary report aggregation: app/services/salary_report.py."""
from app.services.notion import NotionAccounting, NotionModel, NotionOrder
from app.services.salary_report import (
    UNASSIGNED_MANAGER,
    build_salary_report,
    normalize_manager_name,
)


def _model(page_id, title, scoutname=None):
    return NotionModel(page_id=page_id, title=title, scoutname=scoutname)


def _accounting(model_id, title, status="work", files=0, content=None):
    return NotionAccounting(
        page_id=f"acc-{model_id}", title=title, model_id=model_id,
        files=files, status=status, content=content or [],
    )


def _order(model_id, order_type, count=1, pay=0):
    return NotionOrder(
        page_id=f"order-{model_id}-{order_type}-{count}-{pay}",
        title="x", model_id=model_id, order_type=order_type, count=count, pay=pay,
    )


class TestNormalizeManagerName:
    def test_known_alias_normalizes_to_display_name(self):
        assert normalize_manager_name("рони") == "Рони"
        assert normalize_manager_name("МАСОНОВ") == "Артем Массонов"
        assert normalize_manager_name("принц") == "Prince"

    def test_unknown_value_passed_through_stripped(self):
        assert normalize_manager_name("  какой-то ник  ") == "какой-то ник"

    def test_empty_or_none_becomes_unassigned(self):
        assert normalize_manager_name(None) == UNASSIGNED_MANAGER
        assert normalize_manager_name("   ") == UNASSIGNED_MANAGER


class TestBuildSalaryReport:
    def test_custom_and_other_counts_split_correctly(self):
        models = [_model("m1", "КУБАЛИБРА", "калибра")]
        accounting = [_accounting("m1", "КУБАЛИБРА июль 2026", files=500)]
        orders = [
            _order("m1", "custom", count=1, pay=2),
            _order("m1", "custom", count=1, pay=1),
            _order("m1", "short", count=18, pay=0),
            _order("m1", "verif reddit", count=15, pay=2),
        ]
        report = build_salary_report(accounting, orders, models)
        row = report["Калибра"][0]
        assert row.custom_count == 2
        assert row.other_count == 33  # 18 + 15
        assert row.orders_pay == 5  # 2 + 1 + 0 + 2
        assert row.total_files == 500

    def test_model_with_stop_status_excluded(self):
        models = [_model("m1", "ШАНХАЙ", "вангог")]
        accounting = [_accounting("m1", "ШАНХАЙ июль 2026", status="stop")]
        report = build_salary_report(accounting, [], models)
        assert report == {}

    def test_model_with_no_orders_has_zero_counts(self):
        models = [_model("m1", "СОЛО", "ева")]
        accounting = [_accounting("m1", "СОЛО июль 2026", files=42)]
        report = build_salary_report(accounting, [], models)
        row = report["Ева"][0]
        assert row.custom_count == 0
        assert row.other_count == 0
        assert row.orders_pay == 0
        assert row.total_files == 42

    def test_missing_model_lookup_falls_back_to_unassigned_and_accounting_title(self):
        accounting = [_accounting("missing-id", "ФАНТОМ июль 2026")]
        report = build_salary_report(accounting, [], models=[])
        assert UNASSIGNED_MANAGER in report
        assert report[UNASSIGNED_MANAGER][0].model_name == "ФАНТОМ июль 2026"

    def test_groups_multiple_models_under_same_manager_sorted_by_name(self):
        models = [
            _model("m1", "ЗАЙЧИК", "бармалей"),
            _model("m2", "АНЧЕЛОТТИ", "бармалей"),
        ]
        accounting = [
            _accounting("m1", "ЗАЙЧИК июль 2026"),
            _accounting("m2", "АНЧЕЛОТТИ июль 2026"),
        ]
        report = build_salary_report(accounting, [], models)
        names = [r.model_name for r in report["Бармалей"]]
        assert names == ["АНЧЕЛОТТИ", "ЗАЙЧИК"]

    def test_accounting_record_without_model_id_is_skipped(self):
        accounting = [_accounting(None, "СИРОТА июль 2026")]
        report = build_salary_report(accounting, [], models=[])
        assert report == {}
