from unittest.mock import AsyncMock, MagicMock, patch

import asyncio

from app.router.dispatcher import route_message
from app.state.memory import MemoryState


def test_nlp_idle_flow_does_not_skip_and_runs_nlp_pipeline():
    message = MagicMock()
    message.text = "трико"
    message.from_user.id = 42
    message.chat.id = 100
    message.answer = AsyncMock()

    config = MagicMock()
    notion = AsyncMock()
    recent_models = MagicMock()

    memory_state = MemoryState()
    memory_state.set(message.chat.id, message.from_user.id, {"flow": "nlp_idle"})

    with patch("app.router.dispatcher.prefilter_message", return_value=(False, None)) as prefilter:
        asyncio.run(route_message(message, config, notion, memory_state, recent_models))

    prefilter.assert_called_once_with("трико")
