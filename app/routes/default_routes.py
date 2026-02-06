"""
Rutas default - Endpoint raíz
"""
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def read_root():
    """
    Endpoint raíz con información básica de la API
    """
    return {
        "message": "API Task Tracker - Bienvenido",
        "version": "1.0.0",
        "status": "active",
        "documentation": "/docs"
    }
