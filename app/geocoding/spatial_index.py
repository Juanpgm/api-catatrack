"""
Índice espacial en memoria para reverse geocoding sobre los basemaps de Cali.

Basemaps utilizados (todos en ``api-catatrack/basemaps/``):
- ``barrios_veredas.geojson`` — polígonos de barrios/veredas (point-in-polygon),
  cargado por ``artefacto_360_routes`` y reutilizado aquí.
- ``comunas_corregimientos.geojson`` — polígonos de comunas/corregimientos
  (point-in-polygon), también reutilizado de ``artefacto_360_routes``.
- ``cruces_ejes_viales.geojson`` — points de cruces (nearest + inferencia de vía),
  indexados con ``shapely.strtree.STRtree`` y deduplicados por par no ordenado
  de calles.

Las distancias se calculan en metros con haversine puro (sin pyproj).
"""
from __future__ import annotations

import json
import math
import os
from typing import Optional

from shapely.geometry import Point, shape
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
_CRUCE_GEOMS, _CRUCE_NAMES = _load_intersections("cruces_ejes_viales.geojson")

# STRtree para nearest queries O(log n)
_CRUCE_TREE: Optional[STRtree] = STRtree(_CRUCE_GEOMS) if _CRUCE_GEOMS else None


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


def _dist_a_boundary_m(polygon, lon: float, lat: float) -> float:
    """Distancia (m) del punto al borde más cercano del polígono."""
    try:
        nearest_pt = polygon.boundary.interpolate(polygon.boundary.project(Point(lon, lat)))
        return _haversine_m(lon, lat, nearest_pt.x, nearest_pt.y)
    except Exception:
        return float("inf")


def _dist_a_polygon_m(polygon, lon: float, lat: float) -> float:
    """Distancia (m) del punto al polígono (0 si está dentro)."""
    pt = Point(lon, lat)
    if polygon.contains(pt):
        return 0.0
    return _dist_a_boundary_m(polygon, lon, lat)


def barrio_de_robusto(lon: float, lat: float, margen_borde_m: float = 60.0) -> dict:
    """
    Asignación robusta de barrio por intersección geográfica + vecindad:
    - 'primario': polígono que CONTIENE el punto (verdad catastral local).
    - 'vecinos': lista de polígonos cercanos (≤ margen_borde_m * 5), ordenados por distancia.
    - 'dist_borde_m': distancia del punto al borde del polígono primario.
    Si no hay primario, busca el más cercano dentro de 200m.
    """
    pt = Point(lon, lat)
    primario: Optional[str] = None
    primario_poly = None
    for polygon, name in _BARRIOS_POLYGONS:
        if polygon.contains(pt):
            primario = name
            primario_poly = polygon
            break

    if primario_poly is not None:
        dist_borde = _dist_a_boundary_m(primario_poly, lon, lat)
        # Lista de vecinos cercanos para reconciliación con fuentes externas
        candidatos: list[tuple[float, str]] = []
        radio_busqueda = max(margen_borde_m * 5, 200.0)
        for polygon, name in _BARRIOS_POLYGONS:
            if name == primario:
                continue
            d = _dist_a_polygon_m(polygon, lon, lat)
            if d <= radio_busqueda:
                candidatos.append((d, name))
        candidatos.sort()
        vecinos = [{"nombre": n, "distancia_m": round(d, 2)} for d, n in candidatos[:5]]
        vecino_inmediato = vecinos[0]["nombre"] if (vecinos and candidatos[0][0] < margen_borde_m * 3) else None
        return {
            "primario": primario,
            "vecino": vecino_inmediato,
            "vecinos": vecinos,
            "dist_borde_m": round(dist_borde, 2),
        }

    # Sin contenedor → nearest (solo si está razonablemente cerca, < 200m)
    mejor = (float("inf"), None)
    for polygon, name in _BARRIOS_POLYGONS:
        d = _dist_a_polygon_m(polygon, lon, lat)
        if d < mejor[0]:
            mejor = (d, name)
    if mejor[0] > 200.0:
        return {"primario": None, "vecino": None, "vecinos": [], "dist_borde_m": round(mejor[0], 2)}
    return {
        "primario": mejor[1],
        "vecino": None,
        "vecinos": [{"nombre": mejor[1], "distancia_m": round(mejor[0], 2)}] if mejor[1] else [],
        "dist_borde_m": round(mejor[0], 2),
    }


def comuna_de_robusto(lon: float, lat: float, margen_borde_m: float = 80.0) -> dict:
    """Versión robusta para comunas: mismo patrón que barrio_de_robusto."""
    pt = Point(lon, lat)
    primario: Optional[str] = None
    primario_poly = None
    for polygon, name in _COMUNAS_POLYGONS:
        if polygon.contains(pt):
            primario = name
            primario_poly = polygon
            break

    if primario_poly is not None:
        dist_borde = _dist_a_boundary_m(primario_poly, lon, lat)
        candidatos: list[tuple[float, str]] = []
        radio_busqueda = max(margen_borde_m * 5, 300.0)
        for polygon, name in _COMUNAS_POLYGONS:
            if name == primario:
                continue
            d = _dist_a_polygon_m(polygon, lon, lat)
            if d <= radio_busqueda:
                candidatos.append((d, name))
        candidatos.sort()
        vecinos = [{"nombre": n, "distancia_m": round(d, 2)} for d, n in candidatos[:5]]
        vecino_inmediato = vecinos[0]["nombre"] if (vecinos and candidatos[0][0] < margen_borde_m * 3) else None
        return {
            "primario": primario,
            "vecino": vecino_inmediato,
            "vecinos": vecinos,
            "dist_borde_m": round(dist_borde, 2),
        }

    mejor = (float("inf"), None)
    for polygon, name in _COMUNAS_POLYGONS:
        d = _dist_a_polygon_m(polygon, lon, lat)
        if d < mejor[0]:
            mejor = (d, name)
    if mejor[0] > 500.0:
        return {"primario": None, "vecino": None, "vecinos": [], "dist_borde_m": round(mejor[0], 2)}
    return {
        "primario": mejor[1],
        "vecino": None,
        "vecinos": [{"nombre": mejor[1], "distancia_m": round(mejor[0], 2)}] if mejor[1] else [],
        "dist_borde_m": round(mejor[0], 2),
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


# ==================== INFERENCIA DE VÍA A PARTIR DE CRUCES ====================
# Como única fuente vial disponible están los cruces (`cruces_ejes_viales.geojson`),
# se infiere la vía dominante a partir de los nombres de los cruces cercanos.

_ABREV_TO_TIPO: dict[str, str] = {
    "KR": "Carrera",
    "CL": "Calle",
    "DG": "Diagonal",
    "TV": "Transversal",
    "AK": "Autopista",
    "AV": "Avenida",
    "CR": "Circular",
    "VIA": "Vía",
}


def _parse_via_token(token: str) -> Optional[tuple[str, str, str]]:
    """'CL 72A NORTE' → ('CL', '72A NORTE', 'Calle 72A NORTE')."""
    parts = token.strip().split(None, 1)
    if len(parts) != 2:
        return None
    abrev = parts[0].upper()
    tipo = _ABREV_TO_TIPO.get(abrev)
    if not tipo:
        return None
    num = parts[1].strip()
    if not num:
        return None
    return abrev, num, f"{tipo} {num}"


def _cruces_en_radio(lon: float, lat: float, max_m: float) -> list[tuple[int, float]]:
    """Devuelve [(idx, distancia_m), ...] de cruces dentro de max_m, ordenados."""
    if _CRUCE_TREE is None:
        return []
    pt = Point(lon, lat)
    # Conversión aproximada a grados (overestima para coincidir con todos)
    buffer_deg = (max_m / 111000.0) * 1.4
    try:
        idxs = list(_CRUCE_TREE.query(pt.buffer(buffer_deg)))
    except Exception:
        return []
    out: list[tuple[int, float]] = []
    for i in idxs:
        g = _CRUCE_GEOMS[int(i)]
        d = _haversine_m(lon, lat, g.x, g.y)
        if d <= max_m:
            out.append((int(i), d))
    out.sort(key=lambda x: x[1])
    return out


def via_inferida_de_cruces(
    lon: float,
    lat: float,
    k: int = 12,
    max_m: float = 250.0,
) -> Optional[dict]:
    """
    Infiere la vía dominante a partir de los nombres de cruces cercanos.

    Cada cruce 'CL 72A con CL 72' aporta dos vías candidatas. Se rankea por:
    1. Frecuencia (vías que aparecen en más cruces son las vías principales).
    2. Menor distancia mínima al punto consultado.

    Devuelve None si no hay cruces utilizables dentro de ``max_m`` o si los
    nombres no son parseables.
    """
    vecinos = _cruces_en_radio(lon, lat, max_m)
    if not vecinos:
        return None
    vecinos = vecinos[: max(k, 4)]

    # token → lista de distancias a los cruces que lo mencionan
    cand: dict[str, list[float]] = {}
    for idx, d in vecinos:
        for part in _CRUCE_NAMES[idx].split(" con "):
            t = part.strip()
            if not t or _parse_via_token(t) is None:
                continue
            cand.setdefault(t, []).append(d)
    if not cand:
        return None

    def score(item: tuple[str, list[float]]) -> tuple[int, float]:
        _, dists = item
        return (-len(dists), min(dists))

    best_token, best_dists = min(cand.items(), key=score)
    parsed = _parse_via_token(best_token)
    if parsed is None:
        return None
    abrev, num, nombre = parsed
    return {
        "tipo": _ABREV_TO_TIPO.get(abrev),
        "numero": num,
        "nombre": nombre,
        "nombre_catastral": best_token,
        "clase": None,
        "distancia_m": round(min(best_dists), 2),
        "soporte_cruces": len(best_dists),
        "inferida": True,
    }


# Re-export útil
__all__ = [
    "barrio_de",
    "comuna_de",
    "barrio_de_robusto",
    "comuna_de_robusto",
    "via_inferida_de_cruces",
    "cruce_mas_cercano",
    "_CALI_BBOX",
    "_dentro_de_cali",
    "_haversine_m",
]
