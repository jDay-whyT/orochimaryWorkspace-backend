"""
Pre-filter for incoming messages before NLP routing.

Checks:
1. Gibberish detection (no vowels)
2. Minimum length (< 2 characters)
3. Bot commands (starts with /)
"""

import re
import logging

LOGGER = logging.getLogger(__name__)

# Vowels in Russian and English
_VOWELS = set("aeiouаеёиоуыэюя")

# Min query length for meaningful input
MIN_QUERY_LENGTH = 2


def is_gibberish(text: str) -> bool:
    """
    Check if text is gibberish (no vowels in any language).

    Examples:
        "asdfgh" → True (no vowels in the alpha chars... actually 'a' is a vowel)
        "bcdfg" → True
        "мелиса" → False
        "бкдфг" → True
    """
    # Extract only letters
    letters = re.sub(r'[^a-zа-яё]', '', text.lower())
    if not letters:
        return True
    return not any(ch in _VOWELS for ch in letters)


def is_bot_command(text: str) -> bool:
    """Check if text is a bot command (starts with /)."""
    return text.strip().startswith("/")


def is_too_short(text: str) -> bool:
    """Check if text is too short for meaningful NLP processing."""
    # Strip whitespace and check length
    stripped = text.strip()
    if len(stripped) < MIN_QUERY_LENGTH:
        return True
    # Also check if the non-whitespace content is too short
    content = re.sub(r'\s+', '', stripped)
    return len(content) < MIN_QUERY_LENGTH


def prefilter_message(text: str) -> tuple[bool, str | None]:
    """
    Pre-filter message before NLP routing.

    Returns:
        (passed, error_message)
        - (True, None) if message passes all filters
        - (False, error_str) if message should be rejected
    """
    if not text or not text.strip():
        return False, None  # Silently ignore empty

    text = text.strip()

    # Bot commands are handled by aiogram command handlers
    if is_bot_command(text):
        return False, None  # Silently ignore

    # Too short
    if is_too_short(text):
        LOGGER.debug("Pre-filter: too short text=%r", text)
        return False, "Слишком короткий запрос."

    # Gibberish (only if text is purely alphabetic-ish)
    # Don't flag numbers or mixed content as gibberish
    letters_only = re.sub(r'[^a-zа-яё]', '', text.lower())
    if len(letters_only) >= 3 and is_gibberish(text):
        LOGGER.debug("Pre-filter: gibberish text=%r", text)
        return False, None  # Silently ignore gibberish

    return True, None
