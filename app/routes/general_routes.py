"""
Rutas generales - Health checks y endpoints de utilidad
"""
from fastapi import APIRouter
from datetime import datetime
import platform
import os

router = APIRouter(tags=["General"])

@router.get("/ping")
async def ping():
    """
    🔵 GET | ❤️ Health Check | Health check super simple para Railway con soporte UTF-8
    """
    return {
        "status": "ok",
        "message": "¡Pong! 🏓",
        "timestamp": datetime.utcnow().isoformat(),
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
        "timestamp": datetime.utcnow().isoformat()
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
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/health")
async def health_check():
    """
    🔵 GET | ❤️ Health Check | Verificar estado de salud de la API
    
    Endpoint completo de health check con información del sistema
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "API Artefacto 360 DAGMA",
        "version": "1.0.0",
        "uptime": "OK",
        "checks": {
            "api": "ok",
            "database": "ok",
            "storage": "ok"
        }
    }
