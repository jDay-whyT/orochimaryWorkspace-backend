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

import re
from dataclasses import dataclass, field

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
class ManagerBlockPosition:
    """Where an existing manager's block sits in a tab's grid (1-based rows)."""
    header_row: int
    last_row: int  # last existing model row; == header_row if block has no models yet


def find_manager_block(grid: list[list], manager: str) -> ManagerBlockPosition | None:
    """
    Locate a manager's header row and last model row in an existing tab, so a
    new model row can be inserted right after the block instead of appended
    to the wrong place. Manager-block boundaries are detected the same way
    as `index_existing_tab` (empty column A ends a block; empty column B on a
    non-empty column A starts a new manager header).
    """
    manager_lower = manager.strip().lower()
    current_manager: str | None = None
    header_row: int | None = None
    last_row: int | None = None

    def _match() -> ManagerBlockPosition | None:
        if current_manager is not None and current_manager.lower() == manager_lower and header_row is not None:
            return ManagerBlockPosition(header_row=header_row, last_row=last_row or header_row)
        return None

    for i, row in enumerate(grid):
        row_num = i + 1
        if row_num == 1:
            continue  # header
        if not row or not (row[0] or "").strip():
            found = _match()
            if found:
                return found
            current_manager, header_row, last_row = None, None, None
            continue
        is_manager_row = len(row) < 2 or not (row[1] or "").strip()
        if is_manager_row:
            found = _match()
            if found:
                return found
            current_manager, header_row, last_row = row[0].strip(), row_num, None
            continue
        last_row = row_num

    return _match()


@dataclass
class RowInsertionPlan:
    """0-based `insert_at_row` for SheetsClient.insert_rows, plus the 1-based
    row the new model row lands on. The manager's Оплата/SUM formula is
    deliberately left untouched — user updates that range by hand after an
    insert, same as Расходы/Lord/Managers (see insert_new_model_row)."""
    insert_at_row: int
    new_row_num: int
    header_row: int


def plan_row_insertion(grid: list[list], manager: str) -> RowInsertionPlan | None:
    """Return None if the manager's block doesn't exist in the tab at all —
    caller should fall back to reporting the row as 'add manually'."""
    pos = find_manager_block(grid, manager)
    if pos is None:
        return None
    return RowInsertionPlan(
        insert_at_row=pos.last_row,  # 0-based index == 1-based last_row: inserts right after it
        new_row_num=pos.last_row + 1,
        header_row=pos.header_row,
    )


@dataclass
class ExistingTabIndex:
    """model_name(lower) -> 1-based sheet row, scoped per manager block."""
    rows_by_manager: dict[str, dict[str, int]]


_SPLIT_SUFFIX_RE = re.compile(r"\s+0\.5\s*$")


def _strip_split_suffix(name: str) -> str:
    """Co-owned models get a hand-added ' 0.5' suffix on their sheet row
    (e.g. "КОНАН  0.5") when split between two managers at half rate each —
    Notion's Accounting has no such marker, so the report's model_name is
    always the bare name. Stripped only for a fallback lookup key, never
    replacing the raw row key."""
    return _SPLIT_SUFFIX_RE.sub("", name).strip().lower()


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
            key = row[0].strip().lower()
            rows_by_manager[current_manager][key] = row_num
            stripped = _strip_split_suffix(row[0])
            if stripped != key:
                # Fallback alias only — never overwrites a real distinct model
                # that happens to already occupy the stripped name.
                rows_by_manager[current_manager].setdefault(stripped, row_num)

    return ExistingTabIndex(rows_by_manager=rows_by_manager)


def plan_updates_for_existing_tab(
    grid: list[list],
    report: dict[str, list[ModelSalaryRow]],
    tab_name: str,
) -> tuple[list[tuple[str, list[list]]], list[ModelSalaryRow], list[ModelSalaryRow]]:
    """
    Return (cell updates, unmatched, unmatched_no_manager) for an already-existing tab.

    Each matched model gets two range updates: B:F (Статус..Другие) and K
    (Заказы) — deliberately skipping G:J (Расходы/spacer/Lord/Managers) and L
    (Оплата), which stay manual/formula-owned.

    `unmatched` rows have a manager block in the tab but no matching model
    row — these can be auto-inserted via plan_row_insertion/insert_new_model_row.
    `unmatched_no_manager` rows' manager block doesn't exist in the tab at
    all (new manager) — always reported as "add manually", never auto-inserted.
    """
    index = index_existing_tab(grid)
    # Manager block lookup is case-insensitive: report managers are
    # Title-cased from Notion's scoutname, but existing tabs may spell
    # a manager's header row differently (e.g. "FLAIR" vs "Flair").
    by_manager_lower = {name.lower(): rows for name, rows in index.rows_by_manager.items()}
    updates: list[tuple[str, list[list]]] = []
    unmatched: list[ModelSalaryRow] = []
    unmatched_no_manager: list[ModelSalaryRow] = []

    for manager, rows in report.items():
        manager_exists = manager.lower() in by_manager_lower
        model_rows = by_manager_lower.get(manager.lower(), {})
        for row in rows:
            row_num = model_rows.get(row.model_name.strip().lower())
            if row_num is None:
                (unmatched if manager_exists else unmatched_no_manager).append(row)
                continue
            cells = _model_row_cells(row)
            updates.append((f"'{tab_name}'!B{row_num}:F{row_num}", [cells[1:6]]))
            updates.append((f"'{tab_name}'!K{row_num}", [[cells[10]]]))

    return updates, unmatched, unmatched_no_manager


@dataclass
class SalarySheetWriteResult:
    tab_name: str
    created_new_tab: bool
    updated_count: int
    unmatched: list[ModelSalaryRow]
    unmatched_no_manager: list[ModelSalaryRow] = field(default_factory=list)


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
    updates, unmatched, unmatched_no_manager = plan_updates_for_existing_tab(grid, report, tab_name)
    await sheets.update_values(spreadsheet_id, updates)
    matched_count = sum(len(rows) for rows in report.values()) - len(unmatched) - len(unmatched_no_manager)
    return SalarySheetWriteResult(
        tab_name=tab_name, created_new_tab=False,
        updated_count=matched_count, unmatched=unmatched,
        unmatched_no_manager=unmatched_no_manager,
    )


async def insert_new_model_row(
    sheets: SheetsClient,
    spreadsheet_id: str,
    tab_name: str,
    sheet_id: int,
    grid: list[list],
    manager: str,
    row: ModelSalaryRow,
) -> int | None:
    """
    Insert one new model row right after `manager`'s existing block in an
    already-existing tab. Returns the 1-based row the model landed on, or
    None if the manager has no block in this tab (caller should tell the
    user to add manually — never guessed/auto-created, see
    [[project_reports_feature]] on the risk of misaligning a manager's SUM
    range on a live payroll sheet).

    Row insertion (not a plain cell overwrite) is what keeps every other
    manager's rows below the insertion point correctly shifted — a native
    Sheets guarantee for structural inserts. The manager's own Оплата/SUM
    formula is deliberately left untouched (not auto-extended to cover the
    new row) — user explicitly wants formula/money columns hand-edited only,
    same as Расходы/Lord/Managers elsewhere in this writer. Caller should
    tell the user the manager's SUM range needs a manual bump.
    """
    plan = plan_row_insertion(grid, manager)
    if plan is None:
        return None

    await sheets.insert_rows(spreadsheet_id, sheet_id, plan.insert_at_row, plan.insert_at_row + 1)
    cells = _model_row_cells(row)
    await sheets.update_values(
        spreadsheet_id, [(f"'{tab_name}'!A{plan.new_row_num}:L{plan.new_row_num}", [cells])],
    )
    return plan.new_row_num
