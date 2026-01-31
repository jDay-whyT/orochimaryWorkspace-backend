from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class RecentModels:
    """Track recently used models per user. Max 9 models, LRU eviction."""
    max_size: int = 9
    _storage: dict[int, OrderedDict[str, str]] = field(default_factory=dict)

    def add(self, user_id: int, model_id: str, model_title: str) -> None:
        """Add or update a model for a user. Most recent is first."""
        if user_id not in self._storage:
            self._storage[user_id] = OrderedDict()
        
        user_models = self._storage[user_id]
        
        # Remove if exists (to re-add at end)
        if model_id in user_models:
            del user_models[model_id]
        
        # Add to end (most recent)
        user_models[model_id] = model_title
        
        # Evict oldest if over limit
        while len(user_models) > self.max_size:
            user_models.popitem(last=False)

    def get(self, user_id: int) -> list[tuple[str, str]]:
        """Get recent models for user as [(model_id, title), ...]. Most recent first."""
        if user_id not in self._storage:
            return []
        
        # Return in reverse order (most recent first)
        items = list(self._storage[user_id].items())
        items.reverse()
        return items

    def clear(self, user_id: int) -> None:
        """Clear recent models for a user."""
        self._storage.pop(user_id, None)
