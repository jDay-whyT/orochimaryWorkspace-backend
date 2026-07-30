"""Unit tests for the Tango-annotation fallback matching in app/services/wml_sync.py."""
from app.services.wml_sync import _normalize_title, _tango_fallback_key


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
