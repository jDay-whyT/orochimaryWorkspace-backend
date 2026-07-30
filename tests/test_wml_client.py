"""Unit tests for app/services/wml_client.py parsing (no live WML access)."""
from app.services.wml_client import (
    parse_profile_detail,
    parse_statistics,
    strip_wml_suffix,
)


# ---------------------------------------------------------------------------
# strip_wml_suffix
# ---------------------------------------------------------------------------

def test_strip_wml_suffix_normal():
    assert strip_wml_suffix("ТАНГО 47_1134") == "ТАНГО 47"


def test_strip_wml_suffix_ii_excluded():
    assert strip_wml_suffix("ДАХ ИИ_1035") is None
    assert strip_wml_suffix("УМПА ИИ_1029") is None


def test_strip_wml_suffix_no_number():
    assert strip_wml_suffix("СОМЕNAME") == "СОМЕNAME"


def test_strip_wml_suffix_leading_paren_id():
    assert strip_wml_suffix("(2119) СУКУНА") == "СУКУНА"
    assert strip_wml_suffix("(2056) Black Pearl") == "Black Pearl"


# ---------------------------------------------------------------------------
# parse_statistics
# ---------------------------------------------------------------------------

def _grid_row(row_id: str, name: str, href: str, register: str, ref: str, scout: str,
              office: str, p1: str, p2: str, p3: str, fansly_col: str, tango: str) -> str:
    """Build one <tr> matching the real WML grid's data-col-seq layout
    (Model, Register, Ref, Scout, office, P1, P2, P3, Fansly, Tango, ...)."""
    cells = [name + f' <a href="{href}">&rarr;</a>', register, ref, scout, office, p1, p2, p3, fansly_col, tango]
    tds = "".join(
        f'<td class="w0" data-col-seq="{i}">{c}</td>' for i, c in enumerate(cells)
    )
    # pad remaining columns (Payment System .. Reddit) up to data-col-seq=16
    tds += "".join(f'<td class="w0" data-col-seq="{i}"></td>' for i in range(10, 17))
    return f'<tr id="tr{row_id}" class="row-no-done w0" data-key="{row_id}">{tds}</tr>'


def _grid_html(rows: str) -> str:
    return f'<div id="w0" class="grid-view is-bs4"><table><tbody>{rows}</tbody></table></div>'


def test_parse_statistics_basic_row():
    html = _grid_html(_grid_row(
        "1134", "ТАНГО 47_1134", "/profile/1134", "25.07.2026", "", "ДНЕПР",
        "", "21.07.2026", "", "", "", "26.07.2026",
    ))
    profiles = parse_statistics(html)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.wml_id == "1134"
    assert p.wml_name == "ТАНГО 47_1134"
    assert p.name == "ТАНГО 47"
    assert p.profile_url == "https://wml.pp.ua/profile/1134"
    assert p.scout == "ДНЕПР"
    assert p.fansly_date is None  # fansly column (index 8) left empty in this row


def test_parse_statistics_excludes_ii_profiles():
    rows = _grid_row(
        "1035", "ДАХ ИИ_1035", "/profile/1035", "12.06.2026", "", "",
        "", "", "", "", "", "12.06.2026",
    )
    html = _grid_html(rows)
    profiles = parse_statistics(html)
    assert profiles == []


def test_parse_statistics_fansly_date_column():
    # Fansly is data-col-seq=8; put a real value there via the fansly_col arg.
    row = _grid_row(
        "1029", "УМПА ИИ_1029", "/profile/1029", "03.06.2026", "", "",
        "", "", "", "", "28.07.2026", "",
    )
    # Rebuild manually without ИИ so this profile isn't excluded, to check the Fansly column itself.
    row_no_ii = row.replace("ИИ_1029", "_1029")
    html = _grid_html(row_no_ii)
    profiles = parse_statistics(html)
    assert len(profiles) == 1
    assert profiles[0].fansly_date == "28.07.2026"


# ---------------------------------------------------------------------------
# parse_profile_detail
# ---------------------------------------------------------------------------

def _detail_html() -> str:
    def block(label: str, value: str) -> str:
        return f"<div>{label}:</div><div>{value}</div>"

    return (
        "<html><body>"
        + block("Name", "TAXO_1135")
        + block("Offices", "")
        + block("Scout", "Бармалей")
        + block("Location", "Argentina , Rosario")
        + block("Language", "eng, esp")
        + block("Comments", "Сейчас только оф, через недели 2/3 танго старт")
        + block("TG Content Manager", "@orochimary")
        + '<a href="https://t.me/OnlyDakaria">OnlyDakaria</a>'
        + "</body></html>"
    )


def test_parse_profile_detail():
    detail = parse_profile_detail(_detail_html())
    assert detail.wml_name == "TAXO_1135"
    assert detail.scout == "Бармалей"
    assert detail.location == "Argentina"
    assert detail.language == "eng, esp"
    assert detail.tg_content_manager == "@orochimary"
    assert detail.model_telegram == "@OnlyDakaria"


def test_parse_profile_detail_telegram_already_has_at():
    html = '<html><body><a href="https://t.me/foo">@foo</a></body></html>'
    detail = parse_profile_detail(html)
    assert detail.model_telegram == "@foo"  # not double-prefixed


def test_parse_statistics_tango_date_column():
    row = _grid_row(
        "1134", "ТАНГО 47_1134", "/profile/1134", "25.07.2026", "", "ДНЕПР",
        "", "21.07.2026", "", "", "", "26.07.2026",
    )
    profiles = parse_statistics(_grid_html(row))
    assert profiles[0].tango_date == "26.07.2026"
