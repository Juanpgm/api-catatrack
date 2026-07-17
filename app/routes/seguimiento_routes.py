"""
Rutas para el módulo de Seguimiento de Requerimientos (Kanban)
Flujo: Programar Visita → Registrar Requerimientos → Gestión Kanban
"""
from fastapi import APIRouter, HTTPException, Query, Depends, File, Form, UploadFile
from fastapi.responses import Response
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import uuid

from app.firebase_config import db
from app.auth_system.dependencies import get_current_user
from app.utils.pdf_generator import generar_reporte_visita
# Módulo unificado de S3 (single source: credenciales, bucket, key format,
# upload/delete/list/presign).
from app.utils import s3_storage

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


# ==================== DATOS INICIALES (Catálogos) ====================

# Centros gestores disponibles (catálogo base)
_CENTROS_GESTORES_DEFAULT = [
    {"id": "dagma", "nombre": "DAGMA", "sigla": "DAGMA", "color": "#22c55e"},
    {"id": "emcali", "nombre": "EMCALI", "sigla": "EMCALI", "color": "#3b82f6"},
    {"id": "stt", "nombre": "Secretaría de Tránsito", "sigla": "STT", "color": "#f59e0b"},
    {"id": "svsp", "nombre": "Secretaría de Vivienda", "sigla": "SVSP", "color": "#8b5cf6"},
    {"id": "salud", "nombre": "Secretaría de Salud", "sigla": "Salud", "color": "#ef4444"},
    {"id": "educacion", "nombre": "Secretaría de Educación", "sigla": "Educ.", "color": "#06b6d4"},
    {"id": "infraestructura", "nombre": "Infraestructura y Valorización", "sigla": "IyV", "color": "#f97316"},
    {"id": "cultura", "nombre": "Secretaría de Cultura", "sigla": "Cultura", "color": "#ec4899"},
    {"id": "recreacion", "nombre": "IMRD", "sigla": "IMRD", "color": "#84cc16"},
    {"id": "sspd", "nombre": "Secretaría de Seguridad", "sigla": "SSPD", "color": "#6b7280"},
    {"id": "dps", "nombre": "Secretaría de Desarrollo", "sigla": "DPS", "color": "#14b8a6"},
    {"id": "planeacion", "nombre": "Planeación Municipal", "sigla": "Planeac.", "color": "#a78bfa"},
    {"id": "bomberos", "nombre": "Cuerpo de Bomberos", "sigla": "Bomberos", "color": "#dc2626"},
    {"id": "alcaldia", "nombre": "Alcaldía de Cali", "sigla": "Alcaldía", "color": "#1e40af"},
]


# ==================== HELPER ====================

def _doc_to_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    return data


# ==================== CENTROS GESTORES ====================

@router.get(
    "/centros-gestores",
    summary="📋 GET | Catálogo de Centros Gestores",
    response_model=List[CentroGestorOut],
)
async def get_centros_gestores(current_user: dict = Depends(get_current_user)):
    """
    Retorna el catálogo de entidades/organismos de la alcaldía.
    Primero intenta leer desde la colección 'centros_gestores' en Firestore;
    si está vacía, devuelve el catálogo base incorporado.
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
    summary="👥 GET | Colaboradores del grupo operativo",
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
    summary="🗓️ GET | Listar visitas programadas",
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
    summary="🗓️ POST | Programar nueva visita",
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

        # Resolver colaboradores si se envían IDs
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
    summary="🗓️ PATCH | Actualizar estado de visita",
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
            detail=f"Estado inválido. Debe ser uno de: {', '.join(estados_validos)}"
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
    summary="📋 GET | Listar requerimientos",
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
    summary="📋 POST | Crear requerimiento de seguimiento",
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


@router.post(
    "/evidencias",
    summary="📷 POST | Subir evidencias fotográficas de Seguimiento",
    status_code=201,
)
async def subir_evidencias(
    archivos: List[UploadFile] = File(...),
    requerimiento_id: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Sube uno o más archivos de evidencia a S3 (módulo ``seguimiento``) y
    retorna la lista de resultados (``s3_url``, ``s3_key``, ``filename``,
    ``content_type``, ``size``) vía ``app.utils.s3_storage``.

    Reemplaza el flujo legacy del Kanban que llamaba a
    ``/registrar-requerimiento`` del artefacto de captura DAGMA solo
    para subir fotos.
    """
    try:
        s3_client = s3_storage.get_s3_client()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error configurando S3: {str(e)}")

    client_id = requerimiento_id or "general"
    resultados = []
    try:
        for archivo in archivos:
            contenido = await archivo.read()
            if not contenido:
                continue
            resultados.append(
                s3_storage.upload_file(
                    contenido,
                    modulo="seguimiento",
                    client_id=client_id,
                    categoria="evidencias",
                    filename=archivo.filename,
                    content_type=archivo.content_type,
                    s3_client=s3_client,
                )
            )
    except Exception:
        raise HTTPException(status_code=502, detail="Error subiendo evidencias a almacenamiento externo")

    return resultados


@router.patch(
    "/requerimientos/{req_id}/estado",
    summary="📋 PATCH | Cambiar estado de requerimiento",
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
            detail=f"Estado inválido. Debe ser uno de: {', '.join(estados_validos)}"
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
    summary="📋 PATCH | Asignar encargado a requerimiento",
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


# ==================== REPORTE PDF ====================

@router.get(
    "/visitas/{visita_id}/reporte-pdf",
    summary="📄 GET | Descargar informe PDF de visita",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PDF del informe de visita generado exitosamente.",
        },
        404: {"description": "Visita no encontrada."},
        500: {"description": "Error interno al generar el PDF."},
    },
)
async def descargar_reporte_pdf(
    visita_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Genera y descarga el informe PDF de una visita de campo junto con todos
    sus requerimientos asociados.

    El archivo resultante se llama ``informe-visita-{visita_id}.pdf`` y puede
    ser guardado directamente desde el navegador.
    """
    try:
        # Obtener la visita
        doc_ref = db.collection("visitas_programadas").document(visita_id)
        doc = doc_ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail=f"Visita {visita_id} no encontrada")

        visita = doc.to_dict() or {}
        visita["id"] = visita_id

        # Obtener los requerimientos asociados a esta visita
        query = (
            db.collection("requerimientos_seguimiento")
            .where("visita_id", "==", visita_id)
            .order_by("created_at")
        )
        docs_req = list(query.stream())
        requerimientos = []
        for d in docs_req:
            r = d.to_dict() or {}
            r["id"] = d.id
            requerimientos.append(r)

        pdf_bytes = generar_reporte_visita(visita, requerimientos)

        filename = f"informe-visita-{visita_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando PDF: {str(e)}")

