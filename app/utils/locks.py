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
import time

_user_locks: dict[tuple[int, int], asyncio.Lock] = {}


def get_user_lock(chat_id: int, user_id: int) -> asyncio.Lock:
    key = (chat_id, user_id)
    lock = _user_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[key] = lock
    return lock


# ---------------------------------------------------------------------------
# In-flight write locks (double-tap guard for wml_add / salary_add callbacks)
# ---------------------------------------------------------------------------
# Telegram redelivers callback_query on retry, and users double-tap while a
# slow Notion/Sheets call is in flight — both land as two concurrent handler
# invocations for the same button, each performing its own Notion/Sheets
# write. Uses Redis SET NX (safe across Cloud Run instances) when configured,
# falling back to a process-local dict otherwise (best-effort, single
# instance only — same fallback tradeoff as get_user_lock above).

_WRITE_LOCK_TTL_SECONDS = 300
_in_flight_locks: dict[str, float] = {}


async def try_acquire_write_lock(redis, key: str, ttl: int = _WRITE_LOCK_TTL_SECONDS) -> bool:
    """Return True if the lock was acquired, False if already held."""
    if redis is not None:
        return bool(await redis.set(key, "1", nx=True, ex=ttl))

    now = time.monotonic()
    expires_at = _in_flight_locks.get(key)
    if expires_at is not None and expires_at > now:
        return False
    _in_flight_locks[key] = now + ttl
    return True


async def release_write_lock(redis, key: str) -> None:
    if redis is not None:
        await redis.delete(key)
    else:
        _in_flight_locks.pop(key, None)
