"""
Rutas para el módulo de Jornadas Integrales.

Modelo de datos (Firestore, migrado desde Excel):
- ``jornadas_integrales``: una jornada de campo (doc id ``jor_*``).
- ``jornadas_compromisos``: compromisos adquiridos por organismos en una
  jornada (doc id ``com_*``), con verificación de cumplimiento en campo.
- ``jornadas_seguimientos``: seguimientos posteriores a un compromiso
  (doc id ``seg_*``).
- ``jornadas_encuestas``: encuestas de satisfacción a la comunidad
  (doc id ``enc_*``), con una lista ``evaluaciones`` de esquema NO
  enforced (viene de una migración de Excel en formato libre).

Por ahora este módulo solo expone el dashboard de estadísticas
agregadas (``GET /jornadas/estadisticas``); sigue el mismo patrón que
``app.routes.avanzadas_routes`` (Pydantic Out models, cache TTL en
memoria con ``copy.deepcopy`` en el getter, TTL configurable por env
var).
"""
from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.auth_system.dependencies import get_current_user
from app.firebase_config import db
# Reutilizamos helpers de avanzadas_routes (sigla de entidad, upsert de
# categorías personalizadas, agrupado de fotos por índice) en vez de
# duplicarlos: Jornadas Integrales comparte la colección
# 'avanzadas_requerimientos' y el catálogo de categorías con Avanzadas
# Diagnósticas (ver Parte 2 del módulo, más abajo).
from app.routes import avanzadas_routes
# Módulo unificado de S3 (single source: credenciales, bucket, key format,
# upload/delete/list/presign).
from app.utils import s3_storage

router = APIRouter(prefix="/jornadas", tags=["Jornadas Integrales"])


# ==================== MODELOS DE SALIDA ====================

class TotalesJornadasOut(BaseModel):
    jornadas: int
    compromisos: int
    seguimientos: int
    encuestas: int
    asistencia_total: int
    cumplimiento_pct: float


class CompromisoPorOrganismoOut(BaseModel):
    organismo: str
    total: int
    cumple: int
    no_cumple: int
    novedad: int


class CompromisoPorVerificacionOut(BaseModel):
    estado: str
    total: int


class SeguimientoPorEstadoOut(BaseModel):
    estado: str
    total: int


class EncuestaPorOrganismoOut(BaseModel):
    org: str
    bueno: int
    regular: int
    malo: int
    na: int
    total: int


class JornadaPorComunaOut(BaseModel):
    comuna: str
    jornadas: int
    compromisos: int


class JornadaListaItemOut(BaseModel):
    client_id: str
    nombre_jornada: str
    fecha: str
    comuna: str
    barrio: str
    estado: str
    asistencia_aproximada: int
    compromisos_count: int


class JornadasEstadisticasOut(BaseModel):
    totales: TotalesJornadasOut
    compromisos_por_organismo: List[CompromisoPorOrganismoOut]
    compromisos_por_verificacion: List[CompromisoPorVerificacionOut]
    seguimientos_por_estado: List[SeguimientoPorEstadoOut]
    encuestas_por_organismo: List[EncuestaPorOrganismoOut]
    jornadas_por_comuna: List[JornadaPorComunaOut]
    jornadas_lista: List[JornadaListaItemOut]


# ==================== HELPERS ====================

_CALIFICACIONES_VALIDAS = {
    "bueno": "bueno",
    "regular": "regular",
    "malo": "malo",
    "na": "na",
    "n/a": "na",
}


def _texto_normalizado(valor, default: str) -> str:
    """Normaliza un campo de texto potencialmente ausente/vacío/no-string
    (dato migrado desde Excel, sin schema enforced) a un string no vacío,
    usando ``default`` como bucket explícito en vez de fabricar
    agregaciones silenciosamente incompletas.
    """
    if isinstance(valor, str) and valor.strip():
        return valor.strip()
    return default


def _entero_seguro(valor) -> int:
    """Coacciona un campo numérico potencialmente sucio (string, None,
    float) a ``int``, devolviendo 0 ante cualquier valor no convertible
    en vez de romper el endpoint completo por un dato migrado defectuoso.
    """
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def _fecha_a_str(valor) -> str:
    """Serializa un campo de fecha que puede venir como string
    "YYYY-MM-DD" (formato de la migración para ``fecha``) o como
    datetime crudo de Firestore (caso de ``creado``/``actualizado``) --
    no se puede asumir cuál, así que se maneja defensivamente.
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor)


def _normalizar_calificacion(valor) -> Optional[str]:
    """Bucketiza el campo ``calif`` de una evaluación en
    bueno/regular/malo/na, case-insensitive. Valores desconocidos o no
    parseables retornan ``None`` para que el llamador los ignore sin
    romper el endpoint (el esquema de ``evaluaciones`` no está
    enforced: viene de una migración de Excel en formato libre)."""
    if not isinstance(valor, str):
        return None
    return _CALIFICACIONES_VALIDAS.get(valor.strip().lower())


# ==================== CÁLCULO DE ESTADÍSTICAS ====================

def _calcular_estadisticas_jornadas() -> dict:
    """Recorre las cuatro colecciones de Jornadas Integrales UNA sola vez
    cada una y calcula todas las agregaciones del dashboard en memoria
    (nada de N+1 contra Firestore). Retorna un dict plano (no un
    ``JornadasEstadisticasOut``) para que el cache TTL que lo envuelve
    pueda devolver copias baratas sin acoplarse a Pydantic.
    """
    jornada_docs = list(db.collection("jornadas_integrales").stream())
    compromiso_docs = list(db.collection("jornadas_compromisos").stream())
    seguimiento_docs = list(db.collection("jornadas_seguimientos").stream())
    encuesta_docs = list(db.collection("jornadas_encuestas").stream())

    jornadas = [(d.id, d.to_dict() or {}) for d in jornada_docs]
    jornadas_por_id: Dict[str, dict] = {doc_id: data for doc_id, data in jornadas}
    compromisos = [d.to_dict() or {} for d in compromiso_docs]
    seguimientos = [d.to_dict() or {} for d in seguimiento_docs]
    encuestas = [d.to_dict() or {} for d in encuesta_docs]

    total_jornadas = len(jornadas)
    total_compromisos = len(compromisos)
    total_seguimientos = len(seguimientos)
    total_encuestas = len(encuestas)

    asistencia_total = sum(_entero_seguro(data.get("asistencia_aproximada")) for _, data in jornadas)

    # ---- cumplimiento_pct ----
    total_cumple = sum(
        1 for c in compromisos
        if _texto_normalizado(c.get("estado_verificacion_campo"), "sin_verificar") == "cumple"
    )
    cumplimiento_pct = (
        round(total_cumple / total_compromisos * 100, 1) if total_compromisos else 0.0
    )

    # ---- compromisos_por_organismo ----
    organismo_total: Dict[str, int] = {}
    organismo_cumple: Dict[str, int] = {}
    organismo_no_cumple: Dict[str, int] = {}
    organismo_novedad: Dict[str, int] = {}
    for c in compromisos:
        organismo = _texto_normalizado(c.get("organismo"), "Sin organismo")
        organismo_total[organismo] = organismo_total.get(organismo, 0) + 1

        estado_verif = _texto_normalizado(c.get("estado_verificacion_campo"), "sin_verificar")
        if estado_verif == "cumple":
            organismo_cumple[organismo] = organismo_cumple.get(organismo, 0) + 1
        elif estado_verif == "no-cumple":
            organismo_no_cumple[organismo] = organismo_no_cumple.get(organismo, 0) + 1
        elif estado_verif == "novedad":
            organismo_novedad[organismo] = organismo_novedad.get(organismo, 0) + 1

    compromisos_por_organismo = sorted(
        (
            {
                "organismo": organismo,
                "total": total,
                "cumple": organismo_cumple.get(organismo, 0),
                "no_cumple": organismo_no_cumple.get(organismo, 0),
                "novedad": organismo_novedad.get(organismo, 0),
            }
            for organismo, total in organismo_total.items()
        ),
        # Orden: total DESC, tie-break organismo ASC.
        key=lambda x: (-x["total"], x["organismo"]),
    )

    # ---- compromisos_por_verificacion ----
    verificacion_totales: Dict[str, int] = {}
    for c in compromisos:
        estado_verif = _texto_normalizado(c.get("estado_verificacion_campo"), "sin_verificar")
        verificacion_totales[estado_verif] = verificacion_totales.get(estado_verif, 0) + 1

    compromisos_por_verificacion = sorted(
        (
            {"estado": estado, "total": total}
            for estado, total in verificacion_totales.items()
        ),
        key=lambda x: (-x["total"], x["estado"]),
    )

    # ---- seguimientos_por_estado ----
    seguimiento_totales: Dict[str, int] = {}
    for s in seguimientos:
        estado = _texto_normalizado(s.get("estado"), "sin_estado")
        seguimiento_totales[estado] = seguimiento_totales.get(estado, 0) + 1

    seguimientos_por_estado = sorted(
        (
            {"estado": estado, "total": total}
            for estado, total in seguimiento_totales.items()
        ),
        key=lambda x: (-x["total"], x["estado"]),
    )

    # ---- encuestas_por_organismo ----
    # 'evaluaciones' no tiene esquema enforced (Excel de captura libre):
    # se recorre defensivamente, ignorando cualquier item/campo
    # malformado sin romper el endpoint completo.
    org_bueno: Dict[str, int] = {}
    org_regular: Dict[str, int] = {}
    org_malo: Dict[str, int] = {}
    org_na: Dict[str, int] = {}
    org_total: Dict[str, int] = {}
    for e in encuestas:
        evaluaciones = e.get("evaluaciones")
        if not isinstance(evaluaciones, list):
            continue
        for item in evaluaciones:
            if not isinstance(item, dict):
                continue
            org = item.get("org")
            if not isinstance(org, str) or not org.strip():
                continue
            org = org.strip()
            calif = _normalizar_calificacion(item.get("calif"))
            if calif is None:
                continue

            if calif == "bueno":
                org_bueno[org] = org_bueno.get(org, 0) + 1
            elif calif == "regular":
                org_regular[org] = org_regular.get(org, 0) + 1
            elif calif == "malo":
                org_malo[org] = org_malo.get(org, 0) + 1
            elif calif == "na":
                org_na[org] = org_na.get(org, 0) + 1
            org_total[org] = org_total.get(org, 0) + 1

    encuestas_por_organismo = sorted(
        (
            {
                "org": org,
                "bueno": org_bueno.get(org, 0),
                "regular": org_regular.get(org, 0),
                "malo": org_malo.get(org, 0),
                "na": org_na.get(org, 0),
                "total": total,
            }
            for org, total in org_total.items()
        ),
        key=lambda x: (-x["total"], x["org"]),
    )

    # ---- jornadas_por_comuna ----
    comuna_jornadas: Dict[str, int] = {}
    for _, data in jornadas:
        comuna = (data.get("comuna") or "").strip()
        if comuna:
            comuna_jornadas[comuna] = comuna_jornadas.get(comuna, 0) + 1

    comuna_compromisos: Dict[str, int] = {}
    for c in compromisos:
        jornada_padre = jornadas_por_id.get(c.get("jornada_client_id"))
        if jornada_padre is None:
            # Compromiso huérfano: su jornada padre no existe. Se excluye
            # silenciosamente de la agregación por comuna (no se puede
            # unir sin la jornada) en vez de fallar la request -- mismo
            # criterio que los requerimientos huérfanos en avanzadas.
            continue
        comuna = (jornada_padre.get("comuna") or "").strip()
        if comuna:
            comuna_compromisos[comuna] = comuna_compromisos.get(comuna, 0) + 1

    todas_comunas = set(comuna_jornadas) | set(comuna_compromisos)
    jornadas_por_comuna = sorted(
        (
            {
                "comuna": comuna,
                "jornadas": comuna_jornadas.get(comuna, 0),
                "compromisos": comuna_compromisos.get(comuna, 0),
            }
            for comuna in todas_comunas
        ),
        key=lambda x: (-x["jornadas"], x["comuna"]),
    )

    # ---- jornadas_lista ----
    compromisos_count_por_jornada: Dict[str, int] = {}
    for c in compromisos:
        jid = c.get("jornada_client_id")
        if jid:
            compromisos_count_por_jornada[jid] = compromisos_count_por_jornada.get(jid, 0) + 1

    jornadas_lista = [
        {
            "client_id": doc_id,
            "nombre_jornada": data.get("nombre_jornada", ""),
            "fecha": _fecha_a_str(data.get("fecha")),
            "comuna": data.get("comuna", ""),
            "barrio": data.get("barrio", ""),
            "estado": data.get("estado", ""),
            "asistencia_aproximada": _entero_seguro(data.get("asistencia_aproximada")),
            "compromisos_count": compromisos_count_por_jornada.get(doc_id, 0),
        }
        for doc_id, data in jornadas
    ]
    # Orden: fecha DESC (más reciente primero), tie-break client_id ASC.
    # Se ordena en dos pasadas aprovechando que sort() es estable: primero
    # por client_id ASC, luego por fecha DESC (el segundo sort preserva,
    # dentro de cada fecha empatada, el orden por client_id ya aplicado).
    jornadas_lista.sort(key=lambda x: x["client_id"])
    jornadas_lista.sort(key=lambda x: x["fecha"], reverse=True)

    return {
        "totales": {
            "jornadas": total_jornadas,
            "compromisos": total_compromisos,
            "seguimientos": total_seguimientos,
            "encuestas": total_encuestas,
            "asistencia_total": asistencia_total,
            "cumplimiento_pct": cumplimiento_pct,
        },
        "compromisos_por_organismo": compromisos_por_organismo,
        "compromisos_por_verificacion": compromisos_por_verificacion,
        "seguimientos_por_estado": seguimientos_por_estado,
        "encuestas_por_organismo": encuestas_por_organismo,
        "jornadas_por_comuna": jornadas_por_comuna,
        "jornadas_lista": jornadas_lista,
    }


# TTL (segundos) del cache en memoria de las estadísticas agregadas de
# Jornadas Integrales. Mismo patrón que ``avanzadas_routes``:
# configurable por env var para debugging o para aliviar presión sobre
# Firestore.
JORNADAS_ESTADISTICAS_TTL_SECONDS = float(os.getenv("JORNADAS_ESTADISTICAS_TTL_SECONDS", "60"))


@dataclass
class _JornadasEstadisticasCacheEntry:
    value: dict
    expires_at: float


# Cache module-level, sin dependencias externas (una asignación de
# variable global es atómica en CPython, alcanza sin locks).
_jornadas_estadisticas_cache: Optional[_JornadasEstadisticasCacheEntry] = None


def _obtener_estadisticas_jornadas_cacheado() -> dict:
    """Como ``_calcular_estadisticas_jornadas`` pero con un cache TTL en
    memoria, para no recorrer las cuatro colecciones completas en cada
    request al endpoint de estadísticas.

    Devuelve siempre una copia profunda del valor cacheado: si quien
    llama muta el dict/lista recibido, el cache guardado para el
    próximo hit queda intacto.
    """
    global _jornadas_estadisticas_cache

    entry = _jornadas_estadisticas_cache
    now = time.monotonic()
    if entry is not None and entry.expires_at > now:
        return copy.deepcopy(entry.value)

    value = _calcular_estadisticas_jornadas()
    _jornadas_estadisticas_cache = _JornadasEstadisticasCacheEntry(
        value=value, expires_at=now + JORNADAS_ESTADISTICAS_TTL_SECONDS
    )
    return copy.deepcopy(value)


def _invalidar_cache_estadisticas_jornadas() -> None:
    global _jornadas_estadisticas_cache
    _jornadas_estadisticas_cache = None


# ==================== ESTADÍSTICAS ====================

@router.get(
    "/estadisticas",
    summary="📊 GET | Estadísticas de Jornadas Integrales",
    response_model=JornadasEstadisticasOut,
)
async def obtener_estadisticas_jornadas(current_user: dict = Depends(get_current_user)):
    """
    Retorna estadísticas agregadas en servidor sobre las Jornadas
    Integrales y sus compromisos/seguimientos/encuestas asociados
    (totales, cumplimiento, distribución por organismo/verificación/
    estado/comuna, listado de jornadas), para alimentar el dashboard de
    Jornadas Integrales del frontend.

    El cálculo completo se cachea con un TTL en memoria (ver
    ``_obtener_estadisticas_jornadas_cacheado``) para no recorrer las
    cuatro colecciones completas en cada request.
    """
    try:
        return JornadasEstadisticasOut(**_obtener_estadisticas_jornadas_cacheado())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculando estadísticas de jornadas: {str(e)}")


# ============================================================================
# PARTE 1 -- ENDPOINTS DE ESCRITURA DE JORNADAS INTEGRALES
#
# Modelo de guardado incremental por fase (igual que el formulario de
# referencia): cada fase de la jornada (creación, compromisos,
# seguimientos, verificación, encuestas, requerimientos) se persiste con
# su propio endpoint independiente -- no existe un único endpoint de
# "enviar todo". La progresión de ``estado`` es
# planificacion -> seguimiento -> ejecucion -> completada.
#
# IMPORTANTE (orden de rutas): FastAPI matchea rutas en orden de
# declaración dentro del router. Las rutas ESTÁTICAS (o con un segmento
# literal en la posición donde otra ruta tiene un parámetro dinámico del
# mismo método HTTP) deben declararse ANTES que la ruta dinámica que
# competiría por esa posición. En este módulo el único caso real de
# colisión es GET "/estadisticas" (arriba) vs. GET "/{client_id}" (al
# final de este archivo) -- por eso "/{client_id}" se deja como el
# ÚLTIMO handler GET del router. El resto de las rutas nuevas
# (compromisos/{client_id}, encuestas/{client_id}, etc.) usan métodos
# HTTP o segmentos literales distintos entre sí, así que no compiten por
# la misma posición aunque se declaren en cualquier orden.
# ============================================================================

_ESTADOS_JORNADA_VALIDOS = {"planificacion", "seguimiento", "ejecucion", "completada"}
_TIPOS_COMPROMISO_VALIDOS = {"cualitativo", "cuantitativo"}
_ESTADOS_SEGUIMIENTO_VALIDOS = {"ok", "novedad", "cancelado"}
_ESTADOS_VERIFICACION_VALIDOS = {"cumple", "no-cumple", "novedad"}
_MAX_FOTOS_VERIFICACION = 4

# Mapea cualquier variante case-insensitive de las 4 calificaciones
# aceptadas a su forma canónica de almacenamiento/salida.
_CALIF_CANONICA = {
    "bueno": "Bueno",
    "regular": "Regular",
    "malo": "Malo",
    "na": "N/A",
    "n/a": "N/A",
}


# ---------------------------------------------------------------------------
# now_colombia: reexportado de avanzadas_routes para no duplicar la
# constante de zona horaria (UTC-5) en dos módulos.
# ---------------------------------------------------------------------------
now_colombia = avanzadas_routes.now_colombia


# ==================== MODELOS DE ENTRADA (escritura) ====================

class JornadaCreateIn(BaseModel):
    client_id: str = Field(..., min_length=1)
    nombre_jornada: str = Field(..., min_length=1)
    fecha: str = Field(..., min_length=1)
    sector_punto_reconocimiento: Optional[str] = None
    punto_encuentro: str = Field(..., min_length=1)
    direccion_punto_encuentro: str = Field(..., min_length=1)
    coordenadas_encuentro: str = Field(..., min_length=1)
    comuna: str = Field(..., min_length=1)
    barrio: str = Field(..., min_length=1)
    direcciones_recuperadas: List[str] = Field(default_factory=list)


class JornadaUpdateIn(BaseModel):
    """Todos los campos son opcionales: PATCH aplica solo lo enviado
    (``exclude_unset=True`` al construir el diff), cubriendo tanto
    edición de campos generales como transición de ``estado`` como los
    campos de cierre (asistencia/observaciones/peticiones) en un mismo
    endpoint -- tal como pide el modelo incremental por fase.
    """
    nombre_jornada: Optional[str] = None
    fecha: Optional[str] = None
    sector_punto_reconocimiento: Optional[str] = None
    punto_encuentro: Optional[str] = None
    direccion_punto_encuentro: Optional[str] = None
    coordenadas_encuentro: Optional[str] = None
    comuna: Optional[str] = None
    barrio: Optional[str] = None
    direcciones_recuperadas: Optional[List[str]] = None
    estado: Optional[str] = None
    asistencia_aproximada: Optional[int] = None
    observaciones_generales: Optional[str] = None
    peticiones_comunidad: Optional[str] = None

    @field_validator("estado")
    @classmethod
    def _validar_estado(cls, v):
        if v is not None and v not in _ESTADOS_JORNADA_VALIDOS:
            raise ValueError(
                f"estado inválido: {v!r}. Debe ser uno de {sorted(_ESTADOS_JORNADA_VALIDOS)}"
            )
        return v


class CompromisoCreateIn(BaseModel):
    client_id: str = Field(..., min_length=1)
    organismo: str = Field(..., min_length=1)
    oferta_servicio: Optional[str] = None
    responsable_organismo: Optional[str] = None
    celular_responsable: Optional[str] = None
    tipo: str = Field(..., min_length=1)
    compromiso: str = Field(..., min_length=1)
    unidad_medida: Optional[str] = None
    meta_cuantitativa: float = 0

    @field_validator("tipo")
    @classmethod
    def _validar_tipo(cls, v):
        if v not in _TIPOS_COMPROMISO_VALIDOS:
            raise ValueError(f"tipo inválido: {v!r}. Debe ser uno de {sorted(_TIPOS_COMPROMISO_VALIDOS)}")
        return v

    @model_validator(mode="after")
    def _validar_meta_segun_tipo(self):
        # Decisión de diseño: un compromiso 'cualitativo' se verifica en
        # campo como cumple/no-cumple/novedad, no como una cantidad
        # alcanzada -- no tiene sentido una meta_cuantitativa distinta de
        # cero. En vez de coaccionarla silenciosamente a 0 (lo que
        # ocultaría un error de captura real del formulario), se RECHAZA
        # explícitamente con 422 para que el cliente lo corrija.
        if self.tipo == "cualitativo" and self.meta_cuantitativa not in (0, 0.0):
            raise ValueError(
                "meta_cuantitativa debe ser 0 (o no enviarse) cuando tipo='cualitativo'"
            )
        return self


class CompromisoUpdateIn(BaseModel):
    organismo: Optional[str] = None
    oferta_servicio: Optional[str] = None
    responsable_organismo: Optional[str] = None
    celular_responsable: Optional[str] = None
    tipo: Optional[str] = None
    compromiso: Optional[str] = None
    unidad_medida: Optional[str] = None
    meta_cuantitativa: Optional[float] = None

    @field_validator("tipo")
    @classmethod
    def _validar_tipo(cls, v):
        if v is not None and v not in _TIPOS_COMPROMISO_VALIDOS:
            raise ValueError(f"tipo inválido: {v!r}. Debe ser uno de {sorted(_TIPOS_COMPROMISO_VALIDOS)}")
        return v


class SeguimientoCreateIn(BaseModel):
    client_id: str = Field(..., min_length=1)
    fecha_seguimiento: str = Field(..., min_length=1)
    estado: str = Field(..., min_length=1)
    responsable_seguimiento: Optional[str] = None
    comentario_seguimiento: Optional[str] = None

    @field_validator("estado")
    @classmethod
    def _validar_estado(cls, v):
        if v not in _ESTADOS_SEGUIMIENTO_VALIDOS:
            raise ValueError(f"estado inválido: {v!r}. Debe ser uno de {sorted(_ESTADOS_SEGUIMIENTO_VALIDOS)}")
        return v


class VerificacionIn(BaseModel):
    estado_verificacion_campo: str = Field(..., min_length=1)
    fecha_verificacion: Optional[str] = None
    responsable_verificacion: Optional[str] = None
    representante_organismo: Optional[str] = None
    resultado_obtenido: Optional[str] = None
    comentario_verificacion: Optional[str] = None
    fotos_existentes: List[str] = Field(default_factory=list)

    @field_validator("estado_verificacion_campo")
    @classmethod
    def _validar_estado(cls, v):
        if v not in _ESTADOS_VERIFICACION_VALIDOS:
            raise ValueError(
                f"estado_verificacion_campo inválido: {v!r}. Debe ser uno de {sorted(_ESTADOS_VERIFICACION_VALIDOS)}"
            )
        return v


class EvaluacionIn(BaseModel):
    org: str = Field(..., min_length=1)
    calif: str = Field(..., min_length=1)

    @field_validator("calif")
    @classmethod
    def _validar_calif(cls, v):
        canon = _CALIF_CANONICA.get(v.strip().lower())
        if canon is None:
            raise ValueError(f"calif inválida: {v!r}. Debe ser uno de {sorted(set(_CALIF_CANONICA.values()))}")
        return canon


class EncuestaCreateIn(BaseModel):
    client_id: str = Field(..., min_length=1)
    nombre_participante: Optional[str] = None
    comuna: Optional[str] = None
    barrio: Optional[str] = None
    evaluaciones: List[EvaluacionIn] = Field(default_factory=list)
    comentario_final: Optional[str] = None


class RequerimientoJornadaIn(BaseModel):
    entidad: str = Field(..., min_length=1)
    categoria: Optional[str] = None
    categoria_personalizada: Optional[str] = None
    requerimiento: str = Field(..., min_length=1)
    ubicacion: str = Field(..., min_length=1)
    coordenadas: Optional[str] = None


class RequerimientosJornadaPayloadIn(BaseModel):
    requerimientos: List[RequerimientoJornadaIn] = Field(..., min_length=1)


# ==================== MODELOS DE SALIDA (escritura) ====================

class JornadaEscrituraOut(BaseModel):
    id: str
    client_id: str
    numero: int
    fecha: str
    nombre_jornada: str
    sector_punto_reconocimiento: Optional[str] = None
    punto_encuentro: str
    direccion_punto_encuentro: str
    coordenadas_encuentro: str
    comuna: str
    barrio: str
    direcciones_recuperadas: List[str] = []
    estado: str
    asistencia_aproximada: Optional[int] = None
    observaciones_generales: Optional[str] = None
    peticiones_comunidad: Optional[str] = None
    url_croquis: Optional[str] = None
    url_informe_pdf: Optional[str] = None
    creado: str
    actualizado: str


class SeguimientoOut(BaseModel):
    id: str
    compromiso_client_id: str
    jornada_client_id: str
    fecha_seguimiento: str
    estado: str
    responsable_seguimiento: Optional[str] = None
    comentario_seguimiento: Optional[str] = None
    creado: str


class CompromisoOut(BaseModel):
    id: str
    jornada_client_id: str
    nombre_jornada: Optional[str] = None
    organismo: str
    oferta_servicio: Optional[str] = None
    responsable_organismo: Optional[str] = None
    celular_responsable: Optional[str] = None
    tipo: str
    compromiso: str
    unidad_medida: Optional[str] = None
    meta_cuantitativa: Optional[float] = 0
    estado_seguimiento: Optional[str] = None
    estado_verificacion_campo: Optional[str] = None
    fecha_verificacion: Optional[str] = None
    responsable_verificacion: Optional[str] = None
    representante_organismo: Optional[str] = None
    resultado_obtenido: Optional[str] = None
    comentario_verificacion: Optional[str] = None
    fotos_verificacion: List[str] = []
    creado: str
    actualizado: Optional[str] = None
    seguimientos: List[SeguimientoOut] = []


class EncuestaOut(BaseModel):
    id: str
    jornada_client_id: str
    nombre_participante: Optional[str] = None
    comuna: Optional[str] = None
    barrio: Optional[str] = None
    evaluaciones: List[dict] = []
    comentario_final: Optional[str] = None
    creado: str


class RequerimientoJornadaOut(BaseModel):
    id: str
    jornada_client_id: str
    req_index: int
    entidad: str
    categoria: Optional[str] = None
    categoria_personalizada: Optional[str] = None
    requerimiento: str
    ubicacion: str
    coordenadas: Optional[str] = None
    fotos_urls: List[str] = []
    created_at: Optional[str] = None


class JornadaListadoItemOut(BaseModel):
    id: str
    client_id: str
    numero: int
    fecha: str
    nombre_jornada: str
    comuna: str
    barrio: str
    estado: str
    asistencia_aproximada: Optional[int] = None
    compromisos_count: int


class JornadaDetalleOut(JornadaEscrituraOut):
    compromisos_count: int = 0
    compromisos: List[CompromisoOut] = []
    encuestas: List[EncuestaOut] = []
    requerimientos: List[RequerimientoJornadaOut] = []


# ==================== HELPERS DE ESCRITURA ====================

def _invalidar_caches_relacionadas() -> None:
    """Invalida el cache TTL propio de /jornadas/estadisticas y los dos
    caches de avanzadas_routes que también dependen de datos de Jornadas
    Integrales:

    - ``/avanzadas/geo`` pinta las jornadas como una capa más del mapa
      (ver ``_calcular_geo``), y desde la Parte 2 de este feature los
      requerimientos de origen 'jornada' viven en la colección
      compartida ``avanzadas_requerimientos`` que ese mismo endpoint
      recorre.
    - ``/avanzadas/estadisticas`` hace join de los requerimientos de
      origen 'jornada' contra ``jornadas_integrales`` (comuna) para
      ``por_comuna``, y sus totales incluyen ambos orígenes.

    Se invalidan los tres en cada escritura de este módulo para no dejar
    ninguno de los dos dashboards de avanzadas con datos de jornadas
    desactualizados durante el TTL.
    """
    _invalidar_cache_estadisticas_jornadas()
    avanzadas_routes._invalidar_cache_geo()
    avanzadas_routes._invalidar_cache_estadisticas()


def _responder_json(modelo: BaseModel, status_code: int):
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    return JSONResponse(content=jsonable_encoder(modelo), status_code=status_code)


def _jornada_doc_a_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    data["client_id"] = doc.id
    data["creado"] = _fecha_a_str(data.get("creado"))
    data["actualizado"] = _fecha_a_str(data.get("actualizado"))
    return data


def _seguimiento_doc_a_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    data["creado"] = _fecha_a_str(data.get("creado"))
    return data


def _listar_seguimientos_de_compromiso(compromiso_client_id: str) -> List[dict]:
    docs = (
        db.collection("jornadas_seguimientos")
        .where("compromiso_client_id", "==", compromiso_client_id)
        .get()
    )
    seguimientos = [_seguimiento_doc_a_dict(d) for d in docs]
    seguimientos.sort(key=lambda s: s.get("creado", ""))
    return seguimientos


def _compromiso_doc_a_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    data["creado"] = _fecha_a_str(data.get("creado"))
    data["actualizado"] = _fecha_a_str(data.get("actualizado")) if data.get("actualizado") else None
    data["seguimientos"] = _listar_seguimientos_de_compromiso(doc.id)
    return data


def _encuesta_doc_a_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    data["creado"] = _fecha_a_str(data.get("creado"))
    return data


def _requerimiento_jornada_doc_a_dict(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    return data


def _parse_verificacion_payload(datos: str) -> VerificacionIn:
    try:
        parsed = json.loads(datos)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Formato de 'datos' inválido. Debe ser un JSON válido: {str(e)}",
        )
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="'datos' debe ser un objeto JSON")
    try:
        return VerificacionIn(**parsed)
    except ValidationError as e:
        # include_context=False: por default, pydantic v2 mete la
        # excepción cruda (no serializable a JSON) en 'ctx' cuando un
        # @field_validator hace 'raise ValueError(...)' (como
        # ``_validar_estado`` arriba) -- sin este flag, jsonable_encoder
        # revienta al armar la respuesta 422.
        raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False))


def _parse_requerimientos_jornada_payload(datos: str) -> RequerimientosJornadaPayloadIn:
    try:
        parsed = json.loads(datos)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Formato de 'datos' inválido. Debe ser un JSON válido: {str(e)}",
        )
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="'datos' debe ser un objeto JSON")
    try:
        return RequerimientosJornadaPayloadIn(**parsed)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_context=False))


# ==================== CREAR JORNADA ====================

@router.post(
    "",
    summary="🟢 POST | Registrar Jornada Integral",
    response_model=JornadaEscrituraOut,
)
async def crear_jornada(
    payload: JornadaCreateIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Registra una nueva Jornada Integral. Es idempotente por
    ``client_id`` (generado en el cliente, prefijo ``jor_``): si ya
    existe, se retorna la existente con status 200; si es nueva, se crea
    con ``estado='planificacion'`` y se retorna con status 201.
    """
    ref = db.collection("jornadas_integrales").document(payload.client_id)
    existente = ref.get()
    if existente.exists:
        return _responder_json(JornadaEscrituraOut(**_jornada_doc_a_dict(existente)), 200)

    numero = list(db.collection("jornadas_integrales").count().get())[0][0].value + 1
    now = now_colombia().isoformat()
    data = {
        "numero": numero,
        "fecha": payload.fecha,
        "nombre_jornada": payload.nombre_jornada,
        "sector_punto_reconocimiento": payload.sector_punto_reconocimiento,
        "punto_encuentro": payload.punto_encuentro,
        "direccion_punto_encuentro": payload.direccion_punto_encuentro,
        "coordenadas_encuentro": payload.coordenadas_encuentro,
        "comuna": payload.comuna,
        "barrio": payload.barrio,
        "direcciones_recuperadas": payload.direcciones_recuperadas,
        "estado": "planificacion",
        "asistencia_aproximada": None,
        "observaciones_generales": None,
        "peticiones_comunidad": None,
        "url_croquis": None,
        "url_informe_pdf": None,
        "creado": now,
        "actualizado": now,
    }
    ref.set(data)
    _invalidar_caches_relacionadas()

    return _responder_json(JornadaEscrituraOut(**_jornada_doc_a_dict(ref.get())), 201)


# ==================== ACTUALIZAR JORNADA (general / estado / cierre) ====================

@router.patch(
    "/{client_id}",
    summary="🟡 PATCH | Actualizar Jornada Integral",
    response_model=JornadaEscrituraOut,
)
async def actualizar_jornada(
    client_id: str,
    payload: JornadaUpdateIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Actualización parcial de una jornada: campos generales, transición
    de ``estado`` (validado contra las 4 fases del flujo) y/o los campos
    de cierre (asistencia/observaciones/peticiones), todos en el mismo
    endpoint -- solo se aplican los campos efectivamente enviados.
    """
    ref = db.collection("jornadas_integrales").document(client_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Jornada '{client_id}' no encontrada")

    cambios = payload.model_dump(exclude_unset=True)
    if cambios:
        cambios["actualizado"] = now_colombia().isoformat()
        ref.update(cambios)
    _invalidar_caches_relacionadas()

    return _responder_json(JornadaEscrituraOut(**_jornada_doc_a_dict(ref.get())), 200)


# ==================== ELIMINAR JORNADA (cascada dura) ====================

@router.delete(
    "/{client_id}",
    summary="🔴 DELETE | Eliminar Jornada Integral (cascada)",
    status_code=204,
)
async def eliminar_jornada(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Elimina la jornada y cascadea TODOS sus sub-recursos: compromisos
    (y los seguimientos anidados de cada uno), encuestas, los
    requerimientos de la colección compartida ``avanzadas_requerimientos``
    con ``origen='jornada'`` que pertenecen a esta jornada, y sus objetos
    S3 asociados (borrado por prefijo ``jornadas/{client_id}/``).

    Cascada dura (Decisión de diseño #6): a diferencia de
    ``eliminar_compromiso`` -- que RECHAZA (409) el borrado de un
    compromiso individual con seguimientos asociados para evitar
    huerfanaje ACCIDENTAL -- un DELETE de la jornada PADRE es una acción
    deliberada del usuario que se espera que arrastre todo lo que le
    pertenece, igual que ``eliminar_avanzada`` en ``avanzadas_routes.py``.
    """
    ref = db.collection("jornadas_integrales").document(client_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Jornada '{client_id}' no encontrada")

    compromiso_docs = (
        db.collection("jornadas_compromisos").where("jornada_client_id", "==", client_id).get()
    )
    for compromiso_doc in compromiso_docs:
        seguimiento_docs = (
            db.collection("jornadas_seguimientos")
            .where("compromiso_client_id", "==", compromiso_doc.id)
            .get()
        )
        for seguimiento_doc in seguimiento_docs:
            db.collection("jornadas_seguimientos").document(seguimiento_doc.id).delete()
        db.collection("jornadas_compromisos").document(compromiso_doc.id).delete()

    encuesta_docs = (
        db.collection("jornadas_encuestas").where("jornada_client_id", "==", client_id).get()
    )
    for encuesta_doc in encuesta_docs:
        db.collection("jornadas_encuestas").document(encuesta_doc.id).delete()

    # Filtro doble (jornada_client_id + origen) a propósito: aunque en la
    # práctica un doc con jornada_client_id poblado siempre tiene
    # origen='jornada' (ver crear_requerimientos_jornada), el filtro
    # explícito documenta la invariante de origen en el propio query en
    # vez de depender solo de la convención de escritura.
    req_docs = (
        db.collection("avanzadas_requerimientos")
        .where("jornada_client_id", "==", client_id)
        .where("origen", "==", "jornada")
        .get()
    )
    for req_doc in req_docs:
        db.collection("avanzadas_requerimientos").document(req_doc.id).delete()

    ref.delete()

    try:
        s3_client = avanzadas_routes.get_s3_client()
        s3_storage.delete_prefix(
            f"jornadas/{client_id}/",
            s3_client=s3_client,
            bucket=s3_storage.bucket_name(),
        )
    except Exception:
        # Borrado de S3 es best-effort: no bloquear la eliminación en
        # Firestore por un problema de credenciales/red con S3 (mismo
        # criterio que ``eliminar_avanzada``).
        pass

    _invalidar_caches_relacionadas()

    return Response(status_code=204)


# ==================== SUBIR CROQUIS ====================

@router.post(
    "/{client_id}/croquis",
    summary="🟢 POST | Subir croquis de Jornada Integral",
    response_model=JornadaEscrituraOut,
)
async def subir_croquis_jornada(
    client_id: str,
    foto: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    ref = db.collection("jornadas_integrales").document(client_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Jornada '{client_id}' no encontrada")

    contenido = await foto.read()
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo de croquis está vacío")

    bucket_name = s3_storage.bucket_name()
    try:
        s3_client = avanzadas_routes.get_s3_client()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error configurando S3: {str(e)}")

    try:
        subida = s3_storage.upload_file(
            contenido,
            modulo="jornadas",
            client_id=client_id,
            categoria="croquis",
            filename=foto.filename,
            content_type=foto.content_type,
            s3_client=s3_client,
            bucket=bucket_name,
        )
        url = subida["s3_url"]
    except Exception:
        raise HTTPException(status_code=502, detail="Error subiendo croquis a almacenamiento externo")

    ref.update({"url_croquis": url, "actualizado": now_colombia().isoformat()})
    _invalidar_caches_relacionadas()

    return _responder_json(JornadaEscrituraOut(**_jornada_doc_a_dict(ref.get())), 200)


# ==================== COMPROMISOS ====================

@router.post(
    "/{client_id}/compromisos",
    summary="🟢 POST | Registrar compromiso de Jornada Integral",
    response_model=CompromisoOut,
)
async def crear_compromiso(
    client_id: str,
    payload: CompromisoCreateIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Registra un compromiso adquirido por un organismo en la jornada
    ``client_id``. Idempotente por el ``client_id`` del propio
    compromiso (prefijo ``com_``).
    """
    jornada_doc = db.collection("jornadas_integrales").document(client_id).get()
    if not jornada_doc.exists:
        raise HTTPException(status_code=404, detail=f"Jornada '{client_id}' no encontrada")
    jornada_data = jornada_doc.to_dict() or {}

    ref = db.collection("jornadas_compromisos").document(payload.client_id)
    existente = ref.get()
    if existente.exists:
        return _responder_json(CompromisoOut(**_compromiso_doc_a_dict(existente)), 200)

    now = now_colombia().isoformat()
    data = {
        "jornada_client_id": client_id,
        "nombre_jornada": jornada_data.get("nombre_jornada", ""),
        "organismo": payload.organismo,
        "oferta_servicio": payload.oferta_servicio,
        "responsable_organismo": payload.responsable_organismo,
        "celular_responsable": payload.celular_responsable,
        "tipo": payload.tipo,
        "compromiso": payload.compromiso,
        "unidad_medida": payload.unidad_medida,
        "meta_cuantitativa": payload.meta_cuantitativa,
        "estado_seguimiento": None,
        "estado_verificacion_campo": None,
        "fecha_verificacion": None,
        "responsable_verificacion": None,
        "representante_organismo": None,
        "resultado_obtenido": None,
        "comentario_verificacion": None,
        "fotos_verificacion": [],
        "creado": now,
        "actualizado": now,
    }
    ref.set(data)
    _invalidar_caches_relacionadas()

    return _responder_json(CompromisoOut(**_compromiso_doc_a_dict(ref.get())), 201)


@router.patch(
    "/compromisos/{client_id}",
    summary="🟡 PATCH | Editar compromiso de Jornada Integral",
    response_model=CompromisoOut,
)
async def actualizar_compromiso(
    client_id: str,
    payload: CompromisoUpdateIn,
    current_user: dict = Depends(get_current_user),
):
    ref = db.collection("jornadas_compromisos").document(client_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Compromiso '{client_id}' no encontrado")

    cambios = payload.model_dump(exclude_unset=True)
    if cambios:
        cambios["actualizado"] = now_colombia().isoformat()
        ref.update(cambios)
    _invalidar_caches_relacionadas()

    return _responder_json(CompromisoOut(**_compromiso_doc_a_dict(ref.get())), 200)


@router.delete(
    "/compromisos/{client_id}",
    summary="🔴 DELETE | Eliminar compromiso de Jornada Integral",
)
async def eliminar_compromiso(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Elimina un compromiso.

    Decisión de diseño (documentada también en el docstring del test que
    la cubre): si el compromiso tiene ``jornadas_seguimientos`` asociados,
    el borrado se RECHAZA con 409 en vez de cascadear el borrado de esos
    seguimientos. Los seguimientos son el historial de verificación en
    campo de ese compromiso; borrarlos implícitamente destruiría ese
    historial sin que el usuario lo haya pedido explícitamente. Además,
    ``/jornadas/estadisticas`` hace join seguimiento->compromiso
    (``seguimientos_por_estado`` cuenta el total de la colección, pero un
    seguimiento cuyo compromiso desapareciera quedaría huérfano de forma
    silenciosa) -- rechazar el borrado evita fabricar ese huérfano.
    """
    ref = db.collection("jornadas_compromisos").document(client_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Compromiso '{client_id}' no encontrado")

    seguimientos = (
        db.collection("jornadas_seguimientos")
        .where("compromiso_client_id", "==", client_id)
        .get()
    )
    if seguimientos:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No se puede eliminar el compromiso '{client_id}': tiene "
                f"{len(seguimientos)} seguimiento(s) asociado(s). Elimínelos primero."
            ),
        )

    ref.delete()
    _invalidar_caches_relacionadas()
    return {"client_id": client_id, "eliminado": True}


# ==================== SEGUIMIENTOS ====================

@router.post(
    "/compromisos/{client_id}/seguimientos",
    summary="🟢 POST | Registrar seguimiento de compromiso",
    response_model=SeguimientoOut,
)
async def crear_seguimiento(
    client_id: str,
    payload: SeguimientoCreateIn,
    current_user: dict = Depends(get_current_user),
):
    compromiso_ref = db.collection("jornadas_compromisos").document(client_id)
    compromiso_doc = compromiso_ref.get()
    if not compromiso_doc.exists:
        raise HTTPException(status_code=404, detail=f"Compromiso '{client_id}' no encontrado")
    compromiso_data = compromiso_doc.to_dict() or {}
    jornada_client_id = compromiso_data.get("jornada_client_id", "")

    ref = db.collection("jornadas_seguimientos").document(payload.client_id)
    existente = ref.get()
    if existente.exists:
        return _responder_json(SeguimientoOut(**_seguimiento_doc_a_dict(existente)), 200)

    now = now_colombia().isoformat()
    data = {
        "compromiso_client_id": client_id,
        # Denormalizado leyéndolo del compromiso PADRE, no del payload del
        # cliente: /jornadas/estadisticas hace join seguimiento->jornada a
        # través de este campo (jornadas_por_comuna), así que debe ser
        # confiable en vez de depender de que el cliente lo mande bien.
        "jornada_client_id": jornada_client_id,
        "fecha_seguimiento": payload.fecha_seguimiento,
        "estado": payload.estado,
        "responsable_seguimiento": payload.responsable_seguimiento,
        "comentario_seguimiento": payload.comentario_seguimiento,
        "creado": now,
    }
    ref.set(data)

    # El seguimiento más reciente manda sobre el estado_seguimiento
    # denormalizado del compromiso padre (para lectura rápida sin tener
    # que consultar la subcolección de seguimientos).
    compromiso_ref.update({"estado_seguimiento": payload.estado, "actualizado": now})

    _invalidar_caches_relacionadas()
    return _responder_json(SeguimientoOut(**_seguimiento_doc_a_dict(ref.get())), 201)


@router.patch(
    "/compromisos/{client_id}/verificacion",
    summary="🟡 PATCH | Registrar verificación en campo de compromiso",
    response_model=CompromisoOut,
)
async def actualizar_verificacion_compromiso(
    client_id: str,
    request: Request,
    datos: str = Form(..., description="Datos de la verificación en formato JSON (ver VerificacionIn)"),
    current_user: dict = Depends(get_current_user),
):
    ref = db.collection("jornadas_compromisos").document(client_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Compromiso '{client_id}' no encontrado")
    compromiso_data = doc.to_dict() or {}

    payload = _parse_verificacion_payload(datos)

    form = await request.form()
    archivos = [f for f in form.getlist("fotos") if getattr(f, "filename", None)][:_MAX_FOTOS_VERIFICACION]

    fotos_urls: List[str] = []
    if archivos:
        bucket_name = s3_storage.bucket_name()
        try:
            s3_client = avanzadas_routes.get_s3_client()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error configurando S3: {str(e)}")

        # client_id del upload: la JORNADA (denormalizada en el compromiso
        # como 'jornada_client_id'), no el compromiso mismo -- así la key
        # S3 queda bajo el prefijo 'jornadas/{jornada_client_id}/' y el
        # cascade de DELETE /jornadas/{id} (borrado por prefijo) la
        # alcanza. El id propio del compromiso se conserva como segmento
        # de 'categoria' para mantener trazabilidad por compromiso.
        jornada_client_id = compromiso_data.get("jornada_client_id") or client_id
        try:
            for archivo in archivos:
                contenido = await archivo.read()
                if not contenido:
                    continue
                subida = s3_storage.upload_file(
                    contenido,
                    modulo="jornadas",
                    client_id=jornada_client_id,
                    categoria=f"compromisos/{client_id}/verificacion",
                    filename=archivo.filename,
                    content_type=archivo.content_type,
                    s3_client=s3_client,
                    bucket=bucket_name,
                )
                fotos_urls.append(subida["s3_url"])
        except Exception:
            raise HTTPException(status_code=502, detail="Error subiendo fotos de verificación a almacenamiento externo")

    now = now_colombia().isoformat()
    # Las fotos ya existentes (reenviadas por el cliente sin cambios) se
    # mezclan con las recién subidas para formar la lista final -- el
    # cliente es responsable de decidir cuáles "existentes" conservar.
    cambios = {
        "estado_verificacion_campo": payload.estado_verificacion_campo,
        "fecha_verificacion": payload.fecha_verificacion,
        "responsable_verificacion": payload.responsable_verificacion,
        "representante_organismo": payload.representante_organismo,
        "resultado_obtenido": payload.resultado_obtenido,
        "comentario_verificacion": payload.comentario_verificacion,
        "fotos_verificacion": [*payload.fotos_existentes, *fotos_urls],
        "actualizado": now,
    }
    ref.update(cambios)
    _invalidar_caches_relacionadas()

    return _responder_json(CompromisoOut(**_compromiso_doc_a_dict(ref.get())), 200)


# ==================== ENCUESTAS ====================

@router.post(
    "/{client_id}/encuestas",
    summary="🟢 POST | Registrar encuesta de Jornada Integral",
    response_model=EncuestaOut,
)
async def crear_encuesta(
    client_id: str,
    payload: EncuestaCreateIn,
    current_user: dict = Depends(get_current_user),
):
    jornada_doc = db.collection("jornadas_integrales").document(client_id).get()
    if not jornada_doc.exists:
        raise HTTPException(status_code=404, detail=f"Jornada '{client_id}' no encontrada")

    ref = db.collection("jornadas_encuestas").document(payload.client_id)
    existente = ref.get()
    if existente.exists:
        return _responder_json(EncuestaOut(**_encuesta_doc_a_dict(existente)), 200)

    now = now_colombia().isoformat()
    data = {
        "jornada_client_id": client_id,
        "nombre_participante": payload.nombre_participante,
        "comuna": payload.comuna,
        "barrio": payload.barrio,
        "evaluaciones": [e.model_dump() for e in payload.evaluaciones],
        "comentario_final": payload.comentario_final,
        "creado": now,
    }
    ref.set(data)
    _invalidar_caches_relacionadas()

    return _responder_json(EncuestaOut(**_encuesta_doc_a_dict(ref.get())), 201)


@router.delete(
    "/encuestas/{client_id}",
    summary="🔴 DELETE | Eliminar encuesta de Jornada Integral",
)
async def eliminar_encuesta(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    ref = db.collection("jornadas_encuestas").document(client_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Encuesta '{client_id}' no encontrada")
    ref.delete()
    _invalidar_caches_relacionadas()
    return {"client_id": client_id, "eliminado": True}


# ==================== REQUERIMIENTOS DE JORNADA (colección compartida) ====================
# Ver Parte 2 del feature: los requerimientos capturados durante una
# jornada se guardan en la MISMA colección 'avanzadas_requerimientos' que
# usa el módulo de Avanzadas Diagnósticas (no se crea una colección
# nueva), marcados con origen='jornada'. Esto es lo que permite que
# /avanzadas/estadisticas y /avanzadas/geo los agreguen automáticamente
# junto con los de avanzadas.

@router.post(
    "/{client_id}/requerimientos",
    summary="🟢 POST | Registrar requerimientos de Jornada Integral",
)
async def crear_requerimientos_jornada(
    client_id: str,
    request: Request,
    datos: str = Form(..., description="JSON con la lista de requerimientos (ver RequerimientosJornadaPayloadIn)"),
    current_user: dict = Depends(get_current_user),
):
    jornada_doc = db.collection("jornadas_integrales").document(client_id).get()
    if not jornada_doc.exists:
        raise HTTPException(status_code=404, detail=f"Jornada '{client_id}' no encontrada")
    jornada_data = jornada_doc.to_dict() or {}

    payload = _parse_requerimientos_jornada_payload(datos)

    form = await request.form()
    fotos_por_requerimiento = avanzadas_routes._agrupar_fotos_por_requerimiento(form)

    bucket_name = s3_storage.bucket_name()
    s3_client = None
    if fotos_por_requerimiento:
        try:
            s3_client = avanzadas_routes.get_s3_client()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error configurando S3: {str(e)}")

    requerimientos_fotos_urls: Dict[int, List[str]] = {}
    try:
        for idx, req_in in enumerate(payload.requerimientos):
            archivos = fotos_por_requerimiento.get(idx, [])[: avanzadas_routes._MAX_FOTOS_POR_REQUERIMIENTO]
            fotos_urls: List[str] = []
            for archivo in archivos:
                contenido = await archivo.read()
                if not contenido:
                    continue
                subida = s3_storage.upload_file(
                    contenido,
                    modulo="jornadas",
                    client_id=client_id,
                    categoria=f"requerimientos/{idx}",
                    filename=archivo.filename,
                    content_type=archivo.content_type,
                    s3_client=s3_client,
                    bucket=bucket_name,
                )
                fotos_urls.append(subida["s3_url"])
            requerimientos_fotos_urls[idx] = fotos_urls
    except Exception:
        raise HTTPException(status_code=502, detail="Error subiendo fotos a almacenamiento externo")

    # Offset de req_index: el guardado es incremental (puede llamarse más
    # de una vez para la misma jornada a medida que se van agregando
    # requerimientos), así que la numeración continúa donde quedaron los
    # ya existentes -- si arrancara siempre en 0 el id determinístico
    # "{client_id}_{idx}" colisionaría con uno ya guardado en una llamada
    # anterior.
    existentes = (
        db.collection("avanzadas_requerimientos")
        .where("jornada_client_id", "==", client_id)
        .get()
    )
    offset = len(existentes)

    now = now_colombia().isoformat()
    creados: List[dict] = []
    for pos, req_in in enumerate(payload.requerimientos):
        idx = offset + pos
        req_data = {
            "avanzada_client_id": None,
            "jornada_client_id": client_id,
            "origen": "jornada",
            "req_index": idx,
            "entidad": req_in.entidad,
            "categoria": req_in.categoria,
            "categoria_personalizada": req_in.categoria_personalizada,
            "requerimiento": req_in.requerimiento,
            "ubicacion": req_in.ubicacion,
            "coordenadas": req_in.coordenadas,
            "fotos_urls": requerimientos_fotos_urls.get(pos, []),
            "fecha": jornada_data.get("fecha", ""),
            "nombre_avanzada": None,
            # nombre_origen: ver docstring de avanzadas_routes -- para
            # origen='jornada' es el nombre de la JORNADA, nunca se
            # escribe en 'nombre_avanzada' (ese campo debe seguir siendo
            # veraz para no romper lectores viejos).
            "nombre_origen": jornada_data.get("nombre_jornada", ""),
            "estrategia": None,
            "created_at": now,
        }
        req_doc_id = f"{client_id}_{idx}"
        db.collection("avanzadas_requerimientos").document(req_doc_id).set(req_data)
        req_data["id"] = req_doc_id
        creados.append(req_data)

        if req_in.categoria_personalizada and req_in.categoria_personalizada.strip():
            avanzadas_routes._upsert_categoria_personalizada(
                entidad_sigla=avanzadas_routes._sigla_entidad(req_in.entidad),
                categoria=req_in.categoria_personalizada.strip(),
                fecha=jornada_data.get("fecha", ""),
            )

    _invalidar_caches_relacionadas()

    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    return JSONResponse(content=jsonable_encoder({"requerimientos": creados}), status_code=201)


# ==================== LISTAR JORNADAS ====================

@router.get(
    "",
    summary="📋 GET | Listar Jornadas Integrales",
    response_model=List[JornadaListadoItemOut],
)
async def listar_jornadas(
    limit: int = Query(100, ge=1, le=500, description="Máximo de jornadas a retornar"),
    current_user: dict = Depends(get_current_user),
):
    """Lista las jornadas, ordenadas por fecha descendente, cada una con
    el conteo de compromisos calculado en memoria (sin N+1)."""
    docs = (
        db.collection("jornadas_integrales")
        .order_by("fecha", direction="DESCENDING")
        .limit(limit)
        .stream()
    )
    compromiso_docs = list(db.collection("jornadas_compromisos").stream())
    conteo: Dict[str, int] = {}
    for c in compromiso_docs:
        jid = (c.to_dict() or {}).get("jornada_client_id")
        if jid:
            conteo[jid] = conteo.get(jid, 0) + 1

    resultado = []
    for doc in docs:
        data = doc.to_dict() or {}
        resultado.append({
            "id": doc.id,
            "client_id": doc.id,
            "numero": data.get("numero", 0),
            "fecha": _fecha_a_str(data.get("fecha")),
            "nombre_jornada": data.get("nombre_jornada", ""),
            "comuna": data.get("comuna", ""),
            "barrio": data.get("barrio", ""),
            "estado": data.get("estado", ""),
            "asistencia_aproximada": data.get("asistencia_aproximada"),
            "compromisos_count": conteo.get(doc.id, 0),
        })
    return resultado


# ==================== DETALLE DE JORNADA ====================
# IMPORTANTE: esta ruta debe ser el ÚLTIMO handler GET declarado en este
# router -- ver la nota de orden de rutas al inicio de esta sección. Si
# se declarara antes que GET "/estadisticas", esa ruta estática quedaría
# interceptada (FastAPI trataría "estadisticas" como si fuera un
# client_id).

@router.get(
    "/{client_id}",
    summary="🔵 GET | Detalle de Jornada Integral",
    response_model=JornadaDetalleOut,
)
async def obtener_jornada(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna el detalle completo de una jornada: sus datos generales, los
    compromisos (cada uno con sus seguimientos y campos de verificación
    anidados), las encuestas y los requerimientos asociados (leídos de
    la colección compartida ``avanzadas_requerimientos`` filtrando por
    ``jornada_client_id``, ver Parte 2).
    """
    doc = db.collection("jornadas_integrales").document(client_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Jornada '{client_id}' no encontrada")

    data = _jornada_doc_a_dict(doc)

    compromiso_docs = (
        db.collection("jornadas_compromisos").where("jornada_client_id", "==", client_id).get()
    )
    compromisos = [_compromiso_doc_a_dict(d) for d in compromiso_docs]
    compromisos.sort(key=lambda c: c.get("creado", ""))

    encuesta_docs = (
        db.collection("jornadas_encuestas").where("jornada_client_id", "==", client_id).get()
    )
    encuestas = [_encuesta_doc_a_dict(d) for d in encuesta_docs]
    encuestas.sort(key=lambda e: e.get("creado", ""))

    req_docs = (
        db.collection("avanzadas_requerimientos").where("jornada_client_id", "==", client_id).get()
    )
    requerimientos = sorted(
        (_requerimiento_jornada_doc_a_dict(d) for d in req_docs),
        key=lambda r: r.get("req_index", 0),
    )

    data["compromisos_count"] = len(compromisos)
    data["compromisos"] = compromisos
    data["encuestas"] = encuestas
    data["requerimientos"] = requerimientos
    return JornadaDetalleOut(**data)
