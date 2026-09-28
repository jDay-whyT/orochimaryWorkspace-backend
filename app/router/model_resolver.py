"""
Model resolution with typo tolerance, recent models, and disambiguation.

Resolution order:
1. Recent Models (last 10) — exact / substring only (a typo must not jump to a
   recent model when another model is spelled exactly like the query)
2. All models from Notion, scored against title + aliases:
   exact > alias > substring > typo (1 letter off, 2 for long names) > fuzzy
3. Nothing close enough → the nearest models are offered as buttons

Safety: typo/fuzzy matching only for queries >= 4 chars.
A single typo/fuzzy match returns "confirm" (the user confirms it).
Matching ignores case, ё/е and accents (berlin == berlín).
"""

import logging
import unicodedata
from difflib import SequenceMatcher

LOGGER = logging.getLogger(__name__)

# Config
FUZZY_THRESHOLD_RECENT = 0.82
FUZZY_THRESHOLD_GENERAL = 0.80
SUGGEST_THRESHOLD = 0.55  # below every other match: only offered as "did you mean one of these"
MIN_QUERY_LENGTH = 3
FUZZY_MIN_QUERY_LENGTH = 4
MAX_DISAMBIGUATION_BUTTONS = 5


def normalize_model_name(name: str) -> str:
    """
    Normalize model name for matching.

    "Black-Pearl" → "black pearl", "Берлин" → "берлин", "Berlín" → "berlin", "Ёж" → "еж"
    """
    result = unicodedata.normalize("NFKD", name.lower())
    result = "".join(ch for ch in result if not unicodedata.combining(ch))
    result = result.replace("-", " ").replace("_", " ")
    # Collapse multiple spaces
    result = " ".join(result.split())
    return result.strip()


def fuzzy_score(query: str, target: str) -> float:
    """Fuzzy match score (0.0-1.0) between query and target via difflib.SequenceMatcher."""
    query_norm = normalize_model_name(query)
    target_norm = normalize_model_name(target)
    return SequenceMatcher(None, query_norm, target_norm).ratio()


def _typo_distance(a: str, b: str) -> int:
    """Edit distance counting a swap of two neighbouring letters as one typo."""
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[len(b)]


def _allowed_typos(length: int) -> int:
    if length < FUZZY_MIN_QUERY_LENGTH:
        return 0
    return 2 if length >= 7 else 1


def typo_score(query: str, target: str) -> float:
    """0.85-0.9 when target is the query with 1 typo (2 for long names), else 0.0.

    Compared against the whole name, the name without spaces and each word of it.
    """
    q = normalize_model_name(query)
    t = normalize_model_name(target)
    allowed = _allowed_typos(len(q))
    if not allowed or not t:
        return 0.0
    candidates = [c for c in {t, t.replace(" ", ""), *t.split()} if abs(len(c) - len(q)) <= allowed]
    if not candidates:
        return 0.0
    best = min(_typo_distance(q, c) for c in candidates)
    if 0 < best <= allowed:
        return 0.9 - 0.05 * (best - 1)
    return 0.0


def match_recent_models(
    query: str,
    recent: list[tuple[str, str]],
) -> list[dict]:
    """Match query against recent [(model_id, title), ...]; returns [{"id", "name", "score", "match_type"}, ...]."""
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

        # 3. Typo / fuzzy (only for queries >= FUZZY_MIN_QUERY_LENGTH)
        if len(query_norm) >= FUZZY_MIN_QUERY_LENGTH:
            typo = typo_score(query, title)
            if typo:
                matches.append({"id": model_id, "name": title, "score": typo, "match_type": "fuzzy"})
                continue
            score = fuzzy_score(query, title)
            if score >= FUZZY_THRESHOLD_RECENT:
                matches.append({"id": model_id, "name": title, "score": score, "match_type": "fuzzy"})

    # Sort by score descending
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches


def _score_model(query: str, query_norm: str, model: dict) -> tuple[float, str]:
    """Best (score, match_type) of a model against the query over its title and aliases."""
    names = [model["name"], *model.get("aliases", [])]
    norms = [normalize_model_name(n) for n in names]

    if query_norm == norms[0]:
        return 1.0, "exact"
    if query_norm in norms[1:]:
        return 0.98, "alias"
    squeezed = query_norm.replace(" ", "")
    if any(squeezed == n.replace(" ", "") for n in norms):  # "танго8" == "Танго 8"
        return 0.98, "exact"
    if len(query_norm) >= MIN_QUERY_LENGTH and any(query_norm in n for n in norms):
        return 0.9, "substring"
    if len(query_norm) < FUZZY_MIN_QUERY_LENGTH:
        return 0.0, ""

    typo = max(typo_score(query, n) for n in names)
    if typo:
        return typo, "fuzzy"
    return max(fuzzy_score(query, n) for n in names), "fuzzy"


def match_notion_results(
    query: str,
    models: list[dict],
) -> list[dict]:
    """Score query against models [{"id", "name", "aliases"}, ...]; matches only, best first."""
    if not query or not models:
        return []

    query_norm = normalize_model_name(query)
    scored = []
    for model in models:
        score, match_type = _score_model(query, query_norm, model)
        if match_type == "fuzzy" and score < FUZZY_THRESHOLD_GENERAL:
            continue
        if score > 0:
            scored.append({**model, "score": score, "match_type": match_type})

    scored.sort(key=lambda m: m["score"], reverse=True)
    return scored


def suggest_models(query: str, models: list[dict], limit: int = MAX_DISAMBIGUATION_BUTTONS) -> list[dict]:
    """The closest models even when nothing matched well — offered as 'did you mean one of these'."""
    if len(normalize_model_name(query)) < FUZZY_MIN_QUERY_LENGTH:
        return []
    ranked = []
    for model in models:
        score = max(fuzzy_score(query, n) for n in [model["name"], *model.get("aliases", [])])
        if score >= SUGGEST_THRESHOLD:
            ranked.append({**model, "score": score, "match_type": "fuzzy"})
    ranked.sort(key=lambda m: m["score"], reverse=True)
    return ranked[:limit]


async def resolve_model(
    query: str,
    user_id: int,
    db_models: str,
    notion,
    recent_models,
) -> dict:
    """Full model resolution pipeline; returns {"status": found|confirm|multiple|not_found, "model", "models"}."""
    if not query or len(query) < MIN_QUERY_LENGTH:
        return {"status": "not_found", "model": None, "models": []}

    # Step 1: recent models — only exact / substring hits short-circuit
    recent = recent_models.get(user_id)
    if recent:
        recent_matches = [m for m in match_recent_models(query, recent) if m["match_type"] != "fuzzy"]
        if len(recent_matches) == 1:
            m = recent_matches[0]
            LOGGER.info("Model resolved from recent: %s (score=%.2f, type=%s)", m["name"], m["score"], m["match_type"])
            return {"status": "found", "model": m, "models": []}
        if len(recent_matches) > 1 and recent_matches[0]["score"] >= 0.98:
            return {"status": "found", "model": recent_matches[0], "models": []}

    # Step 2: all models from Notion
    from app.handlers.models import search_model_by_name_or_alias

    try:
        all_models = await search_model_by_name_or_alias(query, db_models, notion)
    except Exception as e:
        LOGGER.exception("Failed to search models: %s", e)
        return {"status": "not_found", "model": None, "models": []}

    scored = match_notion_results(query, all_models)

    if not scored:
        suggestions = suggest_models(query, all_models)
        if suggestions:
            return {"status": "multiple", "model": None, "models": suggestions}
        return {"status": "not_found", "model": None, "models": []}

    top = scored[0]
    if top["score"] >= 0.98:
        return {"status": "found", "model": top, "models": []}

    if len(scored) == 1:
        # Typo / fuzzy-only single match → require confirmation
        if top["match_type"] == "fuzzy":
            return {"status": "confirm", "model": top, "models": []}
        return {"status": "found", "model": top, "models": []}

    return {
        "status": "multiple",
        "model": None,
        "models": scored[:MAX_DISAMBIGUATION_BUTTONS],
    }
