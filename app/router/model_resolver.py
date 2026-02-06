"""
Model resolution with fuzzy matching, recent models, and disambiguation.

Resolution order:
1. Recent Models (last 10) — exact, substring, fuzzy >= 85%
2. Notion Query — search by title + aliases
3. Fuzzy match on results >= 80%
4. Disambiguation UI if multiple matches

Safety: fuzzy matching only applied for queries >= 4 chars.
Fuzzy-only single matches return "confirm" status (require user confirmation).
"""

import logging
from difflib import SequenceMatcher
from typing import Optional

from app.router.command_filters import normalize_text

LOGGER = logging.getLogger(__name__)

# Config
FUZZY_THRESHOLD_RECENT = 0.85
FUZZY_THRESHOLD_GENERAL = 0.80
MIN_QUERY_LENGTH = 3
FUZZY_MIN_QUERY_LENGTH = 4
MAX_DISAMBIGUATION_BUTTONS = 5


def normalize_model_name(name: str) -> str:
    """
    Normalize model name for matching.

    "Black-Pearl" → "black pearl"
    "polik" → "polik"
    """
    result = name.lower()
    result = result.replace("-", " ").replace("_", " ")
    # Collapse multiple spaces
    result = " ".join(result.split())
    return result.strip()


def fuzzy_score(query: str, target: str) -> float:
    """
    Calculate fuzzy match score between query and target.
    Uses difflib.SequenceMatcher.

    Returns: float 0.0 - 1.0
    """
    query_norm = normalize_model_name(query)
    target_norm = normalize_model_name(target)
    return SequenceMatcher(None, query_norm, target_norm).ratio()


def match_recent_models(
    query: str,
    recent: list[tuple[str, str]],
) -> list[dict]:
    """
    Search query against recent models list.

    Args:
        query: User's model query
        recent: [(model_id, title), ...] from RecentModels

    Returns:
        List of matches: [{"id": str, "name": str, "score": float, "match_type": str}, ...]
    """
    if not query or not recent:
        return []

    query_norm = normalize_model_name(query)
    matches = []

    for model_id, title in recent:
        title_norm = normalize_model_name(title)

        # 1. Exact match
        if query_norm == title_norm:
            matches.append({"id": model_id, "name": title, "score": 1.0, "match_type": "exact"})
            continue

        # 2. Substring (query in name)
        if query_norm in title_norm:
            matches.append({"id": model_id, "name": title, "score": 0.95, "match_type": "substring"})
            continue

        # 3. Fuzzy match >= 85% (only for queries >= FUZZY_MIN_QUERY_LENGTH)
        if len(query_norm) >= FUZZY_MIN_QUERY_LENGTH:
            score = fuzzy_score(query, title)
            if score >= FUZZY_THRESHOLD_RECENT:
                matches.append({"id": model_id, "name": title, "score": score, "match_type": "fuzzy"})

    # Sort by score descending
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches


def match_notion_results(
    query: str,
    models: list[dict],
) -> list[dict]:
    """
    Apply fuzzy matching to Notion search results.

    Args:
        query: User's model query
        models: [{"id": str, "name": str, "aliases": list[str]}, ...]

    Returns:
        Sorted list with scores: [{"id": str, "name": str, "score": float, "match_type": str}, ...]
    """
    if not query or not models:
        return models

    query_norm = normalize_model_name(query)
    scored = []

    for model in models:
        name_norm = normalize_model_name(model["name"])

        # Exact match on title
        if query_norm == name_norm:
            scored.append({**model, "score": 1.0, "match_type": "exact"})
            continue

        # Check aliases for exact match
        aliases = model.get("aliases", [])
        alias_exact = any(
            query_norm == normalize_model_name(alias) for alias in aliases
        )
        if alias_exact:
            scored.append({**model, "score": 0.98, "match_type": "alias"})
            continue

        # Fuzzy match only for queries >= FUZZY_MIN_QUERY_LENGTH
        if len(query_norm) < FUZZY_MIN_QUERY_LENGTH:
            continue

        # Fuzzy match on title
        title_score = fuzzy_score(query, model["name"])

        # Fuzzy match on aliases (take best)
        alias_score = max(
            (fuzzy_score(query, alias) for alias in aliases),
            default=0.0,
        )

        best_score = max(title_score, alias_score)

        if best_score >= FUZZY_THRESHOLD_GENERAL:
            scored.append({**model, "score": best_score, "match_type": "fuzzy"})

    # Sort by score descending
    scored.sort(key=lambda m: m["score"], reverse=True)
    return scored


async def resolve_model(
    query: str,
    user_id: int,
    db_models: str,
    notion,
    recent_models,
) -> dict:
    """
    Full model resolution pipeline.

    Returns:
        {
            "status": "found" | "confirm" | "multiple" | "not_found",
            "model": {...} or None,           # Single match
            "models": [...] or [],             # Multiple matches
        }

    "confirm" status: fuzzy-only match that needs user confirmation.
    """
    if not query or len(query) < MIN_QUERY_LENGTH:
        return {"status": "not_found", "model": None, "models": []}

    # Step 1: Check recent models
    recent = recent_models.get(user_id)
    if recent:
        recent_matches = match_recent_models(query, recent)
        if len(recent_matches) == 1:
            m = recent_matches[0]
            LOGGER.info("Model resolved from recent: %s (score=%.2f, type=%s)", m["name"], m["score"], m["match_type"])
            # Fuzzy-only single match → require confirmation
            if m["match_type"] == "fuzzy":
                return {"status": "confirm", "model": m, "models": []}
            return {"status": "found", "model": m, "models": []}
        if len(recent_matches) > 1:
            # Check if top match is clearly better (exact or alias)
            if recent_matches[0]["score"] >= 0.98 and recent_matches[0]["match_type"] != "fuzzy":
                m = recent_matches[0]
                return {"status": "found", "model": m, "models": []}
            return {
                "status": "multiple",
                "model": None,
                "models": recent_matches[:MAX_DISAMBIGUATION_BUTTONS],
            }

    # Step 2: Query Notion
    from app.handlers.models import search_model_by_name_or_alias

    try:
        notion_results = await search_model_by_name_or_alias(query, db_models, notion)
    except Exception as e:
        LOGGER.exception("Failed to search models: %s", e)
        return {"status": "not_found", "model": None, "models": []}

    if not notion_results:
        return {"status": "not_found", "model": None, "models": []}

    # Step 3: Apply fuzzy matching to Notion results
    scored = match_notion_results(query, notion_results)

    if not scored:
        # Notion returned results but none passed fuzzy threshold
        # Return raw results for disambiguation
        if len(notion_results) <= MAX_DISAMBIGUATION_BUTTONS:
            return {"status": "multiple", "model": None, "models": notion_results}
        return {"status": "not_found", "model": None, "models": []}

    if len(scored) == 1:
        m = scored[0]
        # Fuzzy-only single match → require confirmation
        if m.get("match_type") == "fuzzy":
            return {"status": "confirm", "model": m, "models": []}
        return {"status": "found", "model": m, "models": []}

    # Multiple matches — check if top match is clearly best (exact or alias)
    if scored[0]["score"] >= 0.98 and scored[0].get("match_type") != "fuzzy":
        return {"status": "found", "model": scored[0], "models": []}

    return {
        "status": "multiple",
        "model": None,
        "models": scored[:MAX_DISAMBIGUATION_BUTTONS],
    }
