"""
Tests del módulo de reverse geocoding (basemaps catastrales de Cali).

Ejercita la rama síncrona (spatial_index) sin llamadas Nominatim para
evitar dependencias de red en CI. La función `reverse_geocode` es async;
se invoca con asyncio.run().
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Coordenadas de referencia en Cali (WGS84)
# ──────────────────────────────────────────────────────────────────────────────
# Centro de Cali: Plaza de Caycedo (3.4516°N, -76.5320°W)
LAT_CALI = 3.4516
LON_CALI = -76.5320

# Bogotá – fuera del bbox de Cali → dentro_de_cali = False
LAT_BOGOTA = 4.7110
LON_BOGOTA = -74.0721


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — coordenada dentro de Cali
# ──────────────────────────────────────────────────────────────────────────────
@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_reverse_geocode_en_cali(mock_nominatim):
    """Punto céntrico de Cali → dentro_de_cali=True, campos catastrales poblados."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_CALI, LON_CALI, usar_nominatim=False))

    assert result["success"] is True, "success debe ser True"
    assert result["dentro_de_cali"] is True, "El punto debe estar dentro de Cali"
    assert result["coordenada"]["lat"] == pytest.approx(LAT_CALI, abs=1e-6)
    assert result["coordenada"]["lon"] == pytest.approx(LON_CALI, abs=1e-6)

    # Al menos barrio o vía debería resolverse en el centro histórico
    tiene_barrio = result.get("barrio_vereda") is not None
    tiene_via = result.get("via") is not None
    assert tiene_barrio or tiene_via, (
        "Se esperaba barrio o vía para el centro de Cali, "
        f"se obtuvo: {result}"
    )

    assert isinstance(result["direccion_legible"], str)
    assert len(result["direccion_legible"]) > 0
    assert "fuentes" in result and len(result["fuentes"]) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — coordenada fuera de Cali
# ──────────────────────────────────────────────────────────────────────────────
@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_reverse_geocode_fuera_de_cali(mock_nominatim):
    """Bogotá → dentro_de_cali=False; campos catastrales None."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_BOGOTA, LON_BOGOTA, usar_nominatim=False))

    assert result["success"] is True
    assert result["dentro_de_cali"] is False
    assert result["barrio_vereda"] is None
    assert result["comuna_corregimiento"] is None


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — campos de respuesta correctamente tipados
# ──────────────────────────────────────────────────────────────────────────────
@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_reverse_geocode_schema(mock_nominatim):
    """La respuesta respeta el schema del endpoint: campos obligatorios y tipos."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_CALI, LON_CALI, usar_nominatim=False))

    required_keys = {
        "success", "coordenada", "dentro_de_cali",
        "barrio_vereda", "comuna_corregimiento",
        "via", "cruce_mas_cercano",
        "direccion_legible", "direccion_osm", "osm", "fuentes",
    }
    assert required_keys.issubset(result.keys()), (
        f"Faltan claves en la respuesta: {required_keys - result.keys()}"
    )
    assert isinstance(result["fuentes"], list)

    via = result.get("via")
    if via is not None:
        assert "distancia_m" in via
        assert isinstance(via["distancia_m"], (int, float))

    cruce = result.get("cruce_mas_cercano")
    if cruce is not None:
        assert "nombre" in cruce
        assert "distancia_m" in cruce


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — vía (catastral o inferida) con distancia razonable
# ──────────────────────────────────────────────────────────────────────────────
@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_via_distancia_razonable(mock_nominatim):
    """La vía resuelta (catastral o inferida por cruces) en el centro de Cali
    debe estar a menos de 250 m."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_CALI, LON_CALI, usar_nominatim=False))

    via = result.get("via")
    assert via is not None, (
        "Se esperaba al menos una vía inferida desde cruces para el centro de Cali"
    )
    dist = via.get("distancia_m", 99999)
    assert dist < 250, f"Vía a {dist}m — demasiado lejos para el centro de Cali"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5 — spatial_index cargó los basemaps obligatorios
# ──────────────────────────────────────────────────────────────────────────────
def test_spatial_index_cargado():
    """Barrios, comunas y cruces son los tres basemaps obligatorios. Las vías se
    derivan por inferencia a partir de los cruces (no se distribuye un basemap
    vial separado)."""
    from app.geocoding import spatial_index as si
    from app.routes.artefacto_360_routes import _BARRIOS_POLYGONS, _COMUNAS_POLYGONS

    assert len(_BARRIOS_POLYGONS) > 0, "No se cargaron polígonos de barrios"
    assert len(_COMUNAS_POLYGONS) > 0, "No se cargaron polígonos de comunas"
    assert len(si._CRUCE_GEOMS) > 0, "No se cargaron cruces"
    assert si._CRUCE_TREE is not None, "STRtree de cruces no inicializado"


# ──────────────────────────────────────────────────────────────────────────────
# Test 6 — inferencia de vía desde cruces (sin basemap vial catastral)
# ──────────────────────────────────────────────────────────────────────────────
def test_via_inferida_de_cruces_funciona():
    """`via_inferida_de_cruces` debe devolver un dict parseado para el centro de Cali."""
    from app.geocoding import spatial_index as si

    via = si.via_inferida_de_cruces(LON_CALI, LAT_CALI)
    assert via is not None, "Se esperaba vía inferida en el centro de Cali"
    assert via["tipo"] in {
        "Carrera", "Calle", "Diagonal", "Transversal",
        "Autopista", "Avenida", "Circular", "Vía",
    }, f"tipo inesperado: {via['tipo']}"
    assert via["numero"], "numero vacío"
    assert via.get("inferida") is True
    assert isinstance(via.get("soporte_cruces"), int) and via["soporte_cruces"] >= 1
    assert via["distancia_m"] <= 250


def test_via_inferida_fuera_de_cali_es_none():
    """Coordenada lejana sin cruces cercanos → None."""
    from app.geocoding import spatial_index as si

    assert si.via_inferida_de_cruces(LON_BOGOTA, LAT_BOGOTA) is None


# ──────────────────────────────────────────────────────────────────────────────
# Test 7 — bloque `verificacion` en la respuesta
# ──────────────────────────────────────────────────────────────────────────────
@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_verificacion_estructura_y_score(mock_nominatim):
    """La respuesta debe incluir `verificacion` con score, nivel, checks y advertencias."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_CALI, LON_CALI, usar_nominatim=False))
    v = result.get("verificacion")
    assert v is not None, "Falta bloque `verificacion` en la respuesta"

    assert set(v.keys()) >= {"score", "nivel", "checks", "advertencias"}
    assert 0 <= v["score"] <= 100
    assert v["nivel"] in {"alta", "media", "baja", "fuera_cali"}
    assert isinstance(v["checks"], dict)
    for nombre in (
        "dentro_cali", "barrio_contenido", "comuna_contenida",
        "via_disponible", "cruce_anclaje",
        "osm_acuerdo_barrio", "osm_acuerdo_comuna",
    ):
        assert nombre in v["checks"], f"Falta check '{nombre}'"
        assert "ok" in v["checks"][nombre]
        assert "detalle" in v["checks"][nombre]
    assert isinstance(v["advertencias"], list)


@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_verificacion_fuera_de_cali(mock_nominatim):
    """Coordenadas fuera de Cali → nivel='fuera_cali' y score=0."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_BOGOTA, LON_BOGOTA, usar_nominatim=False))
    v = result["verificacion"]
    assert v["nivel"] == "fuera_cali"
    assert v["score"] == 0
    assert any("Cali" in adv for adv in v["advertencias"])


@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_verificacion_score_alto_en_centro_cali(mock_nominatim):
    """El centro de Cali (Plaza de Caycedo) tiene cobertura completa de basemaps,
    por lo que el score debe ser al menos 'media' (>=50)."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_CALI, LON_CALI, usar_nominatim=False))
    v = result["verificacion"]
    assert v["score"] >= 50, (
        f"Score {v['score']} demasiado bajo en el centro de Cali. "
        f"advertencias={v['advertencias']}"
    )
