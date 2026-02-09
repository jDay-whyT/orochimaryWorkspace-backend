from app.config import Config


def is_authorized(user_id: int, config: Config) -> bool:
    """Read access is open to everyone."""
    return True


def can_edit(user_id: int, config: Config) -> bool:
    """Check if user can create/edit/delete (in ALLOWED_EDITORS)."""
    return user_id in config.allowed_editors


def is_editor(user_id: int, config: Config) -> bool:
    """Backward-compatible alias for edit checks."""
    return can_edit(user_id, config)


def is_editor_or_admin(user_id: int, config: Config) -> bool:
    """Backward-compatible alias for edit checks."""
    return can_edit(user_id, config)
