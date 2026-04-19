import asyncio
import json
from concurrent.futures import Future
from dataclasses import dataclass, field
from threading import Event, Thread


@dataclass
class RedisRecentModels:
    """Redis-backed recent models store. Max 9 models, LRU eviction."""

    redis_url: str
    max_size: int = 9
    ttl_seconds: int = 7 * 24 * 60 * 60
    redis_client: object | None = None
    redis_kwargs: dict[str, object] = field(default_factory=dict)
    _thread: Thread | None = field(default=None, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)
    _ready: Event = field(default_factory=Event, init=False)

    def __post_init__(self) -> None:
        if self.redis_client is None:
            from redis.asyncio import Redis

            kwargs = dict(self.redis_kwargs)
            self.redis_client = Redis.from_url(self.redis_url, decode_responses=True, **kwargs)

        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._ready.set()
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _run(self, coro):
        self._ready.wait(timeout=1.0)
        if self._loop is None:
            raise RuntimeError("Redis event loop is not initialized")
        future: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    @staticmethod
    def _key(user_id: int) -> str:
        return f"recent:{user_id}"

    def _load_models(self, user_id: int) -> list[list[str]]:
        assert self.redis_client is not None
        raw = self._run(self.redis_client.get(self._key(user_id)))
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, list) and len(item) == 2]
        return []

    def add(self, user_id: int, model_id: str, model_title: str) -> None:
        items = self._load_models(user_id)

        # stored as oldest -> newest internally
        items = [item for item in items if item[0] != model_id]
        items.append([model_id, model_title])
        items = items[-self.max_size :]

        assert self.redis_client is not None
        self._run(self.redis_client.set(self._key(user_id), json.dumps(items), ex=self.ttl_seconds))

    def get(self, user_id: int) -> list[tuple[str, str]]:
        items = self._load_models(user_id)
        items.reverse()  # return most recent first
        return [(item[0], item[1]) for item in items]

    def clear(self, user_id: int) -> None:
        assert self.redis_client is not None
        self._run(self.redis_client.delete(self._key(user_id)))
