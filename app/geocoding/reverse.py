"""
Servicio de reverse geocoding: (lat, lon) → dirección estructurada para Cali.

Combina basemaps catastrales locales (verdad para Cali) con Nominatim /reverse
(enriquecimiento opcional, fallback silencioso). Cache LRU por coordenada
cuantizada a 5 decimales (~1 m) para respetar la política de OSM (1 req/s).
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Optional

import httpx

from app.geocoding import spatial_index as si

# Throttle global para Nominatim (1 req/s)
_NOMINATIM_LOCK = asyncio.Lock()
_NOMINATIM_LAST_TS: list[float] = [0.0]  # mutable holder

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "catatrack-api/1.0 (contacto: catatrack@cali.gov.co)"


async def _nominatim_reverse(lat: float, lon: float, timeout: float = 5.0) -> Optional[dict]:
    """Llama Nominatim reverse con throttling 1 req/s. Devuelve None ante cualquier fallo."""
    import time

    async with _NOMINATIM_LOCK:
        delta = time.time() - _NOMINATIM_LAST_TS[0]
        if delta < 1.0:
            await asyncio.sleep(1.0 - delta)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    NOMINATIM_REVERSE_URL,
                    params={
                        "lat": f"{lat}",
                        "lon": f"{lon}",
                        "format": "jsonv2",
                        "zoom": 18,
                        "addressdetails": 1,
                        "accept-language": "es",
                    },
                    headers={"User-Agent": USER_AGENT},
                )
                _NOMINATIM_LAST_TS[0] = time.time()
                if resp.status_code != 200:
                    return None
                data = resp.json()
                addr = data.get("address", {}) or {}
                return {
                    "display_name": data.get("display_name"),
                    "road": addr.get("road"),
                    "suburb": addr.get("suburb") or addr.get("neighbourhood"),
                    "city_district": addr.get("city_district"),
                    "city": addr.get("city") or addr.get("town") or addr.get("village"),
                    "postcode": addr.get("postcode"),
                }
        except Exception:
            return None


def _componer_direccion(
    via: Optional[dict],
    cruce: Optional[dict],
    barrio: Optional[str],
    comuna: Optional[str],
    nominatim: Optional[dict],
) -> str:
    """Compone una dirección legible priorizando basemaps locales."""
    partes: list[str] = []
    if via and via.get("nombre"):
        partes.append(via["nombre"])
    if cruce and cruce.get("nombre"):
        partes.append(f"cerca de {cruce['nombre']}")
    elif not via and nominatim and nominatim.get("road"):
        partes.append(nominatim["road"])

    contexto: list[str] = []
    if barrio:
        b = barrio.strip()
        contexto.append(b if b.lower().startswith("barrio") else f"Barrio {b}")
    if comuna:
        contexto.append(comuna)
    contexto.append("Cali")

    if partes:
        return f"{' '.join(partes)}, {', '.join(contexto)}"
    return ", ".join(contexto)


# Cache LRU por coordenada cuantizada (~1 m). Guarda solo la parte local (rápida).
@lru_cache(maxsize=2048)
def _lookup_local_cached(lat_q: float, lon_q: float) -> dict:
    barrio = si.barrio_de(lon_q, lat_q)
    comuna = si.comuna_de(lon_q, lat_q)
    via = si.via_mas_cercana(lon_q, lat_q)
    cruce = si.cruce_mas_cercano(lon_q, lat_q)
    return {"barrio": barrio, "comuna": comuna, "via": via, "cruce": cruce}


async def reverse_geocode(
    lat: float,
    lon: float,
    *,
    usar_nominatim: bool = True,
) -> dict:
    """Punto de entrada principal del servicio de reverse geocoding."""
    # Validar rango global
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError("Coordenadas fuera de rango global")

    dentro_cali = si._dentro_de_cali(lon, lat)

    # Lookup local (con cache cuantizada a 5 decimales ≈ 1 m)
    lat_q = round(lat, 5)
    lon_q = round(lon, 5)
    local = _lookup_local_cached(lat_q, lon_q)

    # Enriquecimiento Nominatim (opcional, no bloqueante si falla)
    nominatim = None
    fuentes = ["basemaps_cali"]
    if usar_nominatim:
        nominatim = await _nominatim_reverse(lat, lon)
        if nominatim:
            fuentes.append("nominatim")

    direccion_legible = _componer_direccion(
        local["via"], local["cruce"], local["barrio"], local["comuna"], nominatim
    )

    return {
        "success": True,
        "coordenada": {"lat": lat, "lon": lon},
        "dentro_de_cali": dentro_cali,
        "barrio_vereda": local["barrio"],
        "comuna_corregimiento": local["comuna"],
        "via": local["via"],
        "cruce_mas_cercano": local["cruce"],
        "direccion_legible": direccion_legible,
        "direccion_osm": (nominatim or {}).get("display_name"),
        "osm": nominatim,
        "fuentes": fuentes,
    }
