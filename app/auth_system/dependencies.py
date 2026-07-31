"""Dependencias de autenticación para FastAPI."""

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
    token = credentials.credentials
    try:
        decoded_token = auth_client.verify_id_token(token)
    except auth_client.CertificateFetchError as exc:
        # Fallo de red al buscar las claves públicas de Google: no dice nada
        # sobre la validez del token del usuario. Tratarlo como 401 dispara
        # un logout indebido en el frontend (ApiClient.fetchWithRetry sólo
        # reintenta en 401, refrescando y luego cerrando sesión si vuelve a
        # fallar) por una falla transitoria de infraestructura, no de sesión.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación no disponible temporalmente, intente de nuevo",
        ) from exc
    except (ValueError, auth_client.InvalidIdTokenError) as exc:
        # Cubre token vacío/mal formado (ValueError) y, vía subclases de
        # InvalidIdTokenError, expirado/revocado/usuario deshabilitado.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

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


def build_audit_log(action: str, actor: dict, details: dict | None = None) -> dict:
    return {
        "timestamp": now_colombia(),
        "action": action,
        "user_uid": actor.get("uid"),
        "user_email": actor.get("email"),
        "details": details or {},
    }

