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
# Test 4 — nearest via existe y tiene distancia razonable
# ──────────────────────────────────────────────────────────────────────────────
@patch("app.geocoding.reverse._nominatim_reverse", new_callable=AsyncMock, return_value=None)
def test_via_distancia_razonable(mock_nominatim):
    """La vía más cercana al centro de Cali debe estar a menos de 200m."""
    from app.geocoding.reverse import reverse_geocode

    result = _run(reverse_geocode(LAT_CALI, LON_CALI, usar_nominatim=False))

    via = result.get("via")
    if via is None:
        pytest.skip("No se encontró vía para estas coordenadas (puede ser zona sin cobertura)")

    dist = via.get("distancia_m", 99999)
    assert dist < 200, f"Vía a {dist}m — demasiado lejos para el centro de Cali"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5 — spatial_index cargó los basemaps correctamente
# ──────────────────────────────────────────────────────────────────────────────
def test_spatial_index_cargado():
    """Los STRtree y listas de polígonos deben tener elementos > 0."""
    from app.geocoding import spatial_index as si

    assert len(si._STREET_GEOMS) > 0, "No se cargaron vías"
    assert len(si._CRUCE_GEOMS) > 0, "No se cargaron cruces"
    assert si._STREET_TREE is not None, "STRtree de vías no inicializado"
    assert si._CRUCE_TREE is not None, "STRtree de cruces no inicializado"
