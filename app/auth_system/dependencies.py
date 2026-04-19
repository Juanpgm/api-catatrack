"""Dependencias de autenticaciÃ³n para FastAPI."""

from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.firebase_config import auth_client, db
from .permissions import get_user_permissions

security = HTTPBearer()

# Zona horaria Colombia (UTC-5)
_COL_TZ = timezone(timedelta(hours=-5))

def now_colombia() -> datetime:
    """Retorna la hora actual en zona horaria de Colombia (America/Bogota, UTC-5)."""
    return datetime.now(_COL_TZ)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    try:
        token = credentials.credentials
        decoded_token = auth_client.verify_id_token(token)
        uid = decoded_token["uid"]

        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado en la base de datos",
            )

        user_data = user_doc.to_dict() or {}
        user_data["uid"] = uid

        if not user_data.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario inactivo",
            )

        user_data["permissions"] = get_user_permissions(user_data)
        request.state.user_uid = uid
        request.state.user_email = user_data.get("email")

        return user_data

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invÃ¡lido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


def build_audit_log(action: str, actor: dict, details: dict | None = None) -> dict:
    return {
        "timestamp": now_colombia(),
        "action": action,
        "user_uid": actor.get("uid"),
        "user_email": actor.get("email"),
        "details": details or {},
    }

