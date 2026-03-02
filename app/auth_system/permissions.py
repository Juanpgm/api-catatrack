"""Utilidades para resolver y validar permisos de usuarios."""

from datetime import datetime, timezone
from typing import Iterable, List

from .constants import ROLES


def _normalize_list(raw_value) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        value = raw_value.strip()
        return [value] if value else []
    if isinstance(raw_value, Iterable):
        values: List[str] = []
        for item in raw_value:
            normalized = str(item).strip()
            if normalized:
                values.append(normalized)
        return values
    value = str(raw_value).strip()
    return [value] if value else []


def validate_permission(user_permissions: List[str], required_permission: str) -> bool:
    if "*" in user_permissions:
        return True
    if required_permission in user_permissions:
        return True

    parts = required_permission.split(":")
    if len(parts) >= 2:
        wildcard = f"{parts[0]}:*"
        return wildcard in user_permissions

    return False


def get_user_permissions(user_data: dict) -> List[str]:
    user_roles = _normalize_list(user_data.get("roles", []))
    if "super_admin" in user_roles:
        return ["*"]

    permissions = set()

    for role in user_roles:
        role_cfg = ROLES.get(role)
        if role_cfg:
            permissions.update(role_cfg.get("permissions", []))

    temporary_permissions = user_data.get("temporary_permissions", [])
    now = datetime.now(timezone.utc)

    for temp_perm in temporary_permissions:
        permission = str(temp_perm.get("permission", "")).strip()
        expires_at = temp_perm.get("expires_at")
        if not permission:
            continue

        if isinstance(expires_at, datetime):
            expires_dt = expires_at
        elif isinstance(expires_at, str):
            try:
                expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            continue

        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)

        if expires_dt > now:
            permissions.add(permission)

    explicit_permissions = _normalize_list(user_data.get("permissions", []))
    permissions.update(explicit_permissions)

    return sorted(list(permissions))


def require_permission(current_user: dict, permission: str):
    user_permissions = current_user.get("permissions", [])
    if not validate_permission(user_permissions, permission):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=f"Permiso denegado: {permission}")


def require_any_permission(current_user: dict, permissions: List[str]):
    user_permissions = current_user.get("permissions", [])
    if "*" in user_permissions:
        return

    if not any(validate_permission(user_permissions, permission) for permission in permissions):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Permiso denegado")
