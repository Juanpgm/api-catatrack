"""
Push notification routes — Web Push (VAPID) for installed PWAs.

iOS Safari 16.4+ requires the site to be installed (Add to Home Screen) before
the Notification permission prompt can be shown. The backend signs payloads
with VAPID and pushes via the standard Web Push protocol to Apple's APNs
(transparent to us).

Required env vars (see CONFIGURACION_VARIABLES_ENTORNO.md):
  VAPID_PUBLIC_KEY   — base64url ECDSA public key (uncompressed P-256)
  VAPID_PRIVATE_KEY  — base64url ECDSA private key (PKCS8 or raw)
  VAPID_SUBJECT      — mailto:contact@... or https://app-url

Generate keys once:
  python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); \
             print('PUB', v.public_key); print('PRIV', v.private_key)"
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth_system.dependencies import get_current_user
from app.firebase_config import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["Push Notifications"])

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@catatrack.local")

_PWPUSH_AVAILABLE = True
try:
    from pywebpush import WebPushException, webpush  # type: ignore
except ImportError:  # pragma: no cover
    _PWPUSH_AVAILABLE = False
    WebPushException = Exception  # type: ignore

    def webpush(*args, **kwargs):  # type: ignore
        raise RuntimeError("pywebpush no instalado — agrega a requirements.txt")


# ---------- Models ----------

class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    endpoint: str = Field(..., min_length=10)
    keys: PushKeys
    expiration_time: Optional[int] = None


class SubscribeResponse(BaseModel):
    success: bool
    message: str


class PushPayload(BaseModel):
    title: str = Field(..., max_length=120)
    body: str = Field(..., max_length=500)
    url: Optional[str] = Field(None, description="URL para abrir al click")
    tag: Optional[str] = None
    icon: Optional[str] = "/pwa-192x192.png"
    badge: Optional[str] = "/pwa-192x192.png"
    data: Optional[Dict[str, Any]] = None


# ---------- Endpoints ----------

@router.get("/vapid-public-key")
def get_vapid_public_key() -> Dict[str, str]:
    """Returns the VAPID public key (safe to expose)."""
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="VAPID no configurado en el servidor")
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/subscribe", response_model=SubscribeResponse)
def subscribe(subscription: PushSubscription, current_user=Depends(get_current_user)) -> SubscribeResponse:
    """Save the browser PushSubscription for the authenticated user."""
    uid = current_user.get("uid") if isinstance(current_user, dict) else current_user.uid
    if not uid:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")

    try:
        doc_ref = db.collection("push_subscriptions").document(uid)
        doc_ref.set(
            {
                "endpoint": subscription.endpoint,
                "keys": subscription.keys.model_dump(),
                "expiration_time": subscription.expiration_time,
                "uid": uid,
            },
            merge=True,
        )
        return SubscribeResponse(success=True, message="Suscripción guardada")
    except Exception as exc:  # pragma: no cover
        logger.exception("Error guardando suscripción push: %s", exc)
        raise HTTPException(status_code=500, detail="Error al guardar suscripción") from exc


@router.delete("/unsubscribe", response_model=SubscribeResponse)
def unsubscribe(current_user=Depends(get_current_user)) -> SubscribeResponse:
    """Remove the saved PushSubscription for the authenticated user."""
    uid = current_user.get("uid") if isinstance(current_user, dict) else current_user.uid
    if not uid:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")
    try:
        db.collection("push_subscriptions").document(uid).delete()
        return SubscribeResponse(success=True, message="Suscripción eliminada")
    except Exception as exc:  # pragma: no cover
        logger.exception("Error eliminando suscripción push: %s", exc)
        raise HTTPException(status_code=500, detail="Error al eliminar suscripción") from exc


@router.post("/test", response_model=SubscribeResponse)
def send_test_to_self(payload: PushPayload, current_user=Depends(get_current_user)) -> SubscribeResponse:
    """Send a push to the caller's own device — handy for debugging."""
    uid = current_user.get("uid") if isinstance(current_user, dict) else current_user.uid
    if not uid:
        raise HTTPException(status_code=401, detail="Usuario no autenticado")
    delivered = send_push(uid, payload.model_dump(exclude_none=True))
    if not delivered:
        raise HTTPException(status_code=404, detail="No hay suscripción activa para este usuario")
    return SubscribeResponse(success=True, message="Notificación enviada")


# ---------- Helper exposed to other routes ----------

def send_push(uid: str, payload: Dict[str, Any]) -> bool:
    """
    Send a Web Push to the given user. Returns True if delivered, False if no
    subscription is on file. Raises only on unexpected errors.

    Other routes (e.g. requirement assignment) should call this fire-and-forget.
    """
    if not _PWPUSH_AVAILABLE:
        logger.warning("pywebpush no disponible — push omitido para uid=%s", uid)
        return False
    if not (VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY):
        logger.warning("VAPID no configurado — push omitido para uid=%s", uid)
        return False

    doc = db.collection("push_subscriptions").document(uid).get()
    if not doc.exists:
        return False

    sub = doc.to_dict() or {}
    if not sub.get("endpoint") or not sub.get("keys"):
        return False

    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=24 * 3600,
        )
        return True
    except WebPushException as exc:
        # 404 / 410 = subscription gone — clean up
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in (404, 410):
            logger.info("Suscripción push expirada para uid=%s — eliminando", uid)
            db.collection("push_subscriptions").document(uid).delete()
            return False
        logger.warning("WebPushException uid=%s status=%s: %s", uid, status_code, exc)
        return False
    except Exception as exc:  # pragma: no cover
        logger.exception("Error inesperado enviando push uid=%s: %s", uid, exc)
        return False
