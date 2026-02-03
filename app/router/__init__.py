"""Router module for NLP-based message routing."""

# Old system (kept for backwards compatibility)
from app.router.intent import Intent, classify_intent
from app.router.entities import Entities, extract_entities

# New v2 system (recommended)
from app.router.intent_v2 import classify_intent_v2, get_intent_description
from app.router.entities_v2 import extract_entities_v2, EntitiesV2
from app.router.command_filters import CommandIntent


def _lazy_import_route_message():
    """Lazy import to avoid aiogram dependency at module level."""
    from app.router.dispatcher import route_message
    return route_message


# Make route_message available but delay actual import
def __getattr__(name):
    if name == "route_message":
        return _lazy_import_route_message()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Old system
    "Intent",
    "classify_intent",
    "Entities",
    "extract_entities",
    # New v2 system
    "CommandIntent",
    "classify_intent_v2",
    "get_intent_description",
    "EntitiesV2",
    "extract_entities_v2",
    # Dispatcher
    "route_message",
]
