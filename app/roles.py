from enum import Enum
from app.config import Config


class Role(Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    NONE = "none"


def get_user_role(user_id: int, config: Config) -> Role:
    """Get the role for a user ID. Admin > Editor > Viewer > None."""
    if user_id in config.admin_ids:
        return Role.ADMIN
    if user_id in config.editor_ids:
        return Role.EDITOR
    if user_id in config.viewer_ids:
        return Role.VIEWER
    return Role.NONE


def is_authorized(user_id: int, config: Config) -> bool:
    """Check if user has any access (admin, editor, or viewer)."""
    return get_user_role(user_id, config) != Role.NONE


def can_edit(user_id: int, config: Config) -> bool:
    """Check if user can create/edit/delete (admin or editor)."""
    role = get_user_role(user_id, config)
    return role in (Role.ADMIN, Role.EDITOR)


def is_admin(user_id: int, config: Config) -> bool:
    """Check if user is admin."""
    return get_user_role(user_id, config) == Role.ADMIN
