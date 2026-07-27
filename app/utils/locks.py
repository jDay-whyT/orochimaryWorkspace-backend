"""Per-(chat, user) asyncio locks shared across text and callback handlers.

Text messages (app.router.dispatcher) and inline button presses
(app.handlers.nlp_callbacks) both read-modify-write the same MemoryState
entry for a given user. Without a shared lock, a callback press (e.g.
confirming an order) can interleave with a concurrent text message (e.g.
searching a different model) for the same user, so the callback ends up
reading a state dict that was already overwritten — producing orders
created with a stale or missing model_id.
"""
import asyncio

_user_locks: dict[tuple[int, int], asyncio.Lock] = {}


def get_user_lock(chat_id: int, user_id: int) -> asyncio.Lock:
    key = (chat_id, user_id)
    lock = _user_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[key] = lock
    return lock
