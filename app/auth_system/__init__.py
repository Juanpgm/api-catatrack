"""Sistema de autenticación/autorización (RBAC)."""

from .constants import DEFAULT_USER_ROLE, ROLES
from .permissions import get_user_permissions, require_permission, require_any_permission
from .dependencies import get_current_user

__all__ = [
    "DEFAULT_USER_ROLE",
    "ROLES",
    "get_user_permissions",
    "require_permission",
    "require_any_permission",
    "get_current_user",
]
