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
    barrio_info = si.barrio_de_robusto(lon_q, lat_q)
    comuna_info = si.comuna_de_robusto(lon_q, lat_q)
    # La única fuente vial disponible son los cruces; inferimos la vía dominante.
    via = si.via_inferida_de_cruces(lon_q, lat_q)
    cruce = si.cruce_mas_cercano(lon_q, lat_q)
    return {
        "barrio": barrio_info["primario"],
        "barrio_vecino": barrio_info["vecino"],
        "barrio_vecinos": barrio_info.get("vecinos", []),
        "barrio_dist_borde_m": barrio_info["dist_borde_m"],
        "comuna": comuna_info["primario"],
        "comuna_vecino": comuna_info["vecino"],
        "comuna_vecinos": comuna_info.get("vecinos", []),
        "comuna_dist_borde_m": comuna_info["dist_borde_m"],
        "via": via,
        "via_inferida": via is not None,
        "cruce": cruce,
    }


# Normalización Nominatim → formato catastral local
def _normalizar_comuna_osm(osm_name: Optional[str]) -> Optional[str]:
    """'Comuna 3' → 'COMUNA 03'; 'Comuna 15' → 'COMUNA 15'; pasa corregimientos intactos."""
    if not osm_name:
        return None
    s = osm_name.strip()
    low = s.lower()
    if low.startswith("comuna "):
        num = s.split(" ", 1)[1].strip()
        if num.isdigit():
            return f"COMUNA {int(num):02d}"
        return f"COMUNA {num.upper()}"
    return s


def _norm(s: Optional[str]) -> str:
    """Normaliza para comparar nombres (case + trim)."""
    return (s or "").strip().lower()


def _reconciliar_barrio(local: dict, osm: Optional[dict]) -> tuple[Optional[str], str]:
    """
    Asignación final de barrio combinando intersección geográfica local + OSM.
    Estricto: SOLO acepta el nombre de OSM si geográficamente coincide con
    alguno de los polígonos candidatos cercanos (primario o vecinos).
    Esto evita que OSM imponga nombres arbitrarios sin respaldo geográfico.
    """
    primario = local.get("barrio")
    vecinos: list[dict] = local.get("barrio_vecinos") or []
    dist_borde = local.get("barrio_dist_borde_m") or 0
    osm_barrio = (osm or {}).get("suburb")

    if not osm_barrio:
        return primario, "local"

    osm_n = _norm(osm_barrio)

    # Caso 1: OSM coincide con el polígono primario → ambos están de acuerdo
    if osm_n == _norm(primario):
        return primario, "local+osm"

    # Caso 2: OSM coincide con algún vecino geográficamente cercano → corregir borde
    for v in vecinos:
        if osm_n == _norm(v["nombre"]):
            # Solo aceptar la corrección si el punto está cerca del borde del primario
            # Y el vecino está geográficamente al alcance (< 100m)
            if dist_borde < 80.0 and v["distancia_m"] < 100.0:
                return v["nombre"], "osm_corrige_borde"
            break

    # Caso 3: OSM dice un nombre que NO está entre los polígonos cercanos →
    # NO confiamos en OSM (puede ser un nombre alternativo, un sector, una
    # división informal que no existe en el catastro). Mantenemos local.
    return primario, "local"


def _reconciliar_comuna(local: dict, osm: Optional[dict]) -> tuple[Optional[str], str]:
    """Misma lógica estricta para comunas."""
    primario = local.get("comuna")
    vecinos: list[dict] = local.get("comuna_vecinos") or []
    dist_borde = local.get("comuna_dist_borde_m") or 0
    osm_comuna = _normalizar_comuna_osm((osm or {}).get("city_district"))

    if not osm_comuna:
        return primario, "local"

    osm_n = _norm(osm_comuna)

    if osm_n == _norm(primario):
        return primario, "local+osm"

    for v in vecinos:
        if osm_n == _norm(v["nombre"]):
            if dist_borde < 100.0 and v["distancia_m"] < 150.0:
                return v["nombre"], "osm_corrige_borde"
            break

    return primario, "local"


def _verificar_direccion(
    local: dict,
    barrio_final: Optional[str],
    comuna_final: Optional[str],
    fuente_barrio: str,
    fuente_comuna: str,
    nominatim: Optional[dict],
    dentro_cali: bool,
) -> dict:
    """
    Cruza señales geométricas (basemaps locales) y semánticas (Nominatim) para
    estimar la confianza de la dirección reconstruida.

    Devuelve un dict con:
      - score: 0-100 (mayor = más confiable).
      - nivel: 'alta' | 'media' | 'baja' | 'fuera_cali'.
      - checks: dict de verificaciones puntuales con `ok` y `detalle`.
      - advertencias: lista de strings con problemas detectados.
    """
    checks: dict[str, dict] = {}
    advertencias: list[str] = []

    # 1) Dentro del bbox de Cali (gate principal)
    checks["dentro_cali"] = {
        "ok": bool(dentro_cali),
        "detalle": "Coordenada dentro del bbox de Cali" if dentro_cali else
                    "Coordenada fuera del bbox de Cali",
    }
    if not dentro_cali:
        advertencias.append("Coordenada fuera de Cali; basemaps no aplican.")
        return {
            "score": 0,
            "nivel": "fuera_cali",
            "checks": checks,
            "advertencias": advertencias,
        }

    # 2) Barrio asignado por contención (no por nearest)
    dist_b = local.get("barrio_dist_borde_m") or 0.0
    barrio_contenido = barrio_final is not None and dist_b > 0.0
    checks["barrio_contenido"] = {
        "ok": barrio_contenido,
        "detalle": f"barrio={barrio_final!r}, dist_borde={dist_b:.1f} m",
    }
    if barrio_final is None:
        advertencias.append("Barrio no identificado por basemaps.")

    # 3) Comuna asignada por contención
    dist_c = local.get("comuna_dist_borde_m") or 0.0
    comuna_contenida = comuna_final is not None and dist_c > 0.0
    checks["comuna_contenida"] = {
        "ok": comuna_contenida,
        "detalle": f"comuna={comuna_final!r}, dist_borde={dist_c:.1f} m",
    }
    if comuna_final is None:
        advertencias.append("Comuna/corregimiento no identificado por basemaps.")

    # 4) Concordancia con OSM (no obligatoria, pero suma puntos)
    osm_barrio = _norm((nominatim or {}).get("suburb"))
    osm_comuna = _norm(
        _normalizar_comuna_osm((nominatim or {}).get("city_district"))
    )
    barrio_n = _norm(barrio_final)
    comuna_n = _norm(comuna_final)
    osm_acuerdo_barrio = bool(osm_barrio and osm_barrio == barrio_n)
    osm_acuerdo_comuna = bool(osm_comuna and osm_comuna == comuna_n)
    checks["osm_acuerdo_barrio"] = {
        "ok": osm_acuerdo_barrio,
        "detalle": f"osm={osm_barrio or '∅'} vs local={barrio_n or '∅'}",
    }
    checks["osm_acuerdo_comuna"] = {
        "ok": osm_acuerdo_comuna,
        "detalle": f"osm={osm_comuna or '∅'} vs local={comuna_n or '∅'}",
    }
    if nominatim and osm_barrio and not osm_acuerdo_barrio:
        advertencias.append(
            f"OSM reporta barrio '{(nominatim or {}).get('suburb')}' "
            f"distinto al catastral '{barrio_final}'."
        )

    # 5) Vía soportada: catastral, inferida por cruces o ausente
    via = local.get("via")
    via_inferida = bool(local.get("via_inferida"))
    if via is None:
        via_estado = "ausente"
    elif via_inferida:
        soporte = int(via.get("soporte_cruces") or 0)
        via_estado = "inferida_fuerte" if soporte >= 2 else "inferida_debil"
    else:
        via_estado = "catastral"
    checks["via_disponible"] = {
        "ok": via is not None,
        "detalle": f"estado={via_estado}, dist={via.get('distancia_m') if via else 'N/A'} m",
    }
    if via is None:
        advertencias.append("No se pudo determinar una vía cercana.")
    elif via_estado == "inferida_debil":
        advertencias.append(
            "Vía inferida con soporte débil (un solo cruce); úsese con cautela."
        )

    # 6) Cruce cercano para anclar el numeral
    cruce = local.get("cruce")
    cruce_ok = cruce is not None and (cruce.get("distancia_m") or 999) <= 80.0
    checks["cruce_anclaje"] = {
        "ok": cruce_ok,
        "detalle": (
            f"cruce={cruce['nombre']!r} a {cruce['distancia_m']} m"
            if cruce else "Sin cruce cercano (<150 m)"
        ),
    }

    # ───── Score ponderado (0-100) ─────
    score = 0
    if checks["barrio_contenido"]["ok"]:
        score += 25
    elif barrio_final is not None:
        score += 10  # asignado por vecindad (caso borde)
    if checks["comuna_contenida"]["ok"]:
        score += 20
    elif comuna_final is not None:
        score += 8
    if via is not None:
        score += 20 if via_estado in ("catastral", "inferida_fuerte") else 10
    if cruce_ok:
        score += 15
    elif cruce is not None:
        score += 5
    if osm_acuerdo_barrio:
        score += 10
    if osm_acuerdo_comuna:
        score += 10
    # Bonus por reconciliación OSM
    if fuente_barrio == "osm_corrige_borde":
        score = min(100, score + 5)

    score = max(0, min(100, score))

    if score >= 75:
        nivel = "alta"
    elif score >= 50:
        nivel = "media"
    else:
        nivel = "baja"

    return {
        "score": score,
        "nivel": nivel,
        "checks": checks,
        "advertencias": advertencias,
    }


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

    # Reconciliación estricta: OSM solo corrige si coincide con un polígono vecino real
    barrio_final, fuente_barrio = _reconciliar_barrio(local, nominatim)
    comuna_final, fuente_comuna = _reconciliar_comuna(local, nominatim)

    direccion_legible = _componer_direccion(
        local["via"], local["cruce"], barrio_final, comuna_final, nominatim
    )

    verificacion = _verificar_direccion(
        local=local,
        barrio_final=barrio_final,
        comuna_final=comuna_final,
        fuente_barrio=fuente_barrio,
        fuente_comuna=fuente_comuna,
        nominatim=nominatim,
        dentro_cali=dentro_cali,
    )

    return {
        "success": True,
        "coordenada": {"lat": lat, "lon": lon},
        "dentro_de_cali": dentro_cali,
        "barrio_vereda": barrio_final,
        "comuna_corregimiento": comuna_final,
        "via": local["via"],
        "cruce_mas_cercano": local["cruce"],
        "direccion_legible": direccion_legible,
        "direccion_osm": (nominatim or {}).get("display_name"),
        "osm": nominatim,
        "fuentes": fuentes,
        "verificacion": verificacion,
        "asignacion": {
            "barrio_fuente": fuente_barrio,
            "barrio_local": local.get("barrio"),
            "barrio_local_vecinos": local.get("barrio_vecinos"),
            "barrio_dist_borde_m": local.get("barrio_dist_borde_m"),
            "barrio_osm": (nominatim or {}).get("suburb"),
            "comuna_fuente": fuente_comuna,
            "comuna_local": local.get("comuna"),
            "comuna_local_vecinos": local.get("comuna_vecinos"),
            "comuna_dist_borde_m": local.get("comuna_dist_borde_m"),
            "comuna_osm": _normalizar_comuna_osm((nominatim or {}).get("city_district")),
        },
    }
