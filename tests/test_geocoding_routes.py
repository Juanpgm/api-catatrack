from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.geocoding_routes import router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_reverse_geocode_post_no_requiere_token(monkeypatch):
    async def fake_reverse_geocode(lat: float, lon: float, *, usar_nominatim: bool = True):
        return {
            "success": True,
            "coordenada": {"lat": lat, "lon": lon},
            "dentro_de_cali": True,
            "barrio_vereda": "Prueba",
            "comuna_corregimiento": "COMUNA 01",
            "via": None,
            "cruce_mas_cercano": None,
            "direccion_legible": "Dirección de prueba",
            "direccion_osm": None,
            "osm": None,
            "fuentes": ["basemaps_cali"],
            "verificacion": {"score": 80, "nivel": "alta", "advertencias": []},
        }

    monkeypatch.setattr("app.routes.geocoding_routes.reverse_geocode", fake_reverse_geocode)

    client = _build_client()
    response = client.post(
        "/api/reverse-geocode",
        json={"lat": 3.4516, "lon": -76.5320, "usar_nominatim": False},
    )

    assert response.status_code == 200
    assert response.json()["coordenada"] == {"lat": 3.4516, "lon": -76.532}


def test_reverse_geocode_get_no_requiere_token(monkeypatch):
    async def fake_reverse_geocode(lat: float, lon: float, *, usar_nominatim: bool = True):
        return {
            "success": True,
            "coordenada": {"lat": lat, "lon": lon},
            "dentro_de_cali": True,
            "barrio_vereda": "Prueba",
            "comuna_corregimiento": "COMUNA 01",
            "via": None,
            "cruce_mas_cercano": None,
            "direccion_legible": "Dirección de prueba",
            "direccion_osm": None,
            "osm": None,
            "fuentes": ["basemaps_cali"],
            "verificacion": {"score": 80, "nivel": "alta", "advertencias": []},
        }

    monkeypatch.setattr("app.routes.geocoding_routes.reverse_geocode", fake_reverse_geocode)

    client = _build_client()
    response = client.get("/api/reverse-geocode?lat=3.4516&lon=-76.532&usar_nominatim=false")

    assert response.status_code == 200
    assert response.json()["coordenada"] == {"lat": 3.4516, "lon": -76.532}
