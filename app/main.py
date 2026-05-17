"""
API Task Tracker - Main Application
"""
import logging
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Configurar logging de auditoría
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audit.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Importar configuración de Firebase
from app.firebase_config import db, auth_client

# Importar routers
from app.routes import (
    default_routes,
    general_routes,
    monitoring_routes,
    firebase_routes,
    artefacto_360_routes,
    auth_routes,
    seguimiento_routes,
)

# Crear aplicación FastAPI
app = FastAPI(
    title="API CataTrack",
    description="API para CataTrack - Sistema de seguimiento de requerimientos con Firebase/Firestore 🇨🇴",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


# Middleware ASGI puro para forzar charset=utf-8 en respuestas JSON
# (No usa BaseHTTPMiddleware para evitar problemas con streaming)
class UTF8JSONMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                ct_key = b"content-type"
                ct_val = headers.get(ct_key, b"")
                if b"application/json" in ct_val and b"charset" not in ct_val:
                    new_ct = ct_val + b"; charset=utf-8"
                    new_headers = [
                        (k, new_ct if k == ct_key else v)
                        for k, v in message.get("headers", [])
                    ]
                    message = {**message, "headers": new_headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)

app.add_middleware(UTF8JSONMiddleware)


def _get_allowed_origins() -> list[str]:
    default_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
    ]

    configured = os.getenv("CORS_ALLOW_ORIGINS", "")
    if not configured.strip():
        return default_origins

    parsed = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if not parsed:
        return default_origins

    return parsed

# Configurar rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

def _rate_limit_handler(request, exc: RateLimitExceeded):
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "detail": (
                f"Demasiadas solicitudes. Has superado el límite de peticiones. "
                f"Intenta de nuevo en {retry_after} segundo(s)."
            ),
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )

app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# Agregar middleware de rate limiting
app.add_middleware(SlowAPIMiddleware)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_origin_regex=os.getenv(
        "CORS_ALLOW_ORIGIN_REGEX",
        r"https://([a-zA-Z0-9-]+\.)?(railway\.app|vercel\.app|netlify\.app)$",
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar routers
app.include_router(default_routes.router)
app.include_router(general_routes.router)
app.include_router(monitoring_routes.router)
app.include_router(firebase_routes.router)
app.include_router(artefacto_360_routes.router)
app.include_router(auth_routes.router)
app.include_router(seguimiento_routes.router)

# Pre-carga opcional del modelo SLM de clasificación de centros gestores.
# Activar con la env var CLASSIFIER_PRELOAD=true (recomendado en Railway con
# volumen montado en /app/.cache/huggingface para evitar la descarga en cold-start).
@app.on_event("startup")
async def _precargar_clasificador():
    try:
        from app.classification.embeddings import precargar
        precargar()  # respeta CLASSIFIER_PRELOAD; no-op si está desactivado
    except Exception as e:
        logger.warning(f"⚠️ Preload del clasificador falló (continuando): {e}")

# Manejador de errores global
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": str(exc),
            "type": type(exc).__name__
        },
        media_type="application/json; charset=utf-8"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
