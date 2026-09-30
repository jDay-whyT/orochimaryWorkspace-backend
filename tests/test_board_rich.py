from datetime import date

from app.handlers.notifications import _format_board_rich
from app.services.notion import NotionPlanner


def _shoot(day: str, model: str, **kw) -> NotionPlanner:
    return NotionPlanner(page_id=day + model, title=model, model_title=model, date=day, **kw)


def test_empty_board():
    assert "нет" in _format_board_rich([], date(2026, 9, 30))


def test_today_and_tomorrow_open_rest_collapsed():
    shoots = [
        _shoot("2026-09-30", "A", status="Planned"),
        _shoot("2026-10-01", "B"),
        _shoot("2026-10-03", "C"),
    ]
    html = _format_board_rich(shoots, date(2026, 9, 30))
    assert html.count("<details open>") == 2
    assert html.count("<details>") == 1
    assert "(3 шт)" in html


def test_escapes_and_empty_cells():
    html = _format_board_rich(
        [_shoot("2026-09-30", "A<b>&", content=["x", "y"], location="R&D")], date(2026, 9, 30)
    )
    assert "A&lt;b&gt;&amp;" in html
    assert "x | y" in html and "R&amp;D" in html
    assert "<td>—</td>" in html


def test_bad_dates_skipped():
    assert "нет" in _format_board_rich([_shoot("garbage", "A")], date(2026, 9, 30))
