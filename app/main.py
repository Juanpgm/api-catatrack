"""
API Artefacto 360 DAGMA - Main Application
Configuración basada en gestor_proyecto_api
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Configurar logging de auditoría
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('audit.log'),
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
    auth_routes
)

# Crear aplicación FastAPI
app = FastAPI(
    title="API Artefacto 360 DAGMA",
    description="API para gestión de artefacto de captura 360 con Firebase/Firestore - Soporte completo UTF-8 🇪🇸",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configurar rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Agregar middleware de rate limiting
app.add_middleware(SlowAPIMiddleware)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Desarrollo local
        "http://localhost:3000",      # React default
        "http://localhost:3001",      # React alternate
        "http://localhost:5173",      # Vite default
        "http://localhost:5174",      # Vite alternate
        "http://localhost:5175",      # Vite alternate
        # Producción
        "https://web-production-2d737.up.railway.app",  # Railway API
        "https://dagma-360-capture-frontend.vercel.app",  # Frontend Vercel
        "https://tu-dominio-produccion.com"  # Dominio custom adicional
    ],
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

# Manejador de errores global
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": str(exc),
            "type": type(exc).__name__
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
