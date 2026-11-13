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
import uuid
from contextlib import asynccontextmanager
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


# ---------------------------------------------------------------------------
# Per-model read-modify-write lock (counters: files total, order received)
# ---------------------------------------------------------------------------
# Notion has no atomic increment: two managers adding to the same model at the
# same time read the same value and one add is lost. The lock is a Redis
# SET NX EX (works across Cloud Run instances); without Redis, one asyncio.Lock
# per model (single instance only).

class ModelBusy(Exception):
    """The per-model lock could not be taken in time."""

    def __str__(self) -> str:
        return "busy, try again"


_MODEL_LOCK_TTL_SECONDS = 30
_MODEL_LOCK_WAIT_SECONDS = 10.0
_model_locks: dict[str, asyncio.Lock] = {}
_default_redis = None  # set by server at startup; used when a caller has no redis


def init(redis) -> None:
    global _default_redis
    _default_redis = redis


@asynccontextmanager
async def model_write_lock(
    redis,
    model_id: str,
    wait: float = _MODEL_LOCK_WAIT_SECONDS,
    ttl: int = _MODEL_LOCK_TTL_SECONDS,
):
    """Hold the lock for one model; raises ModelBusy after `wait` seconds."""
    redis = redis if redis is not None else _default_redis
    if redis is None:
        lock = _model_locks.setdefault(model_id, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), timeout=wait)
        except asyncio.TimeoutError:
            raise ModelBusy() from None
        try:
            yield
        finally:
            lock.release()
        return

    key = f"lock:model:{model_id}"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + wait
    while not await redis.set(key, token, nx=True, ex=ttl):
        if time.monotonic() >= deadline:
            raise ModelBusy()
        await asyncio.sleep(0.2)
    try:
        yield
    finally:
        try:
            if await redis.get(key) == token:  # do not drop a lock we lost to TTL expiry
                await redis.delete(key)
        except Exception:
            pass


# Page ids this bot just created: a database query lags behind the write, so a
# second add right after must reuse the page instead of creating a duplicate.
_recent_pages: dict[str, tuple[float, str]] = {}


async def remember_page(redis, key: str, page_id: str, ttl: int = 300) -> None:
    redis = redis if redis is not None else _default_redis
    if redis is not None:
        await redis.set(f"page:{key}", page_id, ex=ttl)
    else:
        _recent_pages[key] = (time.monotonic() + ttl, page_id)


async def recall_page(redis, key: str) -> str | None:
    redis = redis if redis is not None else _default_redis
    if redis is not None:
        return await redis.get(f"page:{key}") or None
    hit = _recent_pages.get(key)
    return hit[1] if hit and hit[0] > time.monotonic() else None
