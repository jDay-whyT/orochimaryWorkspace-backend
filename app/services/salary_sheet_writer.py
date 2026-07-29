"""Writes a monthly salary report (see app.services.salary_report) into the
salary Google Sheet, matching the existing hand-built layout: one tab per
month (e.g. "ИЮЛЬ"), models grouped under a manager header row whose "Оплата"
column holds a `=SUM(I{first}:K{last})` formula over that manager's block.

Only the columns pulled from Notion (Статус, Контент, Total files, Custom,
Другие, Заказы) are ever written. Расходы/Lord/Managers/Оплата stay manual.

If the month's tab doesn't exist yet, the whole tab is built fresh in one
batch (safe — nothing pre-existing to corrupt). If it already exists, only
cells for models found in the sheet are updated in place; models present in
the report but not found as an existing row are returned as `unmatched` for
manual placement rather than risking an automatic row insertion that could
misalign a manager's SUM range on a live payroll sheet.
"""

from dataclasses import dataclass

from app.services.salary_report import ModelSalaryRow
from app.services.sheets import SheetsClient
from app.utils.formatting import MONTHS_RU

HEADER_ROW = [
    "Модель", "Статус", "Контент", "Total files", "Custom",
    "Другие (short/call/verif)", "Расходы", "", "Lord", "Managers",
    "Заказы", "Оплата",
]


def tab_title_for_month(yyyy_mm: str) -> str:
    month_idx = int(yyyy_mm[5:7]) - 1
    return MONTHS_RU[month_idx].upper()


def _content_cell(content: list[str]) -> str:
    return ", ".join(content) if content else "—"


def _count_cell(value: int) -> str | int:
    return value if value else "—"


def _model_row_cells(row: ModelSalaryRow) -> list:
    return [
        row.model_name,
        row.status or "",
        _content_cell(row.content),
        _count_cell(row.total_files),
        _count_cell(row.custom_count),
        _count_cell(row.other_count),
        "",  # Расходы — manual
        "",  # (unnamed spacer column)
        "",  # Lord — manual
        "",  # Managers — manual
        row.orders_pay if row.orders_pay else "",
        "",  # Оплата — manual/formula, only set on manager rows
    ]


def build_new_tab_grid(report: dict[str, list[ModelSalaryRow]]) -> list[list]:
    """Build the full A1:L{n} grid for a brand-new month tab."""
    grid: list[list] = [HEADER_ROW]
    manager_header_rows: list[int] = []

    for manager, rows in report.items():
        header_row_num = len(grid) + 1  # 1-based sheet row
        first_model_row = header_row_num + 1
        last_model_row = first_model_row + len(rows) - 1
        grid.append([manager] + [""] * 10 + [f"=SUM(I{first_model_row}:K{last_model_row})"])
        manager_header_rows.append(header_row_num)
        for row in rows:
            grid.append(_model_row_cells(row))
        grid.append([])  # blank separator between manager blocks

    total_formula = "=SUM(" + ",".join(f"L{n}" for n in manager_header_rows) + ")"
    grid.append([""] * 11 + [total_formula])
    return grid


@dataclass
class ExistingTabIndex:
    """model_name(lower) -> 1-based sheet row, scoped per manager block."""
    rows_by_manager: dict[str, dict[str, int]]


def index_existing_tab(grid: list[list]) -> ExistingTabIndex:
    rows_by_manager: dict[str, dict[str, int]] = {}
    current_manager: str | None = None

    for i, row in enumerate(grid):
        row_num = i + 1  # 1-based
        if row_num == 1:
            continue  # header
        if not row or not (row[0] or "").strip():
            current_manager = None
            continue
        is_manager_row = len(row) < 2 or not (row[1] or "").strip()
        if is_manager_row:
            current_manager = row[0].strip()
            rows_by_manager.setdefault(current_manager, {})
            continue
        if current_manager is not None:
            rows_by_manager[current_manager][row[0].strip().lower()] = row_num

    return ExistingTabIndex(rows_by_manager=rows_by_manager)


def plan_updates_for_existing_tab(
    grid: list[list],
    report: dict[str, list[ModelSalaryRow]],
    tab_name: str,
) -> tuple[list[tuple[str, list[list]]], list[ModelSalaryRow]]:
    """
    Return (cell updates, unmatched rows) for an already-existing tab.

    Each matched model gets two range updates: B:F (Статус..Другие) and K
    (Заказы) — deliberately skipping G:J (Расходы/spacer/Lord/Managers) and L
    (Оплата), which stay manual/formula-owned.
    """
    index = index_existing_tab(grid)
    # Manager block lookup is case-insensitive: report managers are
    # Title-cased from Notion's scoutname, but existing tabs may spell
    # a manager's header row differently (e.g. "FLAIR" vs "Flair").
    by_manager_lower = {name.lower(): rows for name, rows in index.rows_by_manager.items()}
    updates: list[tuple[str, list[list]]] = []
    unmatched: list[ModelSalaryRow] = []

    for manager, rows in report.items():
        model_rows = by_manager_lower.get(manager.lower(), {})
        for row in rows:
            row_num = model_rows.get(row.model_name.strip().lower())
            if row_num is None:
                unmatched.append(row)
                continue
            cells = _model_row_cells(row)
            updates.append((f"'{tab_name}'!B{row_num}:F{row_num}", [cells[1:6]]))
            updates.append((f"'{tab_name}'!K{row_num}", [[cells[10]]]))

    return updates, unmatched


@dataclass
class SalarySheetWriteResult:
    tab_name: str
    created_new_tab: bool
    updated_count: int
    unmatched: list[ModelSalaryRow]


async def write_salary_report(
    sheets: SheetsClient,
    spreadsheet_id: str,
    yyyy_mm: str,
    report: dict[str, list[ModelSalaryRow]],
) -> SalarySheetWriteResult:
    tab_name = tab_title_for_month(yyyy_mm)
    tabs = await sheets.get_sheet_tabs(spreadsheet_id)

    if tab_name not in tabs:
        await sheets.add_sheet_tab(spreadsheet_id, tab_name)
        grid = build_new_tab_grid(report)
        last_row = len(grid)
        await sheets.update_values(spreadsheet_id, [(f"'{tab_name}'!A1:L{last_row}", grid)])
        total_models = sum(len(rows) for rows in report.values())
        return SalarySheetWriteResult(
            tab_name=tab_name, created_new_tab=True,
            updated_count=total_models, unmatched=[],
        )

    grid = await sheets.get_tab_grid(spreadsheet_id, tab_name)
    updates, unmatched = plan_updates_for_existing_tab(grid, report, tab_name)
    await sheets.update_values(spreadsheet_id, updates)
    matched_count = sum(len(rows) for rows in report.values()) - len(unmatched)
    return SalarySheetWriteResult(
        tab_name=tab_name, created_new_tab=False,
        updated_count=matched_count, unmatched=unmatched,
    )
