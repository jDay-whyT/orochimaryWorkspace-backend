"""Unit tests for the Tango-annotation fallback matching in app/services/wml_sync.py."""
from app.services.notion import NotionModel
from app.services.wml_sync import (
    _normalize_title,
    _tango_fallback_key,
    _tango_prefix_collapse_key,
    build_notion_title_index,
    resolve_wml_match,
)


def _model(title: str, page_id: str | None = None) -> NotionModel:
    return NotionModel(page_id=page_id or f"id-{title}", title=title)


def test_tango_suffix_concatenated():
    key = _normalize_title("ХанамиТанго")
    assert _tango_fallback_key(key) == "ханами"


def test_tango_suffix_spaced():
    key = _normalize_title("Смайл Танго")
    assert _tango_fallback_key(key) == "смайл"


def test_tango_slot_with_trailing_annotation():
    assert _tango_fallback_key(_normalize_title("Танго 26 ( сигма)")) == "танго 26"
    assert _tango_fallback_key(_normalize_title("Танго 16 (Бьякуя)")) == "танго 16"
    assert _tango_fallback_key(_normalize_title("Танго 40 John")) == "танго 40"


def test_no_tango_annotation_returns_none():
    assert _tango_fallback_key(_normalize_title("ГЕРЕРО")) is None
    assert _tango_fallback_key(_normalize_title("ТАНГО")) is None  # bare word, no slot number, no suffix


def test_tango_prefix_with_name_never_collapses_to_bare_name():
    """"Танго Кейптаун"/"ТангоКейптаун" is its own persistent Notion page,
    distinct from bare "Кейптаун" — must NOT reduce to the bare name.
    Regression: an earlier version of this fix wrongly matched "Танго
    Кейптаун" to the unrelated bare "КЕЙПТАУН" page (caught live 2026-07-31,
    user confirmed these must stay two separate records)."""
    assert _tango_fallback_key(_normalize_title("Танго Кейптаун")) is None
    assert _tango_fallback_key(_normalize_title("ТангоКейптаун")) is None


def test_tango_prefix_collapse_key_matches_spacing_variants_only():
    """The safe, narrow fix for the same case: only equates spaced vs
    concatenated forms of a Tango-prefixed name against EACH OTHER, never
    against the bare name (which doesn't start with "танго" at all)."""
    assert _tango_prefix_collapse_key(_normalize_title("Танго Кейптаун")) == "тангокейптаун"
    assert _tango_prefix_collapse_key(_normalize_title("ТангоКейптаун")) == "тангокейптаун"
    assert _tango_prefix_collapse_key(_normalize_title("Кейптаун")) is None  # bare name: no prefix
    assert _tango_prefix_collapse_key(_normalize_title("Танго 34 John")) is None  # slot form excluded


def test_tango_slot_note_differs_but_slot_number_is_shared_identity():
    """WML "Танго 34 John" vs Notion "Танго 34 ЕКБ" — different free-text
    notes for the same slot must still reduce to the same key."""
    assert _tango_fallback_key(_normalize_title("Танго 34 John")) == "танго 34"
    assert _tango_fallback_key(_normalize_title("Танго 34 ЕКБ")) == "танго 34"


class TestResolveWmlMatch:
    def test_exact_title_match(self):
        index = build_notion_title_index([_model("ГЕРЕРО")])
        model = resolve_wml_match(_normalize_title("ГЕРЕРО"), index)
        assert model is not None and model.title == "ГЕРЕРО"

    def test_notion_bare_wml_tango_annotated(self):
        """Existing behavior: Notion has the bare name, WML glues Tango on."""
        index = build_notion_title_index([_model("Хмель")])
        model = resolve_wml_match(_normalize_title("ХмельТанго"), index)
        assert model is not None and model.title == "Хмель"

    def test_notion_itself_tango_annotated_with_different_note_same_slot(self):
        """Prod bug fixed 2026-07-31: Notion "Танго 34 ЕКБ" vs WML "Танго 34
        John" — same slot, different free-text note on each side."""
        index = build_notion_title_index([_model("Танго 34 ЕКБ")])
        model = resolve_wml_match(_normalize_title("Танго 34 John"), index)
        assert model is not None and model.title == "Танго 34 ЕКБ"

    def test_tango_prefix_concatenated_vs_spaced(self):
        """Prod bug fixed 2026-07-31: Notion "ТангоКейптаун" (concatenated)
        vs WML "Танго Кейптаун" (spaced)."""
        index = build_notion_title_index([_model("ТангоКейптаун")])
        model = resolve_wml_match(_normalize_title("Танго Кейптаун"), index)
        assert model is not None and model.title == "ТангоКейптаун"

    def test_tango_prefixed_name_never_matches_unrelated_bare_model(self):
        """Regression caught live 2026-07-31: with BOTH "КЕЙПТАУН" (bare) and
        "ТангоКейптаун" existing as separate Notion pages, WML's "Танго
        Кейптаун" must resolve to the Tango page, never the bare one."""
        index = build_notion_title_index([_model("КЕЙПТАУН", "bare-id"), _model("ТангоКейптаун", "tango-id")])
        model = resolve_wml_match(_normalize_title("Танго Кейптаун"), index)
        assert model is not None and model.page_id == "tango-id"

        bare_model = resolve_wml_match(_normalize_title("КЕЙПТАУН"), index)
        assert bare_model is not None and bare_model.page_id == "bare-id"

    def test_ambiguous_raw_title_never_guessed(self):
        index = build_notion_title_index([_model("ФИГУРА", "id-1"), _model("ФИГУРА", "id-2")])
        assert resolve_wml_match(_normalize_title("ФИГУРА"), index) is None

    def test_ambiguous_tango_alias_never_guessed(self):
        """Two different Notion models both reduce to "танго 5" — must not
        pick either one."""
        index = build_notion_title_index([_model("Танго 5 Alice"), _model("Танго 5 Bob")])
        assert resolve_wml_match(_normalize_title("Танго 5 Carol"), index) is None

    def test_no_match_returns_none(self):
        index = build_notion_title_index([_model("ГЕРЕРО")])
        assert resolve_wml_match(_normalize_title("СОВЕРШЕННО НОВАЯ"), index) is None
