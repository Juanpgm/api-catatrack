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


# Mapeo nombre completo → abreviatura catastral usada en los nombres de cruce
_TIPO_VIA_ABREV: dict[str, str] = {
    "carrera": "KR",
    "calle": "CL",
    "diagonal": "DG",
    "transversal": "TV",
    "autopista": "AK",
    "avenida": "AV",
    "circular": "CR",
    "via": "VIA",
}


def _via_abrev(tipo: str, numero: str) -> str:
    """Construye la forma abreviada catastral. 'Carrera', '1' → 'KR 1'."""
    abrev = _TIPO_VIA_ABREV.get((tipo or "").lower().strip(), "")
    num = (numero or "").strip()
    if abrev and num:
        return f"{abrev} {num}"
    return ""


def _cross_num_from_cruce(cruce_nombre: str, via_abrev: str) -> Optional[str]:
    """
    De 'KR 1 con CL 8' y via_abrev='KR 1' extrae '8' (número de la transversal).
    Devuelve None si no puede resolverlo o el cruce no pasa por la via.
    """
    if not cruce_nombre or not via_abrev:
        return None
    parts = [p.strip() for p in cruce_nombre.split(" con ")]
    if len(parts) != 2:
        return None
    via_norm = via_abrev.upper()
    for part in parts:
        if part.upper() == via_norm:
            continue  # esta es la via principal, buscar la otra
        # Extraer número de la transversal: ['CL', '8'] → '8'; ['KR', '8A'] → '8A'
        tokens = part.split()
        if len(tokens) >= 2:
            return " ".join(tokens[1:])
    return None


def _componer_direccion(
    via: Optional[dict],
    cruce: Optional[dict],
    barrio: Optional[str],
    comuna: Optional[str],
    nominatim: Optional[dict],
) -> str:
    """
    Compone una dirección en formato colombiano estándar:
    'Carrera 1 #8-37, barrio La Merced, COMUNA 03, Cali, Valle del Cauca, Colombia'
    """
    partes: list[str] = []

    if via and via.get("nombre"):
        via_str = via["nombre"]
        abrev = _via_abrev(via.get("tipo") or "", via.get("numero") or "")

        if cruce and cruce.get("nombre"):
            cross_num = _cross_num_from_cruce(cruce["nombre"], abrev)
            dist_m = int(round(cruce.get("distancia_m") or 0))
            if cross_num and abrev:
                partes.append(f"{via_str} #{cross_num}-{dist_m}")
            else:
                # Fallback si el cruce no está en la via principal
                partes.append(f"{via_str} cerca de {cruce['nombre']}")
        else:
            partes.append(via_str)
    elif cruce and cruce.get("nombre"):
        partes.append(cruce["nombre"])
    elif nominatim and nominatim.get("road"):
        partes.append(nominatim["road"])

    contexto: list[str] = []
    if barrio:
        b = barrio.strip()
        label = b if b.lower().startswith("barrio") else f"barrio {b}"
        contexto.append(label)
    if comuna:
        contexto.append(comuna)
    contexto.extend(["Cali", "Valle del Cauca", "Colombia"])

    if partes:
        return f"{', '.join(partes)}, {', '.join(contexto)}"
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
