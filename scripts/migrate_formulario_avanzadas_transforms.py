"""
Transformaciones puras: fila de Excel (dict plano) -> documento Firestore
(dict plano), para la migración one-off de ``Formulario Avanzadas.xlsx``.

Ninguna función de este módulo importa Firestore, pandas.DataFrame, ni hace
I/O: reciben listas de dicts (como los que produce
``DataFrame.to_dict('records')``) y retornan ``(docs, warnings)`` donde
``docs`` es un dict ``{doc_id: documento}`` y ``warnings`` es una lista de
strings describiendo filas omitidas o datos ambiguos. Esto las hace
100% testeables sin mocks de infraestructura.

Convención de fecha/hora (debe coincidir con ``app/routes/avanzadas_routes.py``):
- Campos ``fecha`` (y variantes ``fecha_*``): string ``"YYYY-MM-DD"``.
- Campos ``created_at``/``updated_at`` de las colecciones ya consumidas por
  la API (``avanzadas``, ``avanzadas_requerimientos``): string ISO-8601 con
  offset fijo de Colombia (UTC-5), igual que ``now_colombia().isoformat()``.
- Campos ``creado``/``actualizado`` de las colecciones NUEVAS (sin contrato
  de API todavía): se dejan como ``datetime`` (localizados a UTC) en vez de
  string, porque no hay ningún modelo Pydantic que los constriña aún.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

_COL_TZ = timezone(timedelta(hours=-5))


# ──────────────────────────────────────────────────────────────────────────
# Helpers genéricos de limpieza de celdas
# ──────────────────────────────────────────────────────────────────────────

def _is_missing(value) -> bool:
    """True para None, NaN (float o pandas) y strings vacíos/solo espacios."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return False


def clean_optional_str(value) -> Optional[str]:
    """Normaliza una celda de texto: NaN/None/'' -> None, resto -> strip()."""
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def split_names(raw) -> List[str]:
    """Divide una celda 'Nombre A, Nombre B' en una lista de nombres."""
    if _is_missing(raw):
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def normalize_celular(raw) -> str:
    """Normaliza un celular que puede venir como float (3175783808.0),
    int, string o vacío, a un string de solo dígitos (sin '.0' final).
    """
    if _is_missing(raw):
        return ""
    if isinstance(raw, float):
        return str(int(raw))
    return str(raw).strip()


def split_urls(raw) -> List[str]:
    """Divide una celda de URLs separadas por ' | ' en una lista."""
    if _is_missing(raw):
        return []
    return [p.strip() for p in str(raw).split("|") if p.strip()]


def format_fecha_date(value) -> Optional[str]:
    """Convierte una fecha (datetime/date/Timestamp/string) a 'YYYY-MM-DD'."""
    if _is_missing(value):
        return None
    if isinstance(value, str):
        return value.strip() or None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def colombia_iso_from_fecha(value) -> Optional[str]:
    """Adjunta el offset fijo de Colombia (UTC-5) a una fecha/hora y
    retorna su representación ISO-8601, igual que ``now_colombia().isoformat()``.
    """
    if _is_missing(value):
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    localized = value.replace(tzinfo=_COL_TZ)
    return localized.isoformat()


def _to_utc_datetime(value) -> Optional[datetime]:
    """Convierte una fecha/hora naive (Excel) a datetime tz-aware en UTC.

    Asunción documentada: las marcas 'Creado'/'Actualizado' del Excel no
    tienen contrato de API todavía, así que se localizan a UTC en vez de
    dejarlas naive (evita ambigüedad/​warnings del SDK de Firestore).
    """
    if _is_missing(value):
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _slugify(text: str) -> str:
    text = text.strip().lower()
    # Quita acentos comunes en español sin depender de unicodedata/normalize
    # para mantener la función simple y determinística.
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u",
    }
    for accented, plain in replacements.items():
        text = text.replace(accented, plain)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def slugify_categoria_key(entidad: str, categoria: str) -> str:
    """Doc ID determinístico para ``categorias_personalizadas``."""
    return f"{_slugify(entidad)}__{_slugify(categoria)}"


def parse_evaluaciones(raw) -> List[dict]:
    """Parsea la celda 'Evaluaciones' (JSON string) a una lista de dicts.
    Si el JSON es inválido o la celda está vacía, retorna [] (no lanza).
    """
    if _is_missing(raw):
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _int_or_default(value, default: int = 0) -> int:
    if _is_missing(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────────────────────────────────
# Asistencia -> agrupado por avanzada (ClientId)
# ──────────────────────────────────────────────────────────────────────────

def build_asistentes_by_avanzada(
    rows: List[dict],
) -> Tuple[Dict[str, List[dict]], List[str]]:
    grouped: Dict[str, List[dict]] = {}
    warnings: List[str] = []
    for i, row in enumerate(rows):
        client_id = clean_optional_str(row.get("ClientId"))
        if not client_id:
            warnings.append(f"Asistencia fila {i}: sin ClientId, se omite")
            continue
        asistente = {
            "nombre": clean_optional_str(row.get("Nombre Participante")) or "",
            "organismo": clean_optional_str(row.get("Organismo")) or "",
            "celular": normalize_celular(row.get("Celular")),
            "correo": clean_optional_str(row.get("Correo")) or "",
        }
        grouped.setdefault(client_id, []).append(asistente)
    return grouped, warnings


# ──────────────────────────────────────────────────────────────────────────
# Requerimientos
# ──────────────────────────────────────────────────────────────────────────

def build_requerimientos(rows: List[dict]) -> Tuple[Dict[str, dict], List[str]]:
    docs: Dict[str, dict] = {}
    warnings: List[str] = []
    next_index: Dict[str, int] = {}

    for i, row in enumerate(rows):
        client_id = clean_optional_str(row.get("ClientId"))
        if not client_id:
            warnings.append(f"Requerimientos fila {i}: sin ClientId, se omite")
            continue

        idx = next_index.get(client_id, 0)
        next_index[client_id] = idx + 1

        doc = {
            "avanzada_client_id": client_id,
            "req_index": idx,
            "entidad": clean_optional_str(row.get("Entidad")) or "",
            "categoria": clean_optional_str(row.get("Categoría")),
            "categoria_personalizada": None,
            "requerimiento": clean_optional_str(row.get("Requerimiento")) or "",
            "ubicacion": clean_optional_str(row.get("Ubicación")) or "",
            "coordenadas": clean_optional_str(row.get("Coordenadas")),
            "fotos_urls": split_urls(row.get("Evidencia fotográfica")),
            "fecha": format_fecha_date(row.get("Fecha")),
            "nombre_avanzada": clean_optional_str(row.get("Nombre Avanzada")) or "",
            "estrategia": clean_optional_str(row.get("Estrategia")) or "",
            "created_at": colombia_iso_from_fecha(row.get("Fecha")),
        }
        doc_id = f"{client_id}_{idx}"
        docs[doc_id] = doc

    return docs, warnings


def count_requerimientos_by_avanzada(req_docs: Dict[str, dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for doc in req_docs.values():
        client_id = doc["avanzada_client_id"]
        counts[client_id] = counts.get(client_id, 0) + 1
    return counts


# ──────────────────────────────────────────────────────────────────────────
# Avanzadas
# ──────────────────────────────────────────────────────────────────────────

def build_avanzadas(
    rows: List[dict],
    asistentes_by_client: Dict[str, List[dict]],
    req_counts: Dict[str, int],
) -> Tuple[Dict[str, dict], List[str]]:
    docs: Dict[str, dict] = {}
    warnings: List[str] = []

    for i, row in enumerate(rows):
        client_id = clean_optional_str(row.get("ClientId"))
        if not client_id:
            warnings.append(f"Avanzadas fila {i}: sin ClientId, se omite")
            continue

        fecha_iso = colombia_iso_from_fecha(row.get("Fecha"))
        doc = {
            "client_id": client_id,
            "numero": _int_or_default(row.get("No")),
            "fecha": format_fecha_date(row.get("Fecha")),
            "nombre_avanzada": clean_optional_str(row.get("Nombre Avanzada")) or "",
            "estrategia": clean_optional_str(row.get("Estrategia")) or "",
            "sector": clean_optional_str(row.get("Sector")),
            "comuna": clean_optional_str(row.get("Comuna/Corregimiento")) or "",
            "barrio": clean_optional_str(row.get("Barrio/Vereda")) or "",
            "direccion": clean_optional_str(row.get("Dirección")) or "",
            "coordenadas": clean_optional_str(row.get("Coordenadas")) or "",
            "encargados": split_names(row.get("Encargados")),
            "asistentes": asistentes_by_client.get(client_id, []),
            "foto_equipo_url": None,
            "informe_url": clean_optional_str(row.get("Unnamed: 11")),
            "requerimientos_count": req_counts.get(client_id, 0),
            "created_by": "migracion-excel",
            "created_at": fecha_iso,
            "updated_at": fecha_iso,
        }
        docs[client_id] = doc

    return docs, warnings


# ──────────────────────────────────────────────────────────────────────────
# CategoriasPersonalizadas
# ──────────────────────────────────────────────────────────────────────────

def build_categorias_personalizadas(rows: List[dict]) -> Tuple[Dict[str, dict], List[str]]:
    docs: Dict[str, dict] = {}
    warnings: List[str] = []

    for i, row in enumerate(rows):
        entidad = clean_optional_str(row.get("Entidad"))
        categoria = clean_optional_str(row.get("Categoria"))
        if not entidad or not categoria:
            warnings.append(f"CategoriasPersonalizadas fila {i}: sin Entidad/Categoria, se omite")
            continue

        doc_id = slugify_categoria_key(entidad, categoria)
        docs[doc_id] = {
            "entidad": entidad,
            "categoria": categoria,
            "fecha": format_fecha_date(row.get("Fecha")),
        }

    return docs, warnings


# ──────────────────────────────────────────────────────────────────────────
# JornadasIntegrales / Compromisos / SeguimientosHistorial / EncuestasExperiencia
# ──────────────────────────────────────────────────────────────────────────

def build_jornadas(rows: List[dict]) -> Tuple[Dict[str, dict], List[str]]:
    docs: Dict[str, dict] = {}
    warnings: List[str] = []

    for i, row in enumerate(rows):
        client_id = clean_optional_str(row.get("ClientId"))
        if not client_id:
            warnings.append(f"JornadasIntegrales fila {i}: sin ClientId, se omite")
            continue

        docs[client_id] = {
            "numero": _int_or_default(row.get("No")),
            "fecha": format_fecha_date(row.get("Fecha")),
            "nombre_jornada": clean_optional_str(row.get("Nombre Jornada")) or "",
            "sector_punto_reconocimiento": clean_optional_str(row.get("Sector/Punto Reconocimiento")),
            "punto_encuentro": clean_optional_str(row.get("Punto Encuentro")),
            "direccion_punto_encuentro": clean_optional_str(row.get("Direccion Punto Encuentro")),
            "coordenadas_encuentro": clean_optional_str(row.get("Coordenadas Encuentro")),
            "comuna": clean_optional_str(row.get("Comuna/Corregimiento")),
            "barrio": clean_optional_str(row.get("Barrio/Vereda")),
            "direcciones_recuperadas": clean_optional_str(row.get("Direcciones Recuperadas")),
            "estado": clean_optional_str(row.get("Estado")),
            "asistencia_aproximada": _int_or_default(row.get("Asistencia Aproximada")),
            "observaciones_generales": clean_optional_str(row.get("Observaciones Generales")),
            "peticiones_comunidad": clean_optional_str(row.get("Peticiones Comunidad")),
            "url_croquis": clean_optional_str(row.get("URL Croquis")),
            "url_informe_pdf": clean_optional_str(row.get("URL Informe PDF")),
            "creado": _to_utc_datetime(row.get("Creado")),
            "actualizado": _to_utc_datetime(row.get("Actualizado")),
        }

    return docs, warnings


def build_compromisos(rows: List[dict]) -> Tuple[Dict[str, dict], List[str]]:
    docs: Dict[str, dict] = {}
    warnings: List[str] = []

    for i, row in enumerate(rows):
        client_id = clean_optional_str(row.get("ClientId"))
        if not client_id:
            warnings.append(f"Compromisos fila {i}: sin ClientId, se omite")
            continue

        docs[client_id] = {
            "numero": _int_or_default(row.get("No")),
            "fecha": format_fecha_date(row.get("Fecha")),
            "jornada_client_id": clean_optional_str(row.get("JornadaClientId")),
            "nombre_jornada": clean_optional_str(row.get("Nombre Jornada")),
            "organismo": clean_optional_str(row.get("Organismo")),
            "oferta_servicio": clean_optional_str(row.get("Oferta/Servicio")),
            "responsable_organismo": clean_optional_str(row.get("Responsable Organismo")),
            "celular_responsable": normalize_celular(row.get("Celular Responsable")),
            "tipo": clean_optional_str(row.get("Tipo")),
            "compromiso": clean_optional_str(row.get("Compromiso")),
            "unidad_medida": clean_optional_str(row.get("Unidad Medida")),
            "meta_cuantitativa": _int_or_default(row.get("Meta Cuantitativa")),
            "estado_seguimiento": clean_optional_str(row.get("Estado Seguimiento")),
            "estado_verificacion_campo": clean_optional_str(row.get("Estado Verificacion Campo")),
            "fecha_verificacion": format_fecha_date(row.get("Fecha Verificacion")),
            "responsable_verificacion": clean_optional_str(row.get("Responsable Verificacion")),
            "representante_organismo": clean_optional_str(row.get("Representante Organismo")),
            "resultado_obtenido": _int_or_default(row.get("Resultado Obtenido")),
            "comentario_verificacion": clean_optional_str(row.get("Comentario Verificacion")),
            "fotos_verificacion": split_urls(row.get("Fotos Verificacion")),
            "creado": _to_utc_datetime(row.get("Creado")),
            "actualizado": _to_utc_datetime(row.get("Actualizado")),
        }

    return docs, warnings


def build_seguimientos(
    rows: List[dict], compromiso_to_jornada: Dict[str, str]
) -> Tuple[Dict[str, dict], List[str]]:
    docs: Dict[str, dict] = {}
    warnings: List[str] = []

    for i, row in enumerate(rows):
        client_id = clean_optional_str(row.get("ClientId"))
        if not client_id:
            warnings.append(f"SeguimientosHistorial fila {i}: sin ClientId, se omite")
            continue

        compromiso_id = clean_optional_str(row.get("CompromisoClientId"))
        jornada_id = compromiso_to_jornada.get(compromiso_id) if compromiso_id else None
        if compromiso_id and jornada_id is None:
            warnings.append(
                f"SeguimientosHistorial fila {i}: CompromisoClientId "
                f"'{compromiso_id}' no encontrado en Compromisos, "
                f"jornada_client_id queda en None"
            )

        docs[client_id] = {
            "numero": _int_or_default(row.get("No")),
            "fecha": format_fecha_date(row.get("Fecha")),
            "compromiso_client_id": compromiso_id,
            "jornada_client_id": jornada_id,
            "fecha_seguimiento": format_fecha_date(row.get("Fecha Seguimiento")),
            "estado": clean_optional_str(row.get("Estado")),
            "responsable_seguimiento": clean_optional_str(row.get("Responsable Seguimiento")),
            "comentario_seguimiento": clean_optional_str(row.get("Comentario Seguimiento")),
            "creado": _to_utc_datetime(row.get("Creado")),
        }

    return docs, warnings


def build_encuestas(rows: List[dict]) -> Tuple[Dict[str, dict], List[str]]:
    docs: Dict[str, dict] = {}
    warnings: List[str] = []

    for i, row in enumerate(rows):
        client_id = clean_optional_str(row.get("ClientId"))
        if not client_id:
            warnings.append(f"EncuestasExperiencia fila {i}: sin ClientId, se omite")
            continue

        docs[client_id] = {
            "numero": _int_or_default(row.get("No")),
            "fecha": format_fecha_date(row.get("Fecha")),
            "jornada_client_id": clean_optional_str(row.get("JornadaClientId")),
            "nombre_participante": clean_optional_str(row.get("Nombre Participante")),
            "comuna": clean_optional_str(row.get("Comuna")),
            "barrio": clean_optional_str(row.get("Barrio")),
            "evaluaciones": parse_evaluaciones(row.get("Evaluaciones")),
            "comentario_final": clean_optional_str(row.get("Comentario Final")),
            "creado": _to_utc_datetime(row.get("Creado")),
        }

    return docs, warnings
