"""
Índice espacial en memoria para reverse geocoding sobre los basemaps de Cali.

Carga al importar:
- Polígonos de barrios/veredas (point-in-polygon) — reutiliza el loader de
  ``artefacto_360_routes`` para no duplicar memoria.
- Polígonos de comunas/corregimientos (point-in-polygon).
- LineStrings de ejes viales (nearest street) con ``shapely.strtree.STRtree``.
- Points de cruces de ejes viales (nearest intersection) con ``STRtree``,
  deduplicados por par no ordenado de calles.

Las distancias se calculan en metros con haversine puro (sin pyproj).
El ranking interno usa distancia euclídea en grados escalada por cos(lat),
que es monotónica equivalente para puntos cercanos.
"""
from __future__ import annotations

import json
import math
import os
from typing import Optional

from shapely.geometry import LineString, Point, shape
from shapely.strtree import STRtree

# Reutilizar polígonos ya cargados por artefacto_360_routes para no duplicar memoria
from app.routes.artefacto_360_routes import (
    _BARRIOS_POLYGONS,
    _COMUNAS_POLYGONS,
    _CALI_BBOX,
    _dentro_de_cali,
)

_BASEMAPS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "basemaps",
)


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distancia geodésica en metros entre dos puntos (WGS84)."""
    R = 6371008.8  # radio medio de la Tierra
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _load_lines(filepath: str) -> tuple[list[LineString], list[dict]]:
    geoms: list[LineString] = []
    props: list[dict] = []
    full = os.path.join(_BASEMAPS_DIR, filepath)
    try:
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            try:
                g = shape(feat["geometry"])
                if g.is_empty:
                    continue
                geoms.append(g)
                props.append(feat.get("properties", {}) or {})
            except Exception:
                continue
        print(f"✅ Basemap '{filepath}' cargado: {len(geoms)} líneas")
    except Exception as e:
        print(f"⚠️ Error cargando basemap '{filepath}': {e}")
    return geoms, props


def _load_intersections(filepath: str) -> tuple[list[Point], list[str]]:
    """Carga cruces y los deduplica por par de calles (frozenset)."""
    geoms: list[Point] = []
    names: list[str] = []
    seen: set[frozenset[str]] = set()
    full = os.path.join(_BASEMAPS_DIR, filepath)
    try:
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            try:
                g = shape(feat["geometry"])
                if g.is_empty or g.geom_type != "Point":
                    continue
                name = (feat.get("properties", {}) or {}).get("cruce2") or ""
                # Dedupe: "CL 72A con CL 72" == "CL 72 con CL 72A"
                parts = [p.strip() for p in name.split(" con ")]
                key = frozenset(parts) if len(parts) == 2 else frozenset([name])
                if key in seen:
                    continue
                seen.add(key)
                geoms.append(g)
                names.append(name)
            except Exception:
                continue
        print(f"✅ Basemap '{filepath}' cargado: {len(geoms)} cruces (dedup)")
    except Exception as e:
        print(f"⚠️ Error cargando basemap '{filepath}': {e}")
    return geoms, names


# ==================== CARGA AL IMPORT ====================
_STREET_GEOMS, _STREET_PROPS = _load_lines("pdt_nmc_nomenclatura_vial.geojson")
_CRUCE_GEOMS, _CRUCE_NAMES = _load_intersections("cruces_ejes_viales.geojson")

# STRtree para nearest queries O(log n)
_STREET_TREE: Optional[STRtree] = STRtree(_STREET_GEOMS) if _STREET_GEOMS else None
_CRUCE_TREE: Optional[STRtree] = STRtree(_CRUCE_GEOMS) if _CRUCE_GEOMS else None


def _format_via(props: dict) -> str:
    """Formatea una vía: 'Carrera 9 NORTE' (preferencia por nvtipovia + nvnumvia)."""
    tipo = (props.get("nvtipovia") or "").strip()
    num = (props.get("nvnumvia") or "").strip()
    if tipo and num:
        return f"{tipo} {num}"
    # Fallback al nombre catastral abreviado
    return (props.get("nvnmcvial") or "").strip()


def barrio_de(lon: float, lat: float) -> Optional[str]:
    pt = Point(lon, lat)
    for polygon, name in _BARRIOS_POLYGONS:
        if polygon.contains(pt):
            return name
    return None


def comuna_de(lon: float, lat: float) -> Optional[str]:
    pt = Point(lon, lat)
    for polygon, name in _COMUNAS_POLYGONS:
        if polygon.contains(pt):
            return name
    return None


def via_mas_cercana(lon: float, lat: float, max_m: float = 80.0) -> Optional[dict]:
    """Devuelve {'tipo','numero','nombre','distancia_m'} o None si no hay dentro de max_m."""
    if _STREET_TREE is None:
        return None
    pt = Point(lon, lat)
    idx = _STREET_TREE.nearest(pt)
    geom = _STREET_GEOMS[idx]
    props = _STREET_PROPS[idx]
    # Punto más cercano sobre la LineString
    nearest_pt = geom.interpolate(geom.project(pt))
    dist_m = _haversine_m(lon, lat, nearest_pt.x, nearest_pt.y)
    if dist_m > max_m:
        return None
    return {
        "tipo": (props.get("nvtipovia") or "").strip() or None,
        "numero": (props.get("nvnumvia") or "").strip() or None,
        "nombre": _format_via(props) or None,
        "nombre_catastral": (props.get("nvnmcvial") or "").strip() or None,
        "clase": (props.get("nvclasevia") or "").strip() or None,
        "distancia_m": round(dist_m, 2),
    }


def cruce_mas_cercano(lon: float, lat: float, max_m: float = 150.0) -> Optional[dict]:
    """Devuelve {'nombre','distancia_m'} del cruce vial más cercano o None."""
    if _CRUCE_TREE is None:
        return None
    pt = Point(lon, lat)
    idx = _CRUCE_TREE.nearest(pt)
    g = _CRUCE_GEOMS[idx]
    dist_m = _haversine_m(lon, lat, g.x, g.y)
    if dist_m > max_m:
        return None
    return {"nombre": _CRUCE_NAMES[idx], "distancia_m": round(dist_m, 2)}


# Re-export útil
__all__ = [
    "barrio_de",
    "comuna_de",
    "via_mas_cercana",
    "cruce_mas_cercano",
    "_CALI_BBOX",
    "_dentro_de_cali",
    "_haversine_m",
]
