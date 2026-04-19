"""
Rutas para el mÃ³dulo de Seguimiento de Requerimientos (Kanban)
Flujo: Programar Visita â†’ Registrar Requerimientos â†’ GestiÃ³n Kanban
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import uuid

from app.firebase_config import db
from app.auth_system.dependencies import get_current_user

router = APIRouter(prefix="/seguimiento", tags=["Seguimiento de Requerimientos"])

# Zona horaria Colombia (UTC-5)
_COL_TZ = timezone(timedelta(hours=-5))

def now_colombia() -> datetime:
    """Retorna la hora actual en zona horaria de Colombia (America/Bogota, UTC-5)."""
    return datetime.now(_COL_TZ)


# ==================== MODELOS ====================

class CentroGestorOut(BaseModel):
    id: str
    nombre: str
    sigla: str
    color: str


class ColaboradorOut(BaseModel):
    id: str
    nombre: str
    email: str
    telefono: str
    cargo: str
    centro_gestor: str


class EnlaceOut(BaseModel):
    id: str
    nombre: str
    email: str
    telefono: str
    cargo: str
    centro_gestor_id: str
    centro_gestor_nombre: str
    dependencia: Optional[str] = None
    activo: bool


class SolicitanteModel(BaseModel):
    id: Optional[str] = None
    nombre_completo: str
    cedula: str
    telefono: str
    email: str
    direccion: str
    barrio_vereda: str
    comuna_corregimiento: str


class EvidenciaModel(BaseModel):
    id: Optional[str] = None
    tipo: str
    url: str
    descripcion: str
    fecha: str


class RegistroAvanceModel(BaseModel):
    id: Optional[str] = None
    fecha: str
    autor: str
    descripcion: str
    estado_anterior: str
    estado_nuevo: str
    evidencias: List[EvidenciaModel] = []
    porcentaje_avance: int = 0


class RequerimientoOut(BaseModel):
    id: str
    visita_id: str
    solicitante: SolicitanteModel
    centros_gestores: List[str]
    descripcion: str
    observaciones: str
    direccion: str
    latitud: str
    longitud: str
    evidencia_fotos: List[str] = []
    estado: str
    encargado: Optional[str] = None
    enlace_id: Optional[str] = None
    enlace_nombre: Optional[str] = None
    fecha_propuesta_solucion: Optional[str] = None
    porcentaje_avance: int = 0
    prioridad: str = "media"
    historial: List[RegistroAvanceModel] = []
    numero_orfeo: Optional[str] = None
    fecha_radicado_orfeo: Optional[str] = None
    documento_peticion_url: Optional[str] = None
    documento_peticion_nombre: Optional[str] = None
    motivo_cancelacion: Optional[str] = None
    documento_cancelacion_url: Optional[str] = None
    documento_cancelacion_nombre: Optional[str] = None
    created_at: str
    updated_at: str


class VisitaProgramadaOut(BaseModel):
    id: str
    upid: str
    unidad_proyecto: dict
    fecha_visita: str
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    estado: str
    colaboradores: List[dict] = []
    observaciones: Optional[str] = None
    created_at: str
    updated_at: str


class ProgramarVisitaBody(BaseModel):
    upid: str
    unidad_proyecto: dict
    fecha_visita: str
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    colaboradores: List[str] = []
    observaciones: Optional[str] = None


class ActualizarEstadoVisitaBody(BaseModel):
    estado: str


class CrearRequerimientoBody(BaseModel):
    visita_id: str
    solicitante: SolicitanteModel
    centros_gestores: List[str]
    descripcion: str
    observaciones: str
    direccion: str
    latitud: str
    longitud: str
    evidencia_fotos: List[str] = []
    prioridad: str = "media"


class CambiarEstadoBody(BaseModel):
    estado: str
    descripcion: str
    autor: str
    porcentaje_avance: int = 0
    evidencias: List[EvidenciaModel] = []


class AsignarEncargadoBody(BaseModel):
    encargado: str


class AsignarEnlaceBody(BaseModel):
    enlace_id: str
    enlace_nombre: str


# ==================== DATOS INICIALES (CatÃ¡logos) ====================

# Centros gestores disponibles (catÃ¡logo base)
_CENTROS_GESTORES_DEFAULT = [
    {"id": "dagma", "nombre": "DAGMA", "sigla": "DAGMA", "color": "#22c55e"},
    {"id": "emcali", "nombre": "EMCALI", "sigla": "EMCALI", "color": "#3b82f6"},
    {"id": "stt", "nombre": "SecretarÃ­a de TrÃ¡nsito", "sigla": "STT", "color": "#f59e0b"},
    {"id": "svsp", "nombre": "SecretarÃ­a de Vivienda", "sigla": "SVSP", "color": "#8b5cf6"},
    {"id": "salud", "nombre": "SecretarÃ­a de Salud", "sigla": "Salud", "color": "#ef4444"},
    {"id": "educacion", "nombre": "SecretarÃ­a de EducaciÃ³n", "sigla": "Educ.", "color": "#06b6d4"},
    {"id": "infraestructura", "nombre": "Infraestructura y ValorizaciÃ³n", "sigla": "IyV", "color": "#f97316"},
    {"id": "cultura", "nombre": "SecretarÃ­a de Cultura", "sigla": "Cultura", "color": "#ec4899"},
    {"id": "recreacion", "nombre": "IMRD", "sigla": "IMRD", "color": "#84cc16"},
    {"id": "sspd", "nombre": "SecretarÃ­a de Seguridad", "sigla": "SSPD", "color": "#6b7280"},
    {"id": "dps", "nombre": "SecretarÃ­a de Desarrollo", "sigla": "DPS", "color": "#14b8a6"},
    {"id": "planeacion", "nombre": "PlaneaciÃ³n Municipal", "sigla": "Planeac.", "color": "#a78bfa"},
    {"id": "bomberos", "nombre": "Cuerpo de Bomberos", "sigla": "Bomberos", "color": "#dc2626"},
    {"id": "alcaldia", "nombre": "AlcaldÃ­a de Cali", "sigla": "AlcaldÃ­a", "color": "#1e40af"},
]


# ==================== HELPER ====================

def _doc_to_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    return data


# ==================== CENTROS GESTORES ====================

@router.get(
    "/centros-gestores",
    summary="ðŸ“‹ GET | CatÃ¡logo de Centros Gestores",
    response_model=List[CentroGestorOut],
)
async def get_centros_gestores(current_user: dict = Depends(get_current_user)):
    """
    Retorna el catÃ¡logo de entidades/organismos de la alcaldÃ­a.
    Primero intenta leer desde la colecciÃ³n 'centros_gestores' en Firestore;
    si estÃ¡ vacÃ­a, devuelve el catÃ¡logo base incorporado.
    """
    try:
        docs = list(db.collection("centros_gestores").stream())
        if docs:
            return [_doc_to_dict(d) for d in docs]
        return _CENTROS_GESTORES_DEFAULT
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo centros gestores: {str(e)}")


# ==================== COLABORADORES ====================

@router.get(
    "/colaboradores",
    summary="ðŸ‘¥ GET | Colaboradores del grupo operativo",
    response_model=List[ColaboradorOut],
)
async def get_colaboradores(current_user: dict = Depends(get_current_user)):
    """
    Retorna la lista de colaboradores del grupo operativo almacenados en Firestore.
    """
    try:
        docs = list(db.collection("colaboradores").order_by("nombre").stream())
        return [_doc_to_dict(d) for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo colaboradores: {str(e)}")


# ==================== VISITAS PROGRAMADAS ====================

@router.get(
    "/visitas",
    summary="ðŸ—“ï¸ GET | Listar visitas programadas",
    response_model=List[VisitaProgramadaOut],
)
async def get_visitas(
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    upid: Optional[str] = Query(None, description="Filtrar por ID de unidad de proyecto"),
    current_user: dict = Depends(get_current_user),
):
    """
    Obtiene todas las visitas programadas desde Firestore, con filtros opcionales.
    """
    try:
        query = db.collection("visitas_programadas").order_by("created_at", direction="DESCENDING")
        docs = list(query.stream())
        result = [_doc_to_dict(d) for d in docs]

        if estado:
            result = [v for v in result if v.get("estado") == estado]
        if upid:
            result = [v for v in result if v.get("upid") == upid]

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo visitas: {str(e)}")


@router.post(
    "/visitas",
    summary="ðŸ—“ï¸ POST | Programar nueva visita",
    response_model=VisitaProgramadaOut,
    status_code=201,
)
async def programar_visita(
    body: ProgramarVisitaBody,
    current_user: dict = Depends(get_current_user),
):
    """
    Crea una nueva visita programada en Firestore.
    """
    try:
        now = now_colombia().isoformat()

        # Resolver colaboradores si se envÃ­an IDs
        colaboradores_data = []
        if body.colaboradores:
            for col_id in body.colaboradores:
                col_doc = db.collection("colaboradores").document(col_id).get()
                if col_doc.exists:
                    col_dict = col_doc.to_dict() or {}
                    col_dict["id"] = col_doc.id
                    colaboradores_data.append(col_dict)

        visita_data = {
            "upid": body.upid,
            "unidad_proyecto": body.unidad_proyecto,
            "fecha_visita": body.fecha_visita,
            "hora_inicio": body.hora_inicio,
            "hora_fin": body.hora_fin,
            "estado": "programada",
            "colaboradores": colaboradores_data,
            "observaciones": body.observaciones,
            "created_at": now,
            "updated_at": now,
        }

        doc_ref = db.collection("visitas_programadas").document()
        doc_ref.set(visita_data)

        visita_data["id"] = doc_ref.id
        return visita_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error programando visita: {str(e)}")


@router.patch(
    "/visitas/{visita_id}/estado",
    summary="ðŸ—“ï¸ PATCH | Actualizar estado de visita",
    response_model=VisitaProgramadaOut,
)
async def actualizar_estado_visita(
    visita_id: str,
    body: ActualizarEstadoVisitaBody,
    current_user: dict = Depends(get_current_user),
):
    """
    Actualiza el estado de una visita programada.
    """
    estados_validos = ["programada", "en-curso", "finalizada", "cancelada"]
    if body.estado not in estados_validos:
        raise HTTPException(
            status_code=400,
            detail=f"Estado invÃ¡lido. Debe ser uno de: {', '.join(estados_validos)}"
        )

    try:
        doc_ref = db.collection("visitas_programadas").document(visita_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail=f"Visita {visita_id} no encontrada")

        now = now_colombia().isoformat()
        doc_ref.update({"estado": body.estado, "updated_at": now})

        updated = doc.to_dict() or {}
        updated["id"] = visita_id
        updated["estado"] = body.estado
        updated["updated_at"] = now
        return updated
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error actualizando visita: {str(e)}")


# ==================== REQUERIMIENTOS ====================

@router.get(
    "/requerimientos",
    summary="ðŸ“‹ GET | Listar requerimientos",
    response_model=List[RequerimientoOut],
)
async def get_requerimientos(
    visita_id: Optional[str] = Query(None, description="Filtrar por ID de visita"),
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    current_user: dict = Depends(get_current_user),
):
    """
    Obtiene los requerimientos de seguimiento desde Firestore.
    """
    try:
        query = db.collection("requerimientos_seguimiento").order_by("created_at", direction="DESCENDING")
        docs = list(query.stream())
        result = [_doc_to_dict(d) for d in docs]

        if visita_id:
            result = [r for r in result if r.get("visita_id") == visita_id]
        if estado:
            result = [r for r in result if r.get("estado") == estado]

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo requerimientos: {str(e)}")


@router.post(
    "/requerimientos",
    summary="ðŸ“‹ POST | Crear requerimiento de seguimiento",
    response_model=RequerimientoOut,
    status_code=201,
)
async def crear_requerimiento(
    body: CrearRequerimientoBody,
    current_user: dict = Depends(get_current_user),
):
    """
    Crea un nuevo requerimiento de seguimiento en Firestore.
    """
    try:
        now = now_colombia().isoformat()
        uid = current_user.get("uid", "sistema")
        email = current_user.get("email", "sistema")
        autor = current_user.get("full_name") or email

        registro_inicial: dict = {
            "id": f"hist-{uuid.uuid4().hex}",
            "fecha": now,
            "autor": autor,
            "descripcion": "Requerimiento registrado en campo",
            "estado_anterior": "nuevo",
            "estado_nuevo": "nuevo",
            "evidencias": [],
            "porcentaje_avance": 0,
        }

        req_data = {
            "visita_id": body.visita_id,
            "solicitante": body.solicitante.model_dump(),
            "centros_gestores": body.centros_gestores,
            "descripcion": body.descripcion,
            "observaciones": body.observaciones,
            "direccion": body.direccion,
            "latitud": body.latitud,
            "longitud": body.longitud,
            "evidencia_fotos": body.evidencia_fotos,
            "estado": "nuevo",
            "encargado": None,
            "enlace_id": None,
            "enlace_nombre": None,
            "fecha_propuesta_solucion": None,
            "porcentaje_avance": 0,
            "prioridad": body.prioridad,
            "historial": [registro_inicial],
            "numero_orfeo": None,
            "fecha_radicado_orfeo": None,
            "documento_peticion_url": None,
            "documento_peticion_nombre": None,
            "motivo_cancelacion": None,
            "documento_cancelacion_url": None,
            "documento_cancelacion_nombre": None,
            "created_by": uid,
            "created_at": now,
            "updated_at": now,
        }

        doc_ref = db.collection("requerimientos_seguimiento").document()
        doc_ref.set(req_data)

        req_data["id"] = doc_ref.id
        return req_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creando requerimiento: {str(e)}")


@router.patch(
    "/requerimientos/{req_id}/estado",
    summary="ðŸ“‹ PATCH | Cambiar estado de requerimiento",
    response_model=RequerimientoOut,
)
async def cambiar_estado_requerimiento(
    req_id: str,
    body: CambiarEstadoBody,
    current_user: dict = Depends(get_current_user),
):
    """
    Cambia el estado de un requerimiento y agrega una entrada al historial.
    """
    estados_validos = ["nuevo", "radicado", "en-gestion", "asignado", "en-proceso", "resuelto", "cerrado", "cancelado"]
    if body.estado not in estados_validos:
        raise HTTPException(
            status_code=400,
            detail=f"Estado invÃ¡lido. Debe ser uno de: {', '.join(estados_validos)}"
        )

    try:
        doc_ref = db.collection("requerimientos_seguimiento").document(req_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail=f"Requerimiento {req_id} no encontrado")

        data = doc.to_dict() or {}
        now = now_colombia().isoformat()

        nuevo_registro = {
            "id": f"hist-{uuid.uuid4().hex}",
            "fecha": now,
            "autor": body.autor,
            "descripcion": body.descripcion,
            "estado_anterior": data.get("estado", "nuevo"),
            "estado_nuevo": body.estado,
            "evidencias": [e.model_dump() for e in body.evidencias],
            "porcentaje_avance": body.porcentaje_avance,
        }

        historial = data.get("historial", [])
        historial.append(nuevo_registro)

        updates = {
            "estado": body.estado,
            "porcentaje_avance": body.porcentaje_avance,
            "historial": historial,
            "updated_at": now,
        }
        doc_ref.update(updates)

        data.update(updates)
        data["id"] = req_id
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cambiando estado: {str(e)}")


@router.patch(
    "/requerimientos/{req_id}/encargado",
    summary="ðŸ“‹ PATCH | Asignar encargado a requerimiento",
    response_model=RequerimientoOut,
)
async def asignar_encargado(
    req_id: str,
    body: AsignarEncargadoBody,
    current_user: dict = Depends(get_current_user),
):
    """
    Asigna un encargado del centro gestor a un requerimiento.
    """
    try:
        doc_ref = db.collection("requerimientos_seguimiento").document(req_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail=f"Requerimiento {req_id} no encontrado")

        now = now_colombia().isoformat()
        doc_ref.update({"encargado": body.encargado, "updated_at": now})

        data = doc.to_dict() or {}
        data["id"] = req_id
        data["encargado"] = body.encargado
        data["updated_at"] = now
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error asignando encargado: {str(e)}")


@router.patch(
    "/requerimientos/{req_id}/enlace",
    summary="ðŸ“‹ PATCH | Asignar enlace a requerimiento",
    response_model=RequerimientoOut,
)
async def asignar_enlace(
    req_id: str,
    body: AsignarEnlaceBody,
    current_user: dict = Depends(get_current_user),
):
    """
    Asigna un enlace del organismo a un requerimiento.
    """
    try:
        doc_ref = db.collection("requerimientos_seguimiento").document(req_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail=f"Requerimiento {req_id} no encontrado")

        now = now_colombia().isoformat()
        doc_ref.update({
            "enlace_id": body.enlace_id,
            "enlace_nombre": body.enlace_nombre,
            "updated_at": now,
        })

        data = doc.to_dict() or {}
        data["id"] = req_id
        data["enlace_id"] = body.enlace_id
        data["enlace_nombre"] = body.enlace_nombre
        data["updated_at"] = now
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error asignando enlace: {str(e)}")


# ==================== ENLACES ====================

@router.get(
    "/enlaces",
    summary="ðŸ“‡ GET | Directorio de enlaces",
    response_model=List[EnlaceOut],
)
async def get_enlaces(
    centro_gestor_id: Optional[str] = Query(None, description="Filtrar por centro gestor"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo"),
    current_user: dict = Depends(get_current_user),
):
    """
    Obtiene el directorio de representantes/enlaces por organismo desde Firestore.
    """
    try:
        query = db.collection("enlaces").order_by("nombre")
        docs = list(query.stream())
        result = [_doc_to_dict(d) for d in docs]

        if centro_gestor_id:
            result = [e for e in result if e.get("centro_gestor_id") == centro_gestor_id]
        if activo is not None:
            result = [e for e in result if e.get("activo") == activo]

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo enlaces: {str(e)}")

