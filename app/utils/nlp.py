"""NLP utility functions for text parsing."""

import re
from typing import Optional
from datetime import date, timedelta
from app.utils.patterns import NUMBER_PATTERN, ORDER_TYPE_PATTERNS


def extract_first_number(text: str) -> Optional[int]:
    """Extract first number from text."""
    match = NUMBER_PATTERN.search(text)
    if match:
        return int(match.group())
    return None


def extract_all_numbers(text: str) -> list[int]:
    """Extract all numbers from text."""
    matches = NUMBER_PATTERN.findall(text)
    return [int(m) for m in matches]


def detect_order_type(text: str) -> Optional[str]:
    """Detect order type from text."""
    text_lower = text.lower()
    for order_type, pattern in ORDER_TYPE_PATTERNS.items():
        if pattern.search(text_lower):
            return order_type
    return None


def normalize_model_name(name: str | None) -> str:
    """Normalize model name for search (None-safe)."""
    if not name:
        return ""
    return name.strip().lower()


def parse_relative_date(text: str, base_date: Optional[date] = None) -> Optional[date]:
    """
    Parse relative date from text (e.g., "сегодня", "вчера", "today", "yesterday").

    Returns None if no relative date found.
    """
    if base_date is None:
        base_date = date.today()

    text_lower = text.lower()

    if any(word in text_lower for word in ["сегодня", "today"]):
        return base_date

    if any(word in text_lower for word in ["вчера", "yesterday"]):
        return base_date - timedelta(days=1)

    return None
