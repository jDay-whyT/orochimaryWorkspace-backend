"""Monthly salary report — aggregates Accounting/Orders/Models into per-manager rows.

Accounting is the primary source of truth (one record per model per month);
Models is only an auxiliary lookup for the manager name (scoutname). Models
whose Accounting status for the month is "stop" are excluded entirely.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from app.services.notion import NotionAccounting, NotionModel, NotionOrder

UNASSIGNED_MANAGER = "Без менеджера"


def normalize_manager_name(scoutname: str | None) -> str:
    """
    Notion's `scoutname` select stores lowercase working nicknames
    (e.g. "рони", "массонов"); the salary sheet's manager header rows use
    the same word capitalized (e.g. "Рони", "Массонов") — so display name
    is just scoutname with its first letter capitalized. Manager-block
    matching against an existing tab is case-insensitive (see
    salary_sheet_writer), so this only needs to be consistent, not exact.
    """
    if not scoutname or not scoutname.strip():
        return UNASSIGNED_MANAGER
    return scoutname.strip().capitalize()


@dataclass
class ModelSalaryRow:
    """One model's row in the salary report for a given month."""
    model_id: str
    model_name: str
    manager: str
    status: str | None = None
    content: list[str] = field(default_factory=list)
    total_files: int = 0
    custom_count: int = 0
    other_count: int = 0
    orders_pay: int = 0


def salary_pending_redis_key(yyyy_mm: str, model_id: str) -> str:
    """Cache key for a single unmatched row's data between /reports sending
    its "Добавить в таблицу" button and the button being pressed — avoids
    re-running the full month's Accounting/Orders/Models Notion query (slow,
    ~90-250s observed in prod 2026-07-31) just to add one row."""
    return f"salary:pending:{yyyy_mm}:{model_id}"


def build_salary_report(
    accounting_records: list[NotionAccounting],
    orders: list[NotionOrder],
    models: list[NotionModel],
) -> dict[str, list[ModelSalaryRow]]:
    """
    Group monthly salary rows by manager.

    Returns a dict of manager display name -> rows, each list sorted by
    model name. Manager keys are also returned in sorted order via a
    regular dict (Python 3.7+ preserves insertion order; callers that need
    a specific key order should sort `.keys()` themselves).
    """
    models_by_id = {m.page_id: m for m in models}

    orders_by_model: dict[str, list[NotionOrder]] = defaultdict(list)
    for order in orders:
        if order.model_id:
            orders_by_model[order.model_id].append(order)

    by_manager: dict[str, list[ModelSalaryRow]] = defaultdict(list)
    for record in accounting_records:
        if not record.model_id:
            continue
        if (record.status or "").strip().lower() == "stop":
            continue

        model = models_by_id.get(record.model_id)
        manager = normalize_manager_name(model.scoutname if model else None)
        model_orders = orders_by_model.get(record.model_id, [])

        custom_count = sum(1 for o in model_orders if o.order_type == "custom")
        other_count = sum(
            (o.count or 0) for o in model_orders if o.order_type != "custom"
        )
        orders_pay = sum((o.pay or 0) for o in model_orders)

        content = record.content or []
        is_tango = bool(model and (model.project or "").strip().upper() == "TANGO")
        if not content and is_tango:
            content = ["Tango"]

        by_manager[manager].append(ModelSalaryRow(
            model_id=record.model_id,
            model_name=(model.title if model else record.title),
            manager=manager,
            status=record.status,
            content=content,
            total_files=record.files,
            custom_count=custom_count,
            other_count=other_count,
            orders_pay=orders_pay,
        ))

    for rows in by_manager.values():
        rows.sort(key=lambda r: r.model_name.lower())

    return dict(sorted(by_manager.items(), key=lambda kv: kv[0].lower()))
