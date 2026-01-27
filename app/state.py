import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StateEntry:
    data: dict[str, Any]
    expires_at: float


@dataclass
class MemoryState:
    ttl_seconds: int = 1800
    _storage: dict[int, StateEntry] = field(default_factory=dict)

    def _now(self) -> float:
        return time.time()

    def _is_expired(self, entry: StateEntry) -> bool:
        return entry.expires_at <= self._now()

    def _cleanup(self) -> None:
        expired = [user_id for user_id, entry in self._storage.items() if self._is_expired(entry)]
        for user_id in expired:
            self._storage.pop(user_id, None)

    def get(self, user_id: int) -> dict[str, Any] | None:
        self._cleanup()
        entry = self._storage.get(user_id)
        if not entry:
            return None
        if self._is_expired(entry):
            self._storage.pop(user_id, None)
            return None
        return entry.data

    def set(self, user_id: int, data: dict[str, Any]) -> None:
        self._storage[user_id] = StateEntry(data=data, expires_at=self._now() + self.ttl_seconds)

    def update(self, user_id: int, **updates: Any) -> dict[str, Any]:
        data = self.get(user_id) or {}
        data.update(updates)
        self.set(user_id, data)
        return data

    def clear(self, user_id: int) -> None:
        self._storage.pop(user_id, None)
