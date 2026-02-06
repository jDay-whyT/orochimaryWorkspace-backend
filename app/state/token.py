"""Anti-stale token helpers for NLP callback keyboards.

Each time a new NLP keyboard is sent, a fresh token (k) is generated and
stored in memory_state.  The token is appended to every callback_data string
so the handler can verify that the button belongs to the *current* keyboard.

Token format: 4-character base36 string (e.g. "a3f1").
This keeps callback_data well under Telegram's 64-byte limit.
"""

import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits  # base36


def generate_token(length: int = 4) -> str:
    """Generate a short random base36 token."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
