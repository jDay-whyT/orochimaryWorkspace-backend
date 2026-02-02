"""Intent-based routing module."""

from app.router.intent_router import (
    create_intent_router,
    register_model_handler,
)
from app.router.extractor import extract, ExtractedData
from app.router.keywords import (
    INTENT_KEYWORDS,
    MODEL_KEYWORDS,
    ACTION_KEYWORDS,
)

__all__ = [
    "create_intent_router",
    "register_model_handler",
    "extract",
    "ExtractedData",
    "INTENT_KEYWORDS",
    "MODEL_KEYWORDS",
    "ACTION_KEYWORDS",
]
