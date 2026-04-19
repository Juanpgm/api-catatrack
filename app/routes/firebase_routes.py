"""
Rutas de Firebase - Status y gestiÃ³n de colecciones
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone, timedelta
from app.firebase_config import db

router = APIRouter(tags=["Firebase"])

# Zona horaria Colombia (UTC-5)
_COL_TZ = timezone(timedelta(hours=-5))

def now_colombia() -> datetime:
    """Retorna la hora actual en zona horaria de Colombia (America/Bogota, UTC-5)."""
    return datetime.now(_COL_TZ)

@router.get("/firebase/status")
async def firebase_status():
    """
    Verificar estado de la conexiÃ³n con Firebase
    """
    try:
        # Verificar conexiÃ³n intentando acceder a Firestore
        collections = db.collections()
        collection_names = [col.id for col in collections]
        return {
            "status": "connected",
            "firestore": "available",
            "storage": "available",  # TODO: Verificar storage si es necesario
            "project_id": "dagma-85aad",
            "collections_count": len(collection_names),
            "timestamp": now_colombia().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Firebase no disponible: {str(e)}")

@router.get("/firebase/collections")
async def get_firebase_collections():
    """
    Obtener informaciÃ³n completa de todas las colecciones de Firestore
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
                "size_bytes": 0  # TODO: Calcular tamaÃ±o si es necesario
            })
        return {
            "success": True,
            "collections": collections_info,
            "timestamp": now_colombia().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo colecciones: {str(e)}")

@router.get("/firebase/collections/summary")
async def get_firebase_collections_summary():
    """
    Obtener resumen estadÃ­stico de las colecciones
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
            "total_size_mb": 0.0,  # TODO: Calcular tamaÃ±o total
            "timestamp": now_colombia().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo resumen: {str(e)}")


@router.get("/obtener_directorio_contactos")
async def obtener_directorio_contactos():
    """
    ðŸ”µ GET | Obtener todos los contactos del directorio desde la colecciÃ³n 'directorio_contactos'
    """
    try:
        docs = db.collection("directorio_contactos").stream()
        contactos = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            contactos.append(data)
        return {
            "success": True,
            "total": len(contactos),
            "contactos": contactos,
            "timestamp": now_colombia().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo directorio de contactos: {str(e)}")

