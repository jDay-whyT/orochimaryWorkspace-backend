"""Anti-stale token helpers for NLP callback keyboards.

Each time a new NLP keyboard is sent, a fresh token (k) is generated and
stored in memory_state.  The token is appended to every callback_data string
so the handler can verify that the button belongs to the *current* keyboard.

Token format: 6-character base36 string (e.g. "a3f1x7").
This keeps callback_data well under Telegram's 64-byte limit.
"""

import secrets
import string

from app.state.memory import MemoryState

_ALPHABET = string.ascii_lowercase + string.digits  # base36


def generate_token(length: int = 6) -> str:
    """Generate a short random base36 token."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def get_active_token(
    memory_state: MemoryState,
    chat_id: int,
    user_id: int,
    fallback_from_callback: str | None = None,
) -> str:
    """Return the current screen token, creating one only for a new session."""
    state = memory_state.get(chat_id, user_id) or {}
    state_token = state.get("k")
    if state_token:
        return state_token

    if fallback_from_callback:
        memory_state.update(chat_id, user_id, k=fallback_from_callback)
        return fallback_from_callback

    token = generate_token()
    memory_state.update(chat_id, user_id, k=token)
    return token
