"""
Rutas para el módulo de Avanzadas Diagnósticas.

Reemplaza la captura legacy de "requerimientos" sueltos por el modelo de
Avanzada Diagnóstica: una jornada de campo (con encargados, asistentes y
foto de equipo) que agrupa uno o más requerimientos dirigidos a distintas
entidades/dependencias de la Alcaldía.

Modelo de datos (Firestore):
- ``avanzadas``: un documento por avanzada, indexado por ``client_id``
  (UUID generado en el cliente) para permitir creación idempotente.
- ``avanzadas_requerimientos``: un documento por requerimiento de la
  avanzada, con los datos denormalizados (fecha/nombre_avanzada/estrategia)
  necesarios para listarlos sin volver a consultar la avanzada padre.
- ``categorias_personalizadas``: categorías de requerimiento que el equipo
  de campo escribe libremente y quedan disponibles como catálogo para
  las próximas avanzadas de la misma entidad.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError

from app.auth_system.dependencies import get_current_user
from app.data.avanzadas_catalogos import (
    CATEGORIAS_DEFAULT,
    DEPENDENCIAS_DEFAULT,
    EQUIPO_DEFAULT,
    ESTRATEGIAS_DEFAULT,
)
from app.firebase_config import db
# Módulo unificado de S3 (single source: credenciales, bucket, key format,
# upload/delete/list/presign).
from app.utils import s3_storage
from app.utils.s3_storage import get_s3_client

router = APIRouter(prefix="/avanzadas", tags=["Avanzadas Diagnósticas"])

# Zona horaria Colombia (UTC-5)
_COL_TZ = timezone(timedelta(hours=-5))

# Máximo de fotos aceptadas por requerimiento (las que excedan se descartan).
_MAX_FOTOS_POR_REQUERIMIENTO = 5

_FOTO_REQ_FIELD_RE = re.compile(r"^fotos_req_(\d+)$")


def now_colombia() -> datetime:
    """Retorna la hora actual en zona horaria de Colombia (America/Bogota, UTC-5)."""
    return datetime.now(_COL_TZ)


# ==================== MODELOS DE ENTRADA ====================

class AsistenteIn(BaseModel):
    nombre: str
    organismo: str
    celular: str
    correo: str


class RequerimientoAvanzadaIn(BaseModel):
    entidad: str = Field(..., min_length=1)
    categoria: Optional[str] = None
    categoria_personalizada: Optional[str] = None
    requerimiento: str = Field(..., min_length=1)
    ubicacion: str = Field(..., min_length=1)
    coordenadas: Optional[str] = None


class AvanzadaCreateIn(BaseModel):
    client_id: str = Field(..., min_length=1)
    nombre_avanzada: str = Field(..., min_length=1)
    fecha: str = Field(..., min_length=1)
    estrategia: str = Field(..., min_length=1)
    sector: Optional[str] = None
    comuna: str = Field(..., min_length=1)
    barrio: str = Field(..., min_length=1)
    direccion: str = Field(..., min_length=1)
    coordenadas: str = Field(..., min_length=1)
    encargados: List[str] = Field(..., min_length=1)
    asistentes: List[AsistenteIn] = Field(default_factory=list)
    requerimientos: List[RequerimientoAvanzadaIn] = Field(..., min_length=1)


class AvanzadaPutIn(BaseModel):
    """Reemplazo completo de una Avanzada (sin ``client_id``/``requerimientos``,
    que no se tocan por este endpoint: el primero es inmutable una vez creado
    el documento, y los segundos tienen su propio sub-recurso CRUD).

    Los campos opcionales (``sector``) que se omitan vuelven al default del
    schema (``None``), tal como pide el contrato de PUT como reemplazo total.
    """
    nombre_avanzada: str = Field(..., min_length=1)
    fecha: str = Field(..., min_length=1)
    estrategia: str = Field(..., min_length=1)
    sector: Optional[str] = None
    comuna: str = Field(..., min_length=1)
    barrio: str = Field(..., min_length=1)
    direccion: str = Field(..., min_length=1)
    coordenadas: str = Field(..., min_length=1)
    encargados: List[str] = Field(..., min_length=1)
    asistentes: List[AsistenteIn] = Field(default_factory=list)


class AvanzadaPatchIn(BaseModel):
    """Actualización parcial: todos los campos son opcionales y solo se
    aplican los efectivamente enviados (``exclude_unset=True`` al construir
    el diff), mismo patrón que ``JornadaUpdateIn`` en ``jornadas_routes.py``.
    """
    nombre_avanzada: Optional[str] = Field(None, min_length=1)
    fecha: Optional[str] = Field(None, min_length=1)
    estrategia: Optional[str] = Field(None, min_length=1)
    sector: Optional[str] = None
    comuna: Optional[str] = Field(None, min_length=1)
    barrio: Optional[str] = Field(None, min_length=1)
    direccion: Optional[str] = Field(None, min_length=1)
    coordenadas: Optional[str] = Field(None, min_length=1)
    encargados: Optional[List[str]] = Field(None, min_length=1)
    asistentes: Optional[List[AsistenteIn]] = None


class RequerimientoAvanzadaPatchIn(BaseModel):
    """Actualización parcial de un requerimiento sub-recurso. ``fotos_eliminar``
    recibe URLs (``fotos_urls`` tal como las devuelve la API) a remover; las
    fotos nuevas se agregan vía el campo multipart ``fotos`` del endpoint,
    no por este modelo.
    """
    entidad: Optional[str] = Field(None, min_length=1)
    categoria: Optional[str] = None
    categoria_personalizada: Optional[str] = None
    requerimiento: Optional[str] = Field(None, min_length=1)
    ubicacion: Optional[str] = Field(None, min_length=1)
    coordenadas: Optional[str] = None
    fotos_eliminar: Optional[List[str]] = None


# ==================== MODELOS DE SALIDA ====================

class AsistenteOut(BaseModel):
    nombre: str
    organismo: str
    celular: str
    correo: str


class RequerimientoAvanzadaOut(BaseModel):
    id: str
    avanzada_client_id: str
    req_index: int
    entidad: str
    categoria: Optional[str] = None
    categoria_personalizada: Optional[str] = None
    requerimiento: str
    ubicacion: str
    coordenadas: Optional[str] = None
    fotos_urls: List[str] = []
    fecha: str
    nombre_avanzada: str
    estrategia: str
    created_at: str


class AvanzadaOut(BaseModel):
    id: str
    client_id: str
    nombre_avanzada: str
    fecha: str
    estrategia: str
    sector: Optional[str] = None
    comuna: str
    barrio: str
    direccion: str
    coordenadas: str
    encargados: List[str]
    asistentes: List[AsistenteOut]
    foto_equipo_url: Optional[str] = None
    created_by: str
    created_at: str
    updated_at: str
    numero: int
    requerimientos_count: int
    requerimientos: List[RequerimientoAvanzadaOut]


class AvanzadaListItemOut(BaseModel):
    id: str
    client_id: str
    nombre_avanzada: str
    fecha: str
    estrategia: str
    sector: Optional[str] = None
    comuna: str
    barrio: str
    direccion: str
    coordenadas: str
    encargados: List[str]
    foto_equipo_url: Optional[str] = None
    created_by: str
    created_at: str
    updated_at: str
    numero: int
    requerimientos_count: int


class CatalogosOut(BaseModel):
    estrategias: List[str]
    equipo: List[str]
    dependencias: List[str]
    categorias: Dict[str, List[str]]


class TotalesEstadisticasOut(BaseModel):
    avanzadas: int
    requerimientos: int
    comunas: int
    entidades: int
    asistentes: int
    promedio_requerimientos: float


class PorEntidadOut(BaseModel):
    sigla: str
    entidad: str
    total: int


class PorCategoriaOut(BaseModel):
    categoria: str
    sigla: str
    total: int


class PorComunaOut(BaseModel):
    comuna: str
    avanzadas: int
    requerimientos: int


class PorEstrategiaOut(BaseModel):
    estrategia: str
    avanzadas: int
    requerimientos: int


class PorMesOut(BaseModel):
    mes: str
    avanzadas: int
    requerimientos: int


class EstadisticasOut(BaseModel):
    totales: TotalesEstadisticasOut
    por_entidad: List[PorEntidadOut]
    por_categoria: List[PorCategoriaOut]
    por_comuna: List[PorComunaOut]
    por_estrategia: List[PorEstrategiaOut]
    por_mes: List[PorMesOut]


class GeoAvanzadaOut(BaseModel):
    client_id: str
    nombre_avanzada: str
    fecha: str
    estrategia: str
    comuna: str
    barrio: str
    lat: float
    lng: float
    requerimientos_count: int


class GeoRequerimientoOut(BaseModel):
    id: str
    avanzada_client_id: str
    # origen: 'avanzada' | 'jornada'. Ver Parte 2 del feature de Jornadas
    # Integrales: la colección 'avanzadas_requerimientos' es compartida
    # entre ambos módulos; este campo permite al frontend distinguir la
    # capa a la que pertenece cada punto en el mapa.
    origen: str
    sigla: str
    entidad: str
    categoria: Optional[str] = None
    requerimiento: str
    ubicacion: str
    fecha: str
    lat: float
    lng: float
    fotos_count: int


class GeoJornadaOut(BaseModel):
    client_id: str
    nombre_jornada: str
    fecha: str
    comuna: str
    barrio: str
    estado: str
    lat: float
    lng: float


class OmitidosGeoOut(BaseModel):
    avanzadas: int
    requerimientos: int
    jornadas: int


class GeoOut(BaseModel):
    avanzadas: List[GeoAvanzadaOut]
    requerimientos: List[GeoRequerimientoOut]
    jornadas: List[GeoJornadaOut]
    omitidos: OmitidosGeoOut


# ==================== HELPERS ====================

def _sigla_entidad(entidad: str) -> str:
    """Extrae la sigla de una entidad en formato 'SIGLA - Nombre completo'."""
    return entidad.split(" - ", 1)[0].strip()


def _parsear_coordenadas(valor) -> Optional[tuple]:
    """Parsea el campo ``coordenadas`` de Firestore (string "lat, lng",
    tal como quedó tras la migración desde Excel) en una tupla
    ``(lat, lng)`` de floats.

    Retorna ``None`` ante cualquier valor no parseable, ambiguo o fuera
    de rango -- en vez de lanzar o devolver ``(0.0, 0.0)``, que
    renderizaría un punto fantasma en el Golfo de Guinea -- para que el
    llamador pueda descartar el registro y contabilizarlo en
    ``omitidos`` en vez de fabricar una ubicación.

    No se admite un separador decimal de coma dentro de cada componente
    (p. ej. "3,48, -76,51"): el formato real de la migración usa punto
    decimal, y aceptar coma-decimal ahí ambiguaría contra el separador
    "lat, lng" -- se prefiere rechazar antes que adivinar.
    """
    if not isinstance(valor, str):
        return None

    partes = [p.strip() for p in valor.split(",")]
    if len(partes) != 2 or not partes[0] or not partes[1]:
        return None

    try:
        lat = float(partes[0])
        lng = float(partes[1])
    except ValueError:
        return None

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None

    return (lat, lng)


def _requerimiento_doc_to_out(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    return data


def _s3_key_from_url(url: str) -> Optional[str]:
    """Extrae la ``s3_key`` de una ``s3_url`` con el formato que arma
    ``s3_storage.upload_file`` (``https://{bucket}.s3.amazonaws.com/{key}``).

    Retorna ``None`` si ``url`` no tiene ese formato (p. ej. ya es una URL
    presignada u otro esquema) -- en vez de adivinar, se prefiere no borrar
    nada en S3 antes que borrar la key equivocada.
    """
    marcador = ".amazonaws.com/"
    if marcador not in url:
        return None
    return url.split(marcador, 1)[1]


def _siguiente_req_index(client_id: str) -> int:
    """Calcula el próximo ``req_index`` para un requerimiento nuevo dentro de
    una avanzada como ``max(req_index existentes) + 1`` (nunca ``len(...)``,
    que reutilizaría un índice liberado por un DELETE previo -- ver Decisión
    de diseño #5).
    """
    docs = (
        db.collection("avanzadas_requerimientos")
        .where("avanzada_client_id", "==", client_id)
        .get()
    )
    indices = [(d.to_dict() or {}).get("req_index", -1) for d in docs]
    return (max(indices) + 1) if indices else 0


def _construir_catalogo_categorias() -> Dict[str, List[str]]:
    """Combina las categorías por defecto con las personalizadas de Firestore.

    Los valores por defecto siempre van primero; las personalizadas se
    agregan al final, deduplicadas por entidad.
    """
    categorias: Dict[str, List[str]] = {
        entidad: list(valores) for entidad, valores in CATEGORIAS_DEFAULT.items()
    }

    try:
        docs = db.collection("categorias_personalizadas").stream()
    except Exception:
        docs = []

    for doc in docs:
        data = doc.to_dict() or {}
        entidad = (data.get("entidad") or "").strip()
        categoria = (data.get("categoria") or "").strip()
        if not entidad or not categoria:
            continue
        lista = categorias.setdefault(entidad, [])
        if categoria not in lista:
            lista.append(categoria)

    return categorias


# TTL (segundos) del cache en memoria del catálogo de categorías combinado
# (defaults + personalizadas). Configurable por env var para poder bajarlo
# en debugging o subirlo si Firestore está bajo presión.
_AVANZADAS_CATALOGOS_TTL_SECONDS = float(os.getenv("AVANZADAS_CATALOGOS_TTL_SECONDS", "60"))


@dataclass
class _CatalogosCacheEntry:
    value: Dict[str, List[str]]
    expires_at: float


# Cache module-level, sin dependencias externas. Una simple asignación de
# variable global es atómica en CPython, así que alcanza para el caso
# concurrente sin necesidad de locks.
_catalogos_cache: Optional[_CatalogosCacheEntry] = None


def _obtener_catalogo_categorias_cacheado() -> Dict[str, List[str]]:
    """Como ``_construir_catalogo_categorias`` pero con un cache TTL en
    memoria, para no golpear Firestore (stream de la colección completa)
    en cada request al endpoint de catálogos.
    """
    global _catalogos_cache

    entry = _catalogos_cache
    now = time.monotonic()
    if entry is not None and entry.expires_at > now:
        return entry.value

    value = _construir_catalogo_categorias()
    _catalogos_cache = _CatalogosCacheEntry(
        value=value, expires_at=now + _AVANZADAS_CATALOGOS_TTL_SECONDS
    )
    return value


def _invalidar_cache_catalogos() -> None:
    global _catalogos_cache
    _catalogos_cache = None


def _mes_valido(fecha) -> Optional[str]:
    """Extrae 'YYYY-MM' de un campo ``fecha`` si es un string bien formado
    (al menos 7 caracteres); retorna None ante cualquier dato defectuoso
    (ausente, no-string, demasiado corto) para que el llamador lo pueda
    descartar sin arriesgar un crash.
    """
    if not isinstance(fecha, str) or len(fecha) < 7:
        return None
    return fecha[:7]


def _rango_meses(mes_inicio: str, mes_fin: str) -> List[str]:
    """Genera la lista de meses 'YYYY-MM' entre ``mes_inicio`` y
    ``mes_fin`` (ambos inclusive), en orden cronológico ascendente. Se
    usa para rellenar con ceros los meses sin datos y así evitar huecos
    en la serie de ``por_mes``.
    """
    anio_inicio, mes_i = int(mes_inicio[:4]), int(mes_inicio[5:7])
    anio_fin, mes_f = int(mes_fin[:4]), int(mes_fin[5:7])

    meses: List[str] = []
    anio, mes = anio_inicio, mes_i
    while (anio, mes) <= (anio_fin, mes_f):
        meses.append(f"{anio:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            mes = 1
            anio += 1
    return meses


def _calcular_estadisticas() -> dict:
    """Recorre ``avanzadas`` y ``avanzadas_requerimientos`` UNA sola vez
    cada una y calcula todas las agregaciones del dashboard de
    estadísticas en memoria (nada de N+1 contra Firestore).

    Retorna un dict plano (no un ``EstadisticasOut``) para que el cache
    TTL que lo envuelve (``_obtener_estadisticas_cacheado``) pueda
    devolver copias baratas sin acoplarse a Pydantic.
    """
    avanzada_docs = list(db.collection("avanzadas").stream())
    requerimiento_docs = list(db.collection("avanzadas_requerimientos").stream())
    # Jornadas Integrales (Parte 2 del feature): los requerimientos de
    # origen 'jornada' viven en la MISMA colección 'avanzadas_requerimientos'
    # (ver docstring del módulo), así que por_entidad/por_categoria/
    # totales.requerimientos ya los cuentan sin cambios (no se filtran por
    # origen). Lo único que necesita el join explícito contra
    # 'jornadas_integrales' es por_comuna, más abajo.
    jornada_docs = list(db.collection("jornadas_integrales").stream())

    avanzadas = [d.to_dict() or {} for d in avanzada_docs]
    avanzadas_por_id = {d.id: (d.to_dict() or {}) for d in avanzada_docs}
    jornadas_por_id = {d.id: (d.to_dict() or {}) for d in jornada_docs}
    requerimientos = [d.to_dict() or {} for d in requerimiento_docs]

    total_avanzadas = len(avanzadas)
    total_requerimientos = len(requerimientos)

    comunas_distintas = {
        a.get("comuna") for a in avanzadas if (a.get("comuna") or "").strip()
    }

    total_asistentes = sum(len(a.get("asistentes") or []) for a in avanzadas)

    promedio_requerimientos = (
        round(total_requerimientos / total_avanzadas, 1) if total_avanzadas else 0
    )

    # ---- por_entidad ----
    # Se guarda el string completo de entidad la PRIMERA vez que aparece
    # cada sigla, en orden de iteración del stream. No se calcula "el más
    # frecuente": para el nombre de una entidad todas las apariciones
    # deberían ser idénticas, así que first-seen es más simple y
    # suficiente.
    entidad_primera_vista: Dict[str, str] = {}
    entidad_totales: Dict[str, int] = {}
    for r in requerimientos:
        entidad_completa = r.get("entidad") or ""
        sigla = _sigla_entidad(entidad_completa)
        if sigla not in entidad_primera_vista:
            entidad_primera_vista[sigla] = entidad_completa
        entidad_totales[sigla] = entidad_totales.get(sigla, 0) + 1

    por_entidad = sorted(
        (
            {"sigla": sigla, "entidad": entidad_primera_vista[sigla], "total": total}
            for sigla, total in entidad_totales.items()
        ),
        # Orden: total DESC, tie-break sigla ASC.
        key=lambda x: (-x["total"], x["sigla"]),
    )
    total_entidades = len(por_entidad)

    # ---- por_categoria ----
    categoria_totales: Dict[tuple, int] = {}
    for r in requerimientos:
        personalizada = (r.get("categoria_personalizada") or "").strip()
        categoria_efectiva = personalizada or (r.get("categoria") or "").strip()
        if not categoria_efectiva:
            continue
        sigla = _sigla_entidad(r.get("entidad") or "")
        key = (categoria_efectiva, sigla)
        categoria_totales[key] = categoria_totales.get(key, 0) + 1

    por_categoria_completo = sorted(
        (
            {"categoria": categoria, "sigla": sigla, "total": total}
            for (categoria, sigla), total in categoria_totales.items()
        ),
        # Orden: total DESC, tie-break categoria ASC, luego sigla ASC.
        # La tercera clave (sigla) no la pide el negocio explícitamente,
        # pero sin ella un empate en (total, categoria) quedaría a merced
        # del orden de iteración del dict -> no determinista.
        key=lambda x: (-x["total"], x["categoria"], x["sigla"]),
    )
    por_categoria = por_categoria_completo[:12]

    # ---- por_comuna ----
    comuna_avanzadas: Dict[str, int] = {}
    for a in avanzadas:
        comuna = (a.get("comuna") or "").strip()
        if not comuna:
            continue
        comuna_avanzadas[comuna] = comuna_avanzadas.get(comuna, 0) + 1

    comuna_requerimientos: Dict[str, int] = {}
    estrategia_avanzadas: Dict[str, int] = {}
    for a in avanzadas:
        estrategia = (a.get("estrategia") or "").strip()
        if estrategia:
            estrategia_avanzadas[estrategia] = estrategia_avanzadas.get(estrategia, 0) + 1

    estrategia_requerimientos: Dict[str, int] = {}
    for r in requerimientos:
        # origen ausente == 'avanzada': back-compat obligatorio con los
        # 326 documentos migrados antes de que este campo existiera (ver
        # docstring del módulo, Parte 2 del feature de Jornadas
        # Integrales). Nunca se debe tratar un doc legacy como huérfano
        # solo por no tener 'origen'.
        origen = r.get("origen") or "avanzada"

        if origen == "jornada":
            jornada_padre = jornadas_por_id.get(r.get("jornada_client_id"))
            if jornada_padre is None:
                # Requerimiento huérfano (su jornada padre no existe):
                # mismo criterio que un huérfano de avanzada -- se excluye
                # silenciosamente de por_comuna en vez de fallar la
                # request.
                continue
            comuna = (jornada_padre.get("comuna") or "").strip()
            if comuna:
                comuna_requerimientos[comuna] = comuna_requerimientos.get(comuna, 0) + 1
            # por_estrategia es EXCLUSIVO de requerimientos de origen
            # avanzada a propósito: las jornadas no tienen concepto de
            # "estrategia de intervención" (eso es un atributo propio de
            # Avanzadas Diagnósticas). No se fabrica una estrategia falsa
            # ni se reutiliza ninguna otra noción para jornadas -- por
            # eso este bucle simplemente no las suma acá.
            continue

        avanzada_padre = avanzadas_por_id.get(r.get("avanzada_client_id"))
        if avanzada_padre is None:
            # Requerimiento huérfano: su avanzada padre no existe (caso
            # real observado en producción). Se excluye silenciosamente
            # de las agregaciones por comuna/estrategia -- no se puede
            # unir sin la avanzada -- en vez de fallar la request.
            continue

        comuna = (avanzada_padre.get("comuna") or "").strip()
        if comuna:
            comuna_requerimientos[comuna] = comuna_requerimientos.get(comuna, 0) + 1

        estrategia = (avanzada_padre.get("estrategia") or "").strip()
        if estrategia:
            estrategia_requerimientos[estrategia] = estrategia_requerimientos.get(estrategia, 0) + 1

    todas_comunas = set(comuna_avanzadas) | set(comuna_requerimientos)
    por_comuna = sorted(
        (
            {
                "comuna": comuna,
                "avanzadas": comuna_avanzadas.get(comuna, 0),
                "requerimientos": comuna_requerimientos.get(comuna, 0),
            }
            for comuna in todas_comunas
        ),
        # Orden: requerimientos DESC, tie-break comuna ASC.
        key=lambda x: (-x["requerimientos"], x["comuna"]),
    )

    # ---- por_estrategia ----
    todas_estrategias = set(estrategia_avanzadas) | set(estrategia_requerimientos)
    por_estrategia = sorted(
        (
            {
                "estrategia": estrategia,
                "avanzadas": estrategia_avanzadas.get(estrategia, 0),
                "requerimientos": estrategia_requerimientos.get(estrategia, 0),
            }
            for estrategia in todas_estrategias
        ),
        # Orden: avanzadas DESC, tie-break estrategia ASC.
        key=lambda x: (-x["avanzadas"], x["estrategia"]),
    )

    # ---- por_mes ----
    mes_avanzadas: Dict[str, int] = {}
    mes_requerimientos: Dict[str, int] = {}
    for a in avanzadas:
        mes = _mes_valido(a.get("fecha"))
        if mes:
            mes_avanzadas[mes] = mes_avanzadas.get(mes, 0) + 1
    for r in requerimientos:
        # Los requerimientos llevan su propia 'fecha' denormalizada (ver
        # docstring del módulo) -- no hace falta volver a la avanzada
        # padre para esto.
        mes = _mes_valido(r.get("fecha"))
        if mes:
            mes_requerimientos[mes] = mes_requerimientos.get(mes, 0) + 1

    todos_meses = set(mes_avanzadas) | set(mes_requerimientos)
    if todos_meses:
        por_mes = [
            {
                "mes": mes,
                "avanzadas": mes_avanzadas.get(mes, 0),
                "requerimientos": mes_requerimientos.get(mes, 0),
            }
            for mes in _rango_meses(min(todos_meses), max(todos_meses))
        ]
    else:
        por_mes = []

    return {
        "totales": {
            "avanzadas": total_avanzadas,
            "requerimientos": total_requerimientos,
            "comunas": len(comunas_distintas),
            "entidades": total_entidades,
            "asistentes": total_asistentes,
            "promedio_requerimientos": promedio_requerimientos,
        },
        "por_entidad": por_entidad,
        "por_categoria": por_categoria,
        "por_comuna": por_comuna,
        "por_estrategia": por_estrategia,
        "por_mes": por_mes,
    }


# TTL (segundos) del cache en memoria de las estadísticas agregadas de
# avanzadas/requerimientos. Mismo patrón que el cache de catálogos:
# configurable por env var para debugging o para aliviar presión sobre
# Firestore.
_AVANZADAS_ESTADISTICAS_TTL_SECONDS = float(os.getenv("AVANZADAS_ESTADISTICAS_TTL_SECONDS", "60"))


@dataclass
class _EstadisticasCacheEntry:
    value: dict
    expires_at: float


# Cache module-level, sin dependencias externas (ver comentario análogo
# en ``_catalogos_cache``: una asignación de variable global es atómica
# en CPython).
_estadisticas_cache: Optional[_EstadisticasCacheEntry] = None


def _obtener_estadisticas_cacheado() -> dict:
    """Como ``_calcular_estadisticas`` pero con un cache TTL en memoria,
    para no recorrer ambas colecciones completas (avanzadas +
    avanzadas_requerimientos) en cada request al endpoint de
    estadísticas.

    Devuelve siempre una copia profunda del valor cacheado: si quien
    llama muta el dict/lista recibido, el cache guardado para el
    próximo hit queda intacto.
    """
    global _estadisticas_cache

    entry = _estadisticas_cache
    now = time.monotonic()
    if entry is not None and entry.expires_at > now:
        return copy.deepcopy(entry.value)

    value = _calcular_estadisticas()
    _estadisticas_cache = _EstadisticasCacheEntry(
        value=value, expires_at=now + _AVANZADAS_ESTADISTICAS_TTL_SECONDS
    )
    return copy.deepcopy(value)


def _invalidar_cache_estadisticas() -> None:
    global _estadisticas_cache
    _estadisticas_cache = None


def _calcular_geo() -> dict:
    """Recorre ``avanzadas``, ``avanzadas_requerimientos`` y
    ``jornadas_integrales`` UNA sola vez cada una y arma los tres
    arreglos de puntos georreferenciados para el mapa, parseando el
    campo ``coordenadas``/``coordenadas_encuentro`` (string "lat, lng")
    con ``_parsear_coordenadas``.

    Los registros sin coordenadas parseables se OMITEN (nunca se
    fabrica una ubicación 0,0 ni se hereda la coordenada de un padre) y
    se contabilizan en ``omitidos`` para que el frontend pueda mostrar
    honestamente "N sin ubicación".
    """
    avanzada_docs = list(db.collection("avanzadas").stream())
    requerimiento_docs = list(db.collection("avanzadas_requerimientos").stream())
    jornada_docs = list(db.collection("jornadas_integrales").stream())

    # Lookups por id para resolver el padre de cada requerimiento según su
    # origen (ver bucle de requerimientos_out más abajo).
    avanzadas_por_id = {d.id: (d.to_dict() or {}) for d in avanzada_docs}
    jornadas_por_id = {d.id: (d.to_dict() or {}) for d in jornada_docs}

    avanzadas_out: List[dict] = []
    omitidos_avanzadas = 0
    for doc in avanzada_docs:
        data = doc.to_dict() or {}
        coords = _parsear_coordenadas(data.get("coordenadas"))
        if coords is None:
            omitidos_avanzadas += 1
            continue
        lat, lng = coords
        avanzadas_out.append({
            "client_id": doc.id,
            "nombre_avanzada": data.get("nombre_avanzada", ""),
            "fecha": data.get("fecha", ""),
            "estrategia": data.get("estrategia", ""),
            "comuna": data.get("comuna", ""),
            "barrio": data.get("barrio", ""),
            "lat": lat,
            "lng": lng,
            "requerimientos_count": data.get("requerimientos_count", 0),
        })

    requerimientos_out: List[dict] = []
    omitidos_requerimientos = 0
    for doc in requerimiento_docs:
        data = doc.to_dict() or {}
        # Sin fallback a la coordenada del padre (avanzada o jornada):
        # heredarla fabricaría una ubicación que el requerimiento nunca
        # reportó.
        coords = _parsear_coordenadas(data.get("coordenadas"))
        if coords is None:
            omitidos_requerimientos += 1
            continue

        # origen ausente == 'avanzada' (back-compat con los 326 docs
        # migrados antes de que este campo existiera -- ver Parte 2 en el
        # docstring del módulo).
        origen = data.get("origen") or "avanzada"
        if origen == "jornada":
            padre = jornadas_por_id.get(data.get("jornada_client_id"))
        else:
            padre = avanzadas_por_id.get(data.get("avanzada_client_id"))
        if padre is None:
            # Huérfano (referencia colgante a una avanzada o jornada que
            # ya no existe): se omite del mapa y se cuenta en 'omitidos',
            # igual que un requerimiento sin coordenadas parseables.
            omitidos_requerimientos += 1
            continue

        lat, lng = coords
        entidad = data.get("entidad") or ""
        categoria_personalizada = (data.get("categoria_personalizada") or "").strip()
        categoria = categoria_personalizada or (data.get("categoria") or "")
        fotos = data.get("fotos_urls") or []
        requerimientos_out.append({
            "id": doc.id,
            "avanzada_client_id": data.get("avanzada_client_id") or "",
            "origen": origen,
            "sigla": _sigla_entidad(entidad),
            "entidad": entidad,
            "categoria": categoria,
            "requerimiento": data.get("requerimiento", ""),
            "ubicacion": data.get("ubicacion", ""),
            "fecha": data.get("fecha", ""),
            "lat": lat,
            "lng": lng,
            "fotos_count": len(fotos),
        })

    jornadas_out: List[dict] = []
    omitidos_jornadas = 0
    for doc in jornada_docs:
        data = doc.to_dict() or {}
        coords = _parsear_coordenadas(data.get("coordenadas_encuentro"))
        if coords is None:
            omitidos_jornadas += 1
            continue
        lat, lng = coords
        jornadas_out.append({
            "client_id": doc.id,
            "nombre_jornada": data.get("nombre_jornada", ""),
            "fecha": data.get("fecha", ""),
            "comuna": data.get("comuna", ""),
            "barrio": data.get("barrio", ""),
            "estado": data.get("estado", ""),
            "lat": lat,
            "lng": lng,
        })

    return {
        "avanzadas": avanzadas_out,
        "requerimientos": requerimientos_out,
        "jornadas": jornadas_out,
        "omitidos": {
            "avanzadas": omitidos_avanzadas,
            "requerimientos": omitidos_requerimientos,
            "jornadas": omitidos_jornadas,
        },
    }


# TTL (segundos) del cache en memoria de los puntos georreferenciados.
# Mismo patrón que el cache de estadísticas: configurable por env var.
_AVANZADAS_GEO_TTL_SECONDS = float(os.getenv("AVANZADAS_GEO_TTL_SECONDS", "60"))


@dataclass
class _GeoCacheEntry:
    value: dict
    expires_at: float


_geo_cache: Optional[_GeoCacheEntry] = None


def _obtener_geo_cacheado() -> dict:
    """Como ``_calcular_geo`` pero con un cache TTL en memoria (mismo
    patrón que ``_obtener_estadisticas_cacheado``), para no recorrer las
    tres colecciones completas en cada request al endpoint de mapa.

    Devuelve siempre una copia profunda del valor cacheado para que un
    caller que mute el resultado no corrompa el cache.
    """
    global _geo_cache

    entry = _geo_cache
    now = time.monotonic()
    if entry is not None and entry.expires_at > now:
        return copy.deepcopy(entry.value)

    value = _calcular_geo()
    _geo_cache = _GeoCacheEntry(value=value, expires_at=now + _AVANZADAS_GEO_TTL_SECONDS)
    return copy.deepcopy(value)


def _invalidar_cache_geo() -> None:
    global _geo_cache
    _geo_cache = None


def _upsert_categoria_personalizada(entidad_sigla: str, categoria: str, fecha: str) -> None:
    """Registra una categoría personalizada nueva si (entidad, categoria) no existe aún."""
    existentes = (
        db.collection("categorias_personalizadas")
        .where("entidad", "==", entidad_sigla)
        .where("categoria", "==", categoria)
        .limit(1)
        .get()
    )
    if existentes:
        return

    db.collection("categorias_personalizadas").document().set({
        "entidad": entidad_sigla,
        "categoria": categoria,
        "fecha": fecha,
    })
    # Solo invalidamos cuando insertamos una categoría NUEVA: un duplicado
    # no cambia el catálogo, así que no vale la pena tirar el cache.
    _invalidar_cache_catalogos()


def _parse_avanzada_payload(datos: str) -> AvanzadaCreateIn:
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
        return AvanzadaCreateIn(**parsed)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())


def _agrupar_fotos_por_requerimiento(form) -> Dict[int, list]:
    """Agrupa los UploadFile recibidos por índice de requerimiento a partir
    de los nombres de campo ``fotos_req_{i}`` (repetibles en el multipart).
    """
    agrupadas: Dict[int, list] = {}
    for key in set(form.keys()):
        match = _FOTO_REQ_FIELD_RE.match(key)
        if not match:
            continue
        idx = int(match.group(1))
        archivos = [f for f in form.getlist(key) if getattr(f, "filename", None)]
        if archivos:
            agrupadas.setdefault(idx, []).extend(archivos)
    return agrupadas


def _avanzada_existente_a_out(avanzada_doc) -> AvanzadaOut:
    data = avanzada_doc.to_dict() or {}
    client_id = avanzada_doc.id

    # Se ordena en Python (en vez de encadenar .order_by("req_index")) a
    # propósito: en Firestore, un filtro de igualdad sobre un campo (aquí
    # avanzada_client_id) combinado con order_by() sobre un campo DISTINTO
    # (req_index) requiere un índice compuesto. El volumen de
    # requerimientos por avanzada es chico (un puñado por jornada de
    # campo), así que ordenar en memoria evita tener que provisionar ese
    # índice sin costo real de performance.
    req_docs = (
        db.collection("avanzadas_requerimientos")
        .where("avanzada_client_id", "==", client_id)
        .get()
    )
    requerimientos = sorted(
        (_requerimiento_doc_to_out(d) for d in req_docs),
        key=lambda r: r.get("req_index", 0),
    )

    return AvanzadaOut(
        id=client_id,
        client_id=client_id,
        nombre_avanzada=data.get("nombre_avanzada", ""),
        fecha=data.get("fecha", ""),
        estrategia=data.get("estrategia", ""),
        sector=data.get("sector"),
        comuna=data.get("comuna", ""),
        barrio=data.get("barrio", ""),
        direccion=data.get("direccion", ""),
        coordenadas=data.get("coordenadas", ""),
        encargados=data.get("encargados", []),
        asistentes=data.get("asistentes", []),
        foto_equipo_url=data.get("foto_equipo_url"),
        created_by=data.get("created_by", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        numero=data.get("numero", 0),
        requerimientos_count=data.get("requerimientos_count", len(requerimientos)),
        requerimientos=requerimientos,
    )


# ==================== CATÁLOGOS ====================

@router.get(
    "/catalogos",
    summary="📋 GET | Catálogos de Avanzadas Diagnósticas",
    response_model=CatalogosOut,
)
async def get_catalogos(current_user: dict = Depends(get_current_user)):
    """
    Retorna los catálogos base para el formulario de avanzada: estrategias
    de intervención, equipo operativo, dependencias/entidades y categorías
    de requerimiento por entidad (defaults + personalizadas registradas
    en campo).
    """
    try:
        return CatalogosOut(
            estrategias=ESTRATEGIAS_DEFAULT,
            equipo=EQUIPO_DEFAULT,
            dependencias=DEPENDENCIAS_DEFAULT,
            categorias=_obtener_catalogo_categorias_cacheado(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo catálogos: {str(e)}")


# ==================== CREAR AVANZADA ====================

@router.post(
    "",
    summary="🟢 POST | Registrar Avanzada Diagnóstica",
    response_model=AvanzadaOut,
)
async def crear_avanzada(
    request: Request,
    datos: str = Form(..., description="Datos de la avanzada en formato JSON (ver AvanzadaCreateIn)"),
    foto_equipo: Optional[UploadFile] = File(None, description="Foto grupal del equipo (opcional)"),
    current_user: dict = Depends(get_current_user),
):
    """
    Registra una nueva Avanzada Diagnóstica junto con sus requerimientos.

    Es idempotente por ``client_id``: si ya existe una avanzada con ese
    identificador (generado en el cliente), se retorna la existente con
    status 200 sin duplicar nada. Si es nueva, se crea y se retorna con
    status 201.
    """
    payload = _parse_avanzada_payload(datos)

    avanzada_ref = db.collection("avanzadas").document(payload.client_id)
    existente = avanzada_ref.get()
    if existente.exists:
        return _responder(_avanzada_existente_a_out(existente), status_code=200)

    form = await request.form()
    fotos_por_requerimiento = _agrupar_fotos_por_requerimiento(form)

    bucket_name = s3_storage.bucket_name()
    s3_client = None
    necesita_s3 = bool(foto_equipo and foto_equipo.filename) or bool(fotos_por_requerimiento)
    if necesita_s3:
        try:
            s3_client = get_s3_client()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error configurando S3: {str(e)}")

    # Subimos TODAS las fotos (equipo + requerimientos) antes de escribir
    # nada en Firestore. Así, si una subida falla a mitad de camino, no
    # queda ningún documento a medio crear que el cliente deba limpiar.
    foto_equipo_url: Optional[str] = None
    requerimientos_fotos_urls: Dict[int, List[str]] = {}
    try:
        if foto_equipo and foto_equipo.filename:
            contenido = await foto_equipo.read()
            if contenido:
                subida = s3_storage.upload_file(
                    contenido,
                    modulo="avanzadas",
                    client_id=payload.client_id,
                    categoria="equipo",
                    filename=foto_equipo.filename,
                    content_type=foto_equipo.content_type,
                    s3_client=s3_client,
                    bucket=bucket_name,
                )
                foto_equipo_url = subida["s3_url"]

        for idx, req_in in enumerate(payload.requerimientos):
            archivos = fotos_por_requerimiento.get(idx, [])[:_MAX_FOTOS_POR_REQUERIMIENTO]
            fotos_urls: List[str] = []
            for archivo in archivos:
                contenido = await archivo.read()
                if not contenido:
                    continue
                subida = s3_storage.upload_file(
                    contenido,
                    modulo="avanzadas",
                    client_id=payload.client_id,
                    categoria=f"requerimientos/{idx}",
                    filename=archivo.filename,
                    content_type=archivo.content_type,
                    s3_client=s3_client,
                    bucket=bucket_name,
                )
                fotos_urls.append(subida["s3_url"])
            requerimientos_fotos_urls[idx] = fotos_urls
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Error subiendo fotos a almacenamiento externo")

    numero = list(db.collection("avanzadas").count().get())[0][0].value + 1
    now = now_colombia().isoformat()
    uid = current_user.get("uid", "sistema")

    # Armar los documentos de requerimientos (las fotos ya están subidas).
    requerimientos_out: List[RequerimientoAvanzadaOut] = []
    for idx, req_in in enumerate(payload.requerimientos):
        req_data = {
            "avanzada_client_id": payload.client_id,
            # jornada_client_id / origen: Parte 2 del feature de Jornadas
            # Integrales -- esta colección es compartida entre Avanzadas
            # Diagnósticas y Jornadas Integrales (ver docstring del
            # módulo). Los requerimientos creados acá son siempre de
            # origen 'avanzada'.
            "jornada_client_id": None,
            "origen": "avanzada",
            "req_index": idx,
            "entidad": req_in.entidad,
            "categoria": req_in.categoria,
            "categoria_personalizada": req_in.categoria_personalizada,
            "requerimiento": req_in.requerimiento,
            "ubicacion": req_in.ubicacion,
            "coordenadas": req_in.coordenadas,
            "fotos_urls": requerimientos_fotos_urls.get(idx, []),
            "fecha": payload.fecha,
            "nombre_avanzada": payload.nombre_avanzada,
            # nombre_origen: poblado para AMBOS orígenes (ver Parte 2) --
            # para origen='avanzada' es el nombre de la avanzada (mismo
            # valor que 'nombre_avanzada', que se sigue escribiendo para
            # no romper lectores viejos que todavía no conocen este
            # campo).
            "nombre_origen": payload.nombre_avanzada,
            "estrategia": payload.estrategia,
            "created_at": now,
        }
        # ID determinístico (client_id + índice) para que un reintento con
        # el mismo client_id sobrescriba el mismo requerimiento en vez de
        # crear uno nuevo con id aleatorio junto al huérfano previo.
        req_doc_id = f"{payload.client_id}_{idx}"
        req_doc_ref = db.collection("avanzadas_requerimientos").document(req_doc_id)
        req_doc_ref.set(req_data)
        req_data["id"] = req_doc_ref.id
        requerimientos_out.append(RequerimientoAvanzadaOut(**req_data))

        if req_in.categoria_personalizada and req_in.categoria_personalizada.strip():
            _upsert_categoria_personalizada(
                entidad_sigla=_sigla_entidad(req_in.entidad),
                categoria=req_in.categoria_personalizada.strip(),
                fecha=payload.fecha,
            )

    avanzada_data = {
        "client_id": payload.client_id,
        "nombre_avanzada": payload.nombre_avanzada,
        "fecha": payload.fecha,
        "estrategia": payload.estrategia,
        "sector": payload.sector,
        "comuna": payload.comuna,
        "barrio": payload.barrio,
        "direccion": payload.direccion,
        "coordenadas": payload.coordenadas,
        "encargados": payload.encargados,
        "asistentes": [a.model_dump() for a in payload.asistentes],
        "foto_equipo_url": foto_equipo_url,
        "created_by": uid,
        "created_at": now,
        "updated_at": now,
        "numero": numero,
        "requerimientos_count": len(requerimientos_out),
    }
    avanzada_ref.set(avanzada_data)
    # Se creó una avanzada NUEVA (con requerimientos nuevos): las
    # estadísticas y los puntos de mapa cacheados quedaron desactualizados.
    # La rama idempotente (arriba, cuando ya existía) no llega hasta acá
    # porque no cambió nada.
    _invalidar_cache_estadisticas()
    _invalidar_cache_geo()

    resultado = AvanzadaOut(
        id=payload.client_id,
        client_id=payload.client_id,
        requerimientos=requerimientos_out,
        **{k: v for k, v in avanzada_data.items() if k != "client_id"},
    )
    return _responder(resultado, status_code=201)


def _responder(resultado: AvanzadaOut, status_code: int):
    """FastAPI no permite variar el status_code declarado en el decorador
    según la rama del handler, así que devolvemos una JSONResponse manual
    (idempotente = 200, creada = 201) mientras seguimos validando la forma
    de la respuesta contra ``AvanzadaOut``.
    """
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    return JSONResponse(content=jsonable_encoder(resultado), status_code=status_code)


# ==================== LISTAR AVANZADAS ====================

@router.get(
    "",
    summary="📋 GET | Listar Avanzadas Diagnósticas",
    response_model=List[AvanzadaListItemOut],
)
async def listar_avanzadas(
    limit: int = Query(100, ge=1, le=500, description="Máximo de avanzadas a retornar"),
    current_user: dict = Depends(get_current_user),
):
    """
    Lista las avanzadas registradas, ordenadas por fecha descendente,
    con el conteo de requerimientos de cada una.
    """
    try:
        docs = (
            db.collection("avanzadas")
            .order_by("fecha", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        resultado = []
        for doc in docs:
            data = doc.to_dict() or {}
            data["id"] = doc.id
            data["client_id"] = doc.id
            resultado.append(data)
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listando avanzadas: {str(e)}")


# ==================== ESTADÍSTICAS ====================
# IMPORTANTE: esta ruta debe declararse ANTES de "/{client_id}" (más
# abajo). FastAPI matchea rutas en orden de declaración, así que si
# "/{client_id}" quedara primero, un GET a /avanzadas/estadisticas sería
# interceptado por el handler dinámico (tratando "estadisticas" como si
# fuera un client_id) en vez de llegar acá.

@router.get(
    "/estadisticas",
    summary="📊 GET | Estadísticas de Avanzadas Diagnósticas",
    response_model=EstadisticasOut,
)
async def obtener_estadisticas_avanzadas(current_user: dict = Depends(get_current_user)):
    """
    Retorna estadísticas agregadas en servidor sobre las avanzadas y sus
    requerimientos (totales, distribución por entidad/categoría/comuna/
    estrategia/mes), para alimentar el dashboard de estadísticas del
    frontend.

    El cálculo completo se cachea con un TTL en memoria (ver
    ``_obtener_estadisticas_cacheado``) para no recorrer ambas
    colecciones completas en cada request.
    """
    try:
        return EstadisticasOut(**_obtener_estadisticas_cacheado())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculando estadísticas: {str(e)}")


# ==================== PUNTOS GEORREFERENCIADOS (MAPA) ====================
# IMPORTANTE: mismo motivo que "/estadisticas" arriba -- esta ruta debe
# declararse ANTES de "/{client_id}" para que FastAPI no la intercepte
# con el handler dinámico (tratando "geo" como si fuera un client_id).

@router.get(
    "/geo",
    summary="🗺️ GET | Puntos georreferenciados de Avanzadas Diagnósticas",
    response_model=GeoOut,
)
async def obtener_geo_avanzadas(current_user: dict = Depends(get_current_user)):
    """
    Retorna los puntos georreferenciados (avanzadas, requerimientos y
    jornadas integrales) para pintar en el mapa del frontend, parseando
    el campo ``coordenadas``/``coordenadas_encuentro`` almacenado como
    string "lat, lng". Los registros sin coordenadas parseables se
    omiten y se cuentan en ``omitidos`` en vez de fabricar una ubicación.

    El cálculo completo se cachea con un TTL en memoria (ver
    ``_obtener_geo_cacheado``) para no recorrer las tres colecciones
    completas en cada request.
    """
    try:
        return GeoOut(**_obtener_geo_cacheado())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculando puntos georreferenciados: {str(e)}")


# ==================== ACTUALIZAR AVANZADA (PATCH / PUT) ====================
# IMPORTANTE: mismo motivo que "/estadisticas" y "/geo" arriba -- estas
# rutas (y las de requerimientos más abajo) deben declararse ANTES de
# "/{client_id}" para que FastAPI no las intercepte con el handler dinámico.

async def _actualizar_avanzada(client_id: str, cambios: dict) -> AvanzadaOut:
    """Núcleo compartido de actualización de Avanzada: valida existencia,
    aplica ``cambios`` (diff parcial para PATCH, payload completo para PUT),
    bump de ``updated_at`` e invalidación de caches.

    Compartir este núcleo entre PATCH y PUT es la Decisión de diseño #3:
    PUT es un alias delgado del PATCH, no una implementación duplicada.
    """
    avanzada_ref = db.collection("avanzadas").document(client_id)
    doc = avanzada_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Avanzada '{client_id}' no encontrada")

    cambios["updated_at"] = now_colombia().isoformat()
    avanzada_ref.update(cambios)
    _invalidar_cache_estadisticas()
    _invalidar_cache_geo()

    return _avanzada_existente_a_out(avanzada_ref.get())


@router.patch(
    "/{client_id}",
    summary="🟡 PATCH | Actualizar Avanzada Diagnóstica (parcial)",
    response_model=AvanzadaOut,
)
async def actualizar_avanzada_parcial(
    client_id: str,
    payload: AvanzadaPatchIn,
    current_user: dict = Depends(get_current_user),
):
    """Actualización parcial: solo se aplican los campos efectivamente
    enviados en el body."""
    cambios = payload.model_dump(exclude_unset=True)
    return await _actualizar_avanzada(client_id, cambios)


@router.put(
    "/{client_id}",
    summary="🟡 PUT | Reemplazar Avanzada Diagnóstica (completo)",
    response_model=AvanzadaOut,
)
async def reemplazar_avanzada(
    client_id: str,
    payload: AvanzadaPutIn,
    current_user: dict = Depends(get_current_user),
):
    """Reemplazo completo: los campos opcionales omitidos vuelven al default
    del schema (ver ``AvanzadaPutIn``). Alias delgado sobre el mismo núcleo
    que PATCH (Decisión de diseño #3)."""
    cambios = payload.model_dump()
    return await _actualizar_avanzada(client_id, cambios)


# ==================== ELIMINAR AVANZADA (cascada dura) ====================

@router.delete(
    "/{client_id}",
    summary="🔴 DELETE | Eliminar Avanzada Diagnóstica (cascada)",
    status_code=204,
)
async def eliminar_avanzada(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Elimina la avanzada, todos sus requerimientos (``avanzadas_requerimientos``
    con ``avanzada_client_id == client_id``) y sus objetos S3 asociados
    (borrado por prefijo ``avanzadas/{client_id}/``).

    Cascada dura (no soft-delete): Decisión de diseño #4 -- los
    requerimientos son propiedad exclusiva de la avanzada, y no existe un
    patrón de soft-delete en el resto del código.
    """
    avanzada_ref = db.collection("avanzadas").document(client_id)
    doc = avanzada_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Avanzada '{client_id}' no encontrada")

    req_docs = (
        db.collection("avanzadas_requerimientos")
        .where("avanzada_client_id", "==", client_id)
        .get()
    )
    for req_doc in req_docs:
        db.collection("avanzadas_requerimientos").document(req_doc.id).delete()

    avanzada_ref.delete()

    try:
        s3_client = get_s3_client()
        s3_storage.delete_prefix(
            f"avanzadas/{client_id}/",
            s3_client=s3_client,
            bucket=s3_storage.bucket_name(),
        )
    except Exception:
        # Borrado de S3 es best-effort: no bloquear la eliminación en
        # Firestore por un problema de credenciales/red con S3.
        pass

    _invalidar_cache_estadisticas()
    _invalidar_cache_geo()

    return Response(status_code=204)


# ==================== SUB-RECURSO: REQUERIMIENTOS DE AVANZADA ====================

@router.post(
    "/{client_id}/requerimientos",
    summary="🟢 POST | Agregar Requerimiento a Avanzada",
    response_model=RequerimientoAvanzadaOut,
    status_code=201,
)
async def crear_requerimiento_avanzada(
    client_id: str,
    request: Request,
    datos: str = Form(..., description="Datos del requerimiento en formato JSON (ver RequerimientoAvanzadaIn)"),
    current_user: dict = Depends(get_current_user),
):
    """Crea un requerimiento suelto dentro de una avanzada existente (fuera
    del flujo de creación inline de ``POST /avanzadas``).

    El ``req_index`` asignado es ``max(req_index existentes) + 1`` (nunca
    ``len(...)``, ver Decisión de diseño #5): así nunca colisiona con un
    índice liberado por un DELETE previo.
    """
    avanzada_ref = db.collection("avanzadas").document(client_id)
    avanzada_doc = avanzada_ref.get()
    if not avanzada_doc.exists:
        raise HTTPException(status_code=404, detail=f"Avanzada '{client_id}' no encontrada")

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
        req_in = RequerimientoAvanzadaIn(**parsed)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    form = await request.form()
    archivos = [f for f in form.getlist("fotos") if getattr(f, "filename", None)]
    archivos = archivos[:_MAX_FOTOS_POR_REQUERIMIENTO]

    req_index = _siguiente_req_index(client_id)

    fotos_urls: List[str] = []
    if archivos:
        try:
            s3_client = get_s3_client()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error configurando S3: {str(e)}")
        bucket = s3_storage.bucket_name()
        try:
            for archivo in archivos:
                contenido = await archivo.read()
                if not contenido:
                    continue
                subida = s3_storage.upload_file(
                    contenido,
                    modulo="avanzadas",
                    client_id=client_id,
                    categoria=f"requerimientos/{req_index}",
                    filename=archivo.filename,
                    content_type=archivo.content_type,
                    s3_client=s3_client,
                    bucket=bucket,
                )
                fotos_urls.append(subida["s3_url"])
        except Exception:
            raise HTTPException(status_code=502, detail="Error subiendo fotos a almacenamiento externo")

    avanzada_data = avanzada_doc.to_dict() or {}
    now = now_colombia().isoformat()
    req_data = {
        "avanzada_client_id": client_id,
        "jornada_client_id": None,
        "origen": "avanzada",
        "req_index": req_index,
        "entidad": req_in.entidad,
        "categoria": req_in.categoria,
        "categoria_personalizada": req_in.categoria_personalizada,
        "requerimiento": req_in.requerimiento,
        "ubicacion": req_in.ubicacion,
        "coordenadas": req_in.coordenadas,
        "fotos_urls": fotos_urls,
        "fecha": avanzada_data.get("fecha", ""),
        "nombre_avanzada": avanzada_data.get("nombre_avanzada", ""),
        "nombre_origen": avanzada_data.get("nombre_avanzada", ""),
        "estrategia": avanzada_data.get("estrategia", ""),
        "created_at": now,
    }
    req_doc_id = f"{client_id}_{req_index}"
    req_ref = db.collection("avanzadas_requerimientos").document(req_doc_id)
    req_ref.set(req_data)
    req_data["id"] = req_doc_id

    if req_in.categoria_personalizada and req_in.categoria_personalizada.strip():
        _upsert_categoria_personalizada(
            entidad_sigla=_sigla_entidad(req_in.entidad),
            categoria=req_in.categoria_personalizada.strip(),
            fecha=avanzada_data.get("fecha", ""),
        )

    avanzada_ref.update({
        "requerimientos_count": avanzada_data.get("requerimientos_count", 0) + 1,
        "updated_at": now,
    })
    _invalidar_cache_estadisticas()
    _invalidar_cache_geo()

    return RequerimientoAvanzadaOut(**req_data)


@router.get(
    "/{client_id}/requerimientos/{req_id}",
    summary="🔵 GET | Detalle de Requerimiento de Avanzada",
    response_model=RequerimientoAvanzadaOut,
)
async def obtener_requerimiento_avanzada(
    client_id: str,
    req_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = db.collection("avanzadas_requerimientos").document(req_id).get()
    if not doc.exists or (doc.to_dict() or {}).get("avanzada_client_id") != client_id:
        raise HTTPException(
            status_code=404,
            detail=f"Requerimiento '{req_id}' no encontrado en avanzada '{client_id}'",
        )
    return RequerimientoAvanzadaOut(**_requerimiento_doc_to_out(doc))


@router.patch(
    "/{client_id}/requerimientos/{req_id}",
    summary="🟡 PATCH | Actualizar Requerimiento de Avanzada",
    response_model=RequerimientoAvanzadaOut,
)
async def actualizar_requerimiento_avanzada(
    client_id: str,
    req_id: str,
    request: Request,
    datos: str = Form("{}", description="Campos a actualizar en formato JSON (ver RequerimientoAvanzadaPatchIn)"),
    current_user: dict = Depends(get_current_user),
):
    """Actualización parcial de un requerimiento, incluyendo agregar fotos
    nuevas (campo multipart ``fotos``) y/o eliminar fotos existentes
    (``fotos_eliminar`` en ``datos``, con las URLs a remover)."""
    req_ref = db.collection("avanzadas_requerimientos").document(req_id)
    doc = req_ref.get()
    data_actual = doc.to_dict() or {}
    if not doc.exists or data_actual.get("avanzada_client_id") != client_id:
        raise HTTPException(
            status_code=404,
            detail=f"Requerimiento '{req_id}' no encontrado en avanzada '{client_id}'",
        )

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
        patch_in = RequerimientoAvanzadaPatchIn(**parsed)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    cambios = patch_in.model_dump(exclude_unset=True, exclude={"fotos_eliminar"})

    fotos_urls = list(data_actual.get("fotos_urls", []))
    eliminadas = patch_in.fotos_eliminar or []
    fotos_tocadas = False
    if eliminadas:
        keys_a_borrar = [k for k in (_s3_key_from_url(u) for u in eliminadas) if k]
        if keys_a_borrar:
            try:
                s3_client = get_s3_client()
                s3_storage.delete_keys(
                    keys_a_borrar, s3_client=s3_client, bucket=s3_storage.bucket_name()
                )
            except Exception:
                pass
        fotos_urls = [u for u in fotos_urls if u not in eliminadas]
        fotos_tocadas = True

    form = await request.form()
    nuevas_fotos = [f for f in form.getlist("fotos") if getattr(f, "filename", None)]
    if nuevas_fotos:
        espacio_disponible = max(0, _MAX_FOTOS_POR_REQUERIMIENTO - len(fotos_urls))
        try:
            s3_client = get_s3_client()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error configurando S3: {str(e)}")
        bucket = s3_storage.bucket_name()
        req_index = data_actual.get("req_index", 0)
        try:
            for archivo in nuevas_fotos[:espacio_disponible]:
                contenido = await archivo.read()
                if not contenido:
                    continue
                subida = s3_storage.upload_file(
                    contenido,
                    modulo="avanzadas",
                    client_id=client_id,
                    categoria=f"requerimientos/{req_index}",
                    filename=archivo.filename,
                    content_type=archivo.content_type,
                    s3_client=s3_client,
                    bucket=bucket,
                )
                fotos_urls.append(subida["s3_url"])
        except Exception:
            raise HTTPException(status_code=502, detail="Error subiendo fotos a almacenamiento externo")
        fotos_tocadas = True

    if fotos_tocadas:
        cambios["fotos_urls"] = fotos_urls

    if cambios:
        req_ref.update(cambios)

    _invalidar_cache_estadisticas()
    _invalidar_cache_geo()

    return RequerimientoAvanzadaOut(**_requerimiento_doc_to_out(req_ref.get()))


@router.delete(
    "/{client_id}/requerimientos/{req_id}",
    summary="🔴 DELETE | Eliminar Requerimiento de Avanzada",
    status_code=204,
)
async def eliminar_requerimiento_avanzada(
    client_id: str,
    req_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Elimina el requerimiento, sus objetos S3 asociados (borrado por
    prefijo ``avanzadas/{client_id}/requerimientos/{req_index}/``) y
    decrementa ``requerimientos_count`` de la avanzada padre."""
    req_ref = db.collection("avanzadas_requerimientos").document(req_id)
    doc = req_ref.get()
    data_actual = doc.to_dict() or {}
    if not doc.exists or data_actual.get("avanzada_client_id") != client_id:
        raise HTTPException(
            status_code=404,
            detail=f"Requerimiento '{req_id}' no encontrado en avanzada '{client_id}'",
        )

    req_index = data_actual.get("req_index", 0)
    req_ref.delete()

    try:
        s3_client = get_s3_client()
        s3_storage.delete_prefix(
            f"avanzadas/{client_id}/requerimientos/{req_index}/",
            s3_client=s3_client,
            bucket=s3_storage.bucket_name(),
        )
    except Exception:
        pass

    avanzada_ref = db.collection("avanzadas").document(client_id)
    avanzada_doc = avanzada_ref.get()
    if avanzada_doc.exists:
        avanzada_data = avanzada_doc.to_dict() or {}
        nuevo_conteo = max(0, avanzada_data.get("requerimientos_count", 1) - 1)
        avanzada_ref.update({
            "requerimientos_count": nuevo_conteo,
            "updated_at": now_colombia().isoformat(),
        })

    _invalidar_cache_estadisticas()
    _invalidar_cache_geo()

    return Response(status_code=204)


# ==================== DETALLE DE AVANZADA ====================

@router.get(
    "/{client_id}",
    summary="🔵 GET | Detalle de Avanzada Diagnóstica",
    response_model=AvanzadaOut,
)
async def obtener_avanzada(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna el detalle completo de una avanzada, incluyendo todos sus
    requerimientos.
    """
    try:
        doc = db.collection("avanzadas").document(client_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail=f"Avanzada '{client_id}' no encontrada")
        return _avanzada_existente_a_out(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo avanzada: {str(e)}")
