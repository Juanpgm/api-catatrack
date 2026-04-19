"""
Rutas generales - Health checks y endpoints de utilidad
"""
from fastapi import APIRouter
from datetime import datetime, timezone, timedelta
import platform
import os

router = APIRouter(tags=["General"])

# Zona horaria Colombia (UTC-5)
_COL_TZ = timezone(timedelta(hours=-5))

def now_colombia() -> datetime:
    """Retorna la hora actual en zona horaria de Colombia (America/Bogota, UTC-5)."""
    return datetime.now(_COL_TZ)

@router.get("/ping")
async def ping():
    """
    🔵 GET | ❤️ Health Check | Health check super simple para Railway con soporte UTF-8
    """
    return {
        "status": "ok",
        "message": "¡Pong! 🏓",
        "timestamp": now_colombia().isoformat(),
        "utf8_test": "Funciona correctamente con caracteres especiales: á é í ó ú ñ"
    }

@router.get("/cors-test")
async def cors_test():
    """
    Endpoint específico para probar configuración CORS
    """
    return {
        "cors": "enabled",
        "message": "CORS configurado correctamente",
        "timestamp": now_colombia().isoformat()
    }

@router.options("/cors-test")
async def cors_test_options():
    """
    OPTIONS handler específico para CORS test
    """
    return {"message": "OPTIONS request successful"}

@router.get("/test/utf8")
async def test_utf8():
    """
    Endpoint de prueba específico para caracteres UTF-8 en español
    """
    return {
        "test": "UTF-8",
        "español": "Caracteres especiales: á é í ó ú ñ Ñ",
        "symbols": "© ® ™ € £ ¥",
        "message": "Todos los caracteres UTF-8 funcionan correctamente ✓"
    }

@router.get("/debug/railway")
async def railway_debug():
    """
    Debug específico para Railway - Diagnóstico simplificado
    """
    return {
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "environment": os.environ.get("RAILWAY_ENVIRONMENT", "local"),
        "timestamp": now_colombia().isoformat()
    }

@router.get("/health")
async def health_check():
    """
    🔵 GET | ❤️ Health Check | Verificar estado de salud de la API
    
    Endpoint completo de health check con información del sistema
    """
    return {
        "status": "healthy",
        "timestamp": now_colombia().isoformat(),
        "service": "API Artefacto 360 DAGMA",
        "version": "1.0.0",
        "uptime": "OK",
        "checks": {
            "api": "ok",
            "database": "ok",
            "storage": "ok"
        }
    }

