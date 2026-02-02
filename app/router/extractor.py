"""Intent, model, and parameter extraction from user text."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.router.keywords import (
    INTENT_KEYWORDS,
    MODEL_KEYWORDS,
    ACTION_KEYWORDS,
    STATUS_KEYWORDS,
)


@dataclass
class ExtractedData:
    """Extracted intent, model, and parameters from user text."""
    intent: str  # e.g., "orders_new", "planner_list"
    model: str  # e.g., "orders", "planner"
    action: str  # e.g., "create", "view", "search"
    query: str  # Cleaned up text for search
    numbers: list[int]  # Extracted numbers
    dates: list[dict]  # Extracted dates with type
    confidence: float  # 0.0 to 1.0


def extract_intent_and_model(text: str) -> Optional[tuple[str, str]]:
    """Extract primary intent and model from text."""
    text_lower = text.lower()

    # Score each intent with length-weighted scoring (longer keywords score higher)
    intent_scores = {}
    for intent_name, intent_data in INTENT_KEYWORDS.items():
        score = 0
        for keyword in intent_data["keywords"]:
            if keyword in text_lower:
                # Weight by keyword length to prefer specific keywords
                score += len(keyword)
        if score > 0:
            intent_scores[intent_name] = score

    if not intent_scores:
        return None

    # Get the intent with highest score
    best_intent = max(intent_scores, key=intent_scores.get)
    model = INTENT_KEYWORDS[best_intent]["model"]

    return best_intent, model


def extract_action(text: str) -> str:
    """Extract action from text."""
    text_lower = text.lower()

    action_scores = {}
    for action_name, keywords in ACTION_KEYWORDS.items():
        score = sum(
            1 for keyword in keywords
            if keyword in text_lower
        )
        if score > 0:
            action_scores[action_name] = score

    if action_scores:
        return max(action_scores, key=action_scores.get)

    # Default action based on intent
    return "view"


def extract_numbers(text: str) -> list[int]:
    """Extract all numbers from text."""
    # Find all number sequences
    matches = re.findall(r'\b(\d+)\b', text)
    return [int(m) for m in matches]


def extract_dates(text: str) -> list[dict]:
    """Extract relative and absolute dates from text."""
    dates = []
    text_lower = text.lower()

    # Relative dates
    relative_patterns = {
        r'завтра|tomorrow|next day': lambda: datetime.now() + timedelta(days=1),
        r'сегодня|today': lambda: datetime.now(),
        r'вчера|yesterday': lambda: datetime.now() - timedelta(days=1),
        r'через (\d+) дн|in (\d+) days?|next (\d+) days?': lambda m: datetime.now() + timedelta(
            days=int(m.group(1) or m.group(2) or m.group(3))
        ),
        r'на следующей неделе|next week': lambda: datetime.now() + timedelta(days=7),
        r'на этой неделе|this week': lambda: datetime.now(),
    }

    for pattern, date_func in relative_patterns.items():
        if re.search(pattern, text_lower):
            try:
                dates.append({
                    "type": "relative",
                    "date": date_func().date(),
                    "pattern": pattern,
                })
            except (ValueError, TypeError):
                pass

    # Absolute dates (DD.MM, DD/MM, DD-MM, YYYY-MM-DD)
    date_patterns = [
        r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?',  # 25.12.2024 or 25.12
        r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?',    # 25/12/2024 or 25/12
        r'(\d{1,2})-(\d{1,2})(?:-(\d{4}))?',    # 25-12-2024 or 25-12
        r'(\d{4})-(\d{1,2})-(\d{1,2})',         # 2024-12-25
    ]

    for pattern in date_patterns:
        matches = re.finditer(pattern, text)
        for match in matches:
            try:
                groups = match.groups()

                if pattern == r'(\d{4})-(\d{1,2})-(\d{1,2})':
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                else:
                    day = int(groups[0])
                    month = int(groups[1])
                    year = int(groups[2]) if groups[2] else datetime.now().year

                parsed_date = datetime(year, month, day).date()
                dates.append({
                    "type": "absolute",
                    "date": parsed_date,
                    "pattern": pattern,
                })
            except (ValueError, IndexError):
                pass

    return dates


def clean_text_for_search(text: str) -> str:
    """Remove intent/action keywords to get clean search text."""
    text_lower = text.lower()
    cleaned = text

    # Remove all known keywords
    all_keywords = set()
    for intent_data in INTENT_KEYWORDS.values():
        all_keywords.update(intent_data["keywords"])

    for action_keywords in ACTION_KEYWORDS.values():
        all_keywords.update(action_keywords)

    for keywords in MODEL_KEYWORDS.values():
        all_keywords.update(keywords)

    # Sort by length (longest first) to avoid partial removals
    for keyword in sorted(all_keywords, key=len, reverse=True):
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        cleaned = pattern.sub("", cleaned)

    # Clean up extra spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned


def calculate_confidence(text: str, intent: str, model: str) -> float:
    """Calculate confidence score for extracted intent and model."""
    text_lower = text.lower()
    intent_keywords = INTENT_KEYWORDS.get(intent, {}).get("keywords", [])

    # Count matching keywords
    matches = sum(1 for kw in intent_keywords if kw in text_lower)

    # Calculate confidence: 0.5 for any match, up to 1.0 with multiple matches
    if matches == 0:
        return 0.3  # Low confidence if no direct keywords
    elif matches == 1:
        return 0.6
    elif matches == 2:
        return 0.8
    else:
        return 0.95


def extract(text: str) -> Optional[ExtractedData]:
    """Extract all data from user text."""
    if not text or len(text.strip()) < 2:
        return None

    # Extract intent and model
    result = extract_intent_and_model(text)
    if not result:
        return None

    intent, model = result

    # Extract other data
    action = extract_action(text)
    numbers = extract_numbers(text)
    dates = extract_dates(text)
    query = clean_text_for_search(text)
    confidence = calculate_confidence(text, intent, model)

    return ExtractedData(
        intent=intent,
        model=model,
        action=action,
        query=query,
        numbers=numbers,
        dates=dates,
        confidence=confidence,
    )
