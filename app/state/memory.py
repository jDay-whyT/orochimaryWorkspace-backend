import time
import logging
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class StateEntry:
    data: dict[str, Any]
    expires_at: float


@dataclass
class MemoryState:
    """In-memory user state storage with TTL."""
    ttl_seconds: int = 7200  # 2 hours (increased from 30 minutes)
    _storage: dict[tuple[int, int], StateEntry] = field(default_factory=dict)
    _last_chat_id_by_user: dict[int, int] = field(default_factory=dict)

    @staticmethod
    def _key(chat_id: int, user_id: int) -> tuple[int, int]:
        return (chat_id, user_id)

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

    def _now(self) -> float:
        return time.time()

    def _is_expired(self, entry: StateEntry) -> bool:
        return entry.expires_at <= self._now()

    def _cleanup(self) -> None:
        expired = [key for key, entry in self._storage.items() if self._is_expired(entry)]
        for key in expired:
            self._storage.pop(key, None)

    def get(
        self,
        chat_id: int | tuple[int, int],
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        self._cleanup()
        key = self._resolve_key(chat_id, user_id)
        if key is None:
            return None
        entry = self._storage.get(key)
        if not entry:
            return None
        if self._is_expired(entry):
            self._storage.pop(key, None)
            return None
        return entry.data

    def set(
        self,
        chat_id: int | tuple[int, int],
        user_id: int | None,
        data: dict[str, Any],
    ) -> None:
        key = self._resolve_key(chat_id, user_id)
        if key is None:
            return
        self._storage[key] = StateEntry(
            data=data,
            expires_at=self._now() + self.ttl_seconds,
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

    def transition(
        self,
        chat_id: int,
        user_id: int,
        flow: str,
        **updates: Any,
    ) -> dict[str, Any]:
        """
        Transition user state to a new flow with validation and logging.

        Args:
            chat_id: Chat ID
            user_id: User ID
            flow: New flow name (must start with 'nlp_' prefix)
            **updates: Additional state updates

        Returns:
            Updated state dictionary

        Raises:
            ValueError: If flow doesn't start with 'nlp_' prefix
        """
        if not flow.startswith("nlp_"):
            raise ValueError(
                f"Invalid flow name '{flow}'. All flows must start with 'nlp_' prefix. "
                f"Use 'nlp_{flow}' instead."
            )

        old_state = self.get(chat_id, user_id) or {}
        old_flow = old_state.get("flow", "none")

        LOGGER.info(
            "State transition: user=%s chat=%s flow=%s->%s updates=%s",
            user_id,
            chat_id,
            old_flow,
            flow,
            updates,
        )

        data = old_state.copy()
        data["flow"] = flow
        data.update(updates)
        self.set(chat_id, user_id, data)
        return data

    def clear(self, chat_id: int | tuple[int, int], user_id: int | None = None) -> None:
        key = self._resolve_key(chat_id, user_id)
        if key is None:
            return
        self._storage.pop(key, None)
