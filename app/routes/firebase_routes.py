"""
Rutas de Firebase - Status y gestión de colecciones
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from app.firebase_config import db

router = APIRouter(tags=["Firebase"])

@router.get("/firebase/status")
async def firebase_status():
    """
    Verificar estado de la conexión con Firebase
    """
    try:
        # Verificar conexión intentando acceder a Firestore
        collections = db.collections()
        collection_names = [col.id for col in collections]
        return {
            "status": "connected",
            "firestore": "available",
            "storage": "available",  # TODO: Verificar storage si es necesario
            "project_id": "dagma-85aad",
            "collections_count": len(collection_names),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Firebase no disponible: {str(e)}")

@router.get("/firebase/collections")
async def get_firebase_collections():
    """
    Obtener información completa de todas las colecciones de Firestore
    """
    try:
        collections = db.collections()
        collections_info = []
        for col in collections:
            docs = col.stream()
            doc_count = sum(1 for _ in docs)
            collections_info.append({
                "name": col.id,
                "document_count": doc_count,
                "size_bytes": 0  # TODO: Calcular tamaño si es necesario
            })
        return {
            "success": True,
            "collections": collections_info,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo colecciones: {str(e)}")

@router.get("/firebase/collections/summary")
async def get_firebase_collections_summary():
    """
    Obtener resumen estadístico de las colecciones
    """
    try:
        collections = db.collections()
        total_collections = 0
        total_documents = 0
        for col in collections:
            total_collections += 1
            docs = col.stream()
            total_documents += sum(1 for _ in docs)
        return {
            "success": True,
            "total_collections": total_collections,
            "total_documents": total_documents,
            "total_size_mb": 0.0,  # TODO: Calcular tamaño total
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo resumen: {str(e)}")
