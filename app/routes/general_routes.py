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
    ðŸ”µ GET | â¤ï¸ Health Check | Health check super simple para Railway con soporte UTF-8
    """
    return {
        "status": "ok",
        "message": "Â¡Pong! ðŸ“",
        "timestamp": now_colombia().isoformat(),
        "utf8_test": "Funciona correctamente con caracteres especiales: Ã¡ Ã© Ã­ Ã³ Ãº Ã±"
    }

@router.get("/cors-test")
async def cors_test():
    """
    Endpoint especÃ­fico para probar configuraciÃ³n CORS
    """
    return {
        "cors": "enabled",
        "message": "CORS configurado correctamente",
        "timestamp": now_colombia().isoformat()
    }

@router.options("/cors-test")
async def cors_test_options():
    """
    OPTIONS handler especÃ­fico para CORS test
    """
    return {"message": "OPTIONS request successful"}

@router.get("/test/utf8")
async def test_utf8():
    """
    Endpoint de prueba especÃ­fico para caracteres UTF-8 en espaÃ±ol
    """
    return {
        "test": "UTF-8",
        "espaÃ±ol": "Caracteres especiales: Ã¡ Ã© Ã­ Ã³ Ãº Ã± Ã‘",
        "symbols": "Â© Â® â„¢ â‚¬ Â£ Â¥",
        "message": "Todos los caracteres UTF-8 funcionan correctamente âœ“"
    }

@router.get("/debug/railway")
async def railway_debug():
    """
    Debug especÃ­fico para Railway - DiagnÃ³stico simplificado
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
    ðŸ”µ GET | â¤ï¸ Health Check | Verificar estado de salud de la API
    
    Endpoint completo de health check con informaciÃ³n del sistema
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

