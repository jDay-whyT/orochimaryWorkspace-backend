import asyncio
import dataclasses
import json
import logging
from concurrent.futures import Future
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any
from urllib.parse import urlsplit

from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

LOGGER = logging.getLogger(__name__)

# Connection-level errors worth retrying once on a fresh connection: redis-py's
# own ConnectionError/TimeoutError (raised for socket read/write failures —
# these do NOT subclass the builtin exceptions of the same name) plus the
# builtin ConnectionError/TimeoutError for any raw socket error that reaches
# us unwrapped.
_RETRYABLE_REDIS_ERRORS = (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError)


def _default_serializer(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _redact_redis_url(url: str) -> str:
    """scheme://host:port only — strips any embedded username/password."""
    parts = urlsplit(url)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname or ''}{port}"


@dataclass
class RedisMemoryState:
    """Redis-backed user state storage with TTL."""

    redis_url: str
    ttl_seconds: int = 1800  # 30 minutes
    redis_client: Any = None
    redis_kwargs: dict[str, Any] = field(default_factory=dict)
    _last_chat_id_by_user: dict[int, int] = field(default_factory=dict)
    _thread: Thread | None = field(default=None, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)
    _ready: Event = field(default_factory=Event, init=False)

    def __post_init__(self) -> None:
        if self.redis_client is None:
            from redis.asyncio import Redis
            from redis.backoff import ExponentialBackoff
            from redis.retry import Retry

            kwargs = dict(self.redis_kwargs)
            kwargs.setdefault("socket_keepalive", True)
            kwargs.setdefault("health_check_interval", 30)
            kwargs.setdefault("retry_on_timeout", True)
            kwargs.setdefault("retry_on_error", [RedisConnectionError, RedisTimeoutError])
            kwargs.setdefault("retry", Retry(ExponentialBackoff(), 2))
            self.redis_client = Redis.from_url(self.redis_url, decode_responses=True, **kwargs)
            LOGGER.info("RedisMemoryState initialized: url=%s ttl=%s", _redact_redis_url(self.redis_url), self.ttl_seconds)

        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._ready.set()
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        except Exception as e:
            LOGGER.error("Redis event loop crashed: %s", e)

    def _run(self, coro: Any) -> Any:
        self._ready.wait(timeout=1.0)
        if self._loop is None:
            raise RuntimeError("Redis event loop is not initialized")
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    @staticmethod
    def _state_key(chat_id: int, user_id: int) -> str:
        return f"state:{chat_id}:{user_id}"

    def _resolve_key(
        self,
        chat_id: int | tuple[int, int],
        user_id: int | None,
    ) -> tuple[int, int] | None:
        if user_id is None:
            if isinstance(chat_id, tuple):
                chat_id, user_id = chat_id
            else:
                legacy_user_id = chat_id
                chat_id = self._last_chat_id_by_user.get(legacy_user_id)
                if chat_id is None:
                    return None
                user_id = legacy_user_id
        self._last_chat_id_by_user[user_id] = chat_id
        return (chat_id, user_id)

    async def _get_data(self, key: str) -> dict[str, Any] | None:
        assert self.redis_client is not None
        raw = await self.redis_client.get(key)
        if not raw:
            return None
        return json.loads(raw)

    def _run_resilient(self, make_coro: Any, *, on_error: Any) -> Any:
        """
        Run a Redis coroutine, tolerating a single dropped connection.
        Upstash closes idle TCP connections server-side; redis-py's own
        retry (see __post_init__) reuses the same dead connection and can
        still raise ConnectionError/TimeoutError on the first attempt after
        an idle period. One extra attempt on a fresh connection covers that
        case; a second consecutive failure is treated as a real outage and
        falls back to `on_error` instead of crashing the caller's handler.
        `make_coro` is a zero-arg callable — a coroutine object can only be
        awaited once, so retrying needs a fresh one each attempt.
        """
        try:
            return self._run(make_coro())
        except _RETRYABLE_REDIS_ERRORS as e:
            LOGGER.warning("Redis op failed once (%s), retrying", e)
            try:
                return self._run(make_coro())
            except _RETRYABLE_REDIS_ERRORS as e2:
                LOGGER.error("Redis op failed twice, giving up: %s", e2)
                return on_error() if callable(on_error) else on_error

    def get(
        self,
        chat_id: int | tuple[int, int],
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        key = self._resolve_key(chat_id, user_id)
        if key is None:
            return None
        redis_key = self._state_key(*key)
        return self._run_resilient(lambda: self._get_data(redis_key), on_error=None)

    def set(
        self,
        chat_id: int | tuple[int, int],
        user_id: int | None,
        data: dict[str, Any],
    ) -> None:
        key = self._resolve_key(chat_id, user_id)
        if key is None:
            return

        redis_key = self._state_key(*key)
        previous_data = self._run_resilient(lambda: self._get_data(redis_key), on_error=None)
        if (
            previous_data
            and "prompt_message_id" not in data
            and "prompt_message_id" in previous_data
        ):
            data = {
                **data,
                "prompt_message_id": previous_data.get("prompt_message_id"),
            }

        assert self.redis_client is not None
        payload = json.dumps(data, default=_default_serializer)
        self._run_resilient(
            lambda: self.redis_client.set(redis_key, payload, ex=self.ttl_seconds),
            on_error=None,
        )

    def update(
        self,
        chat_id: int,
        user_id: int,
        **updates: Any,
    ) -> dict[str, Any]:
        data = self.get(chat_id, user_id) or {}
        data.update(updates)
        self.set(chat_id, user_id, data)
        return data

    def clear(self, chat_id: int | tuple[int, int], user_id: int | None = None) -> None:
        key = self._resolve_key(chat_id, user_id)
        if key is None:
            return
        redis_key = self._state_key(*key)
        assert self.redis_client is not None
        self._run_resilient(lambda: self.redis_client.delete(redis_key), on_error=None)
