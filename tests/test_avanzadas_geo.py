"""
Tests de ``GET /avanzadas/geo`` y del helper puro ``_parsear_coordenadas``.

Cubre: parseo defensivo del string "lat, lng" tal como quedó en Firestore
tras la migración desde Excel (incluyendo casos malformados/ambiguos),
el armado de los tres arreglos de puntos (avanzadas/requerimientos/
jornadas), el conteo honesto de ``omitidos`` para records sin ubicación
parseable, el cache TTL en memoria (mismo patrón que
``/avanzadas/estadisticas``) y el orden de registro de la ruta respecto
de ``/avanzadas/{client_id}``.

Este módulo tiene su propio set de fixtures (no hay ``conftest.py``
compartido en el proyecto), siguiendo el mismo estilo que
``test_avanzadas_estadisticas.py``.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_system.dependencies import get_current_user
from app.routes import avanzadas_routes
from tests.fakes_firestore import FakeFirestore, FakeS3Client


# ──────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────

_FAKE_USER = {"uid": "tester-uid", "email": "tester@catatrack.test"}


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr(avanzadas_routes, "db", db)
    return db


@pytest.fixture(autouse=True)
def _reset_caches():
    avanzadas_routes._catalogos_cache = None
    avanzadas_routes._estadisticas_cache = None
    avanzadas_routes._geo_cache = None
    yield
    avanzadas_routes._catalogos_cache = None
    avanzadas_routes._estadisticas_cache = None
    avanzadas_routes._geo_cache = None


@pytest.fixture()
def fake_s3(monkeypatch):
    s3 = FakeS3Client()
    monkeypatch.setattr(avanzadas_routes, "get_s3_client", lambda: s3)
    return s3


@pytest.fixture()
def client(fake_db, fake_s3):
    app = FastAPI()
    app.include_router(avanzadas_routes.router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    return TestClient(app)


@pytest.fixture()
def unauthenticated_client(fake_db, fake_s3):
    app = FastAPI()
    app.include_router(avanzadas_routes.router)
    return TestClient(app)


def _valid_datos(client_id: str = "cid-001", **overrides) -> dict:
    datos = {
        "client_id": client_id,
        "nombre_avanzada": "Avanzada Comuna 3",
        "fecha": "2026-07-10",
        "estrategia": "En Un 2x3",
        "sector": "Sector A",
        "comuna": "COMUNA 03",
        "barrio": "San Antonio",
        "direccion": "Calle 5 # 10-20",
        "coordenadas": "3.4516, -76.5320",
        "encargados": ["Ana Maria Carabali"],
        "asistentes": [],
        "requerimientos": [
            {
                "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
                "categoria": "Poda de árboles (autorización)",
                "categoria_personalizada": None,
                "requerimiento": "Árbol caído bloquea la vía",
                "ubicacion": "Frente al parque central",
                "coordenadas": "3.4520, -76.5322",
            }
        ],
    }
    datos.update(overrides)
    return datos


def _post_avanzada(client: TestClient, datos: dict, files=None):
    return client.post(
        "/avanzadas",
        data={"datos": json.dumps(datos)},
        files=files or [],
    )


def _spy_stream_calls(monkeypatch, collection_name: str) -> dict:
    from tests.fakes_firestore import FakeCollection

    calls = {"stream": 0}
    original_stream = FakeCollection.stream

    def spy_stream(self):
        if self.name == collection_name:
            calls["stream"] += 1
        return original_stream(self)

    monkeypatch.setattr(FakeCollection, "stream", spy_stream)
    return calls


def _set_avanzada(fake_db, doc_id: str, **campos) -> dict:
    data = {
        "client_id": doc_id,
        "nombre_avanzada": "Avanzada de prueba",
        "fecha": "2026-01-01",
        "estrategia": "En Un 2x3",
        "comuna": "COMUNA 01",
        "barrio": "Barrio X",
        "coordenadas": "3.45, -76.53",
        "requerimientos_count": 0,
    }
    data.update(campos)
    fake_db.collection("avanzadas").document(doc_id).set(data)
    return data


def _set_requerimiento(fake_db, doc_id: str, avanzada_client_id: str, **campos) -> dict:
    data = {
        "avanzada_client_id": avanzada_client_id,
        "req_index": 0,
        "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
        "categoria": "Poda de árboles (autorización)",
        "categoria_personalizada": None,
        "requerimiento": "Requerimiento de prueba",
        "ubicacion": "Ubicación de prueba",
        "coordenadas": "3.46, -76.54",
        "fotos_urls": [],
        "fecha": "2026-01-01",
        "estrategia": "En Un 2x3",
    }
    data.update(campos)
    fake_db.collection("avanzadas_requerimientos").document(doc_id).set(data)
    return data


def _set_jornada(fake_db, doc_id: str, **campos) -> dict:
    data = {
        "numero": 1,
        "fecha": "2026-01-01",
        "nombre_jornada": "Jornada de prueba",
        "comuna": "COMUNA 01",
        "barrio": "Barrio X",
        "estado": "finalizada",
        "coordenadas_encuentro": "3.47, -76.55",
    }
    data.update(campos)
    fake_db.collection("jornadas_integrales").document(doc_id).set(data)
    return data


# ──────────────────────────────────────────────────────────────────────────
# Unit tests: _parsear_coordenadas (helper puro, sin Firestore)
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("3.483293, -76.515065", (3.483293, -76.515065)),
        ("3.48,-76.51", (3.48, -76.51)),
        ("   3.48  ,   -76.51   ", (3.48, -76.51)),
        ("90, 180", (90.0, 180.0)),
        ("-90, -180", (-90.0, -180.0)),
        ("0, 0", (0.0, 0.0)),  # válido en sí mismo: 0,0 solo se evita por fallback fabricado, no por ser inválido
    ],
)
def test_parsear_coordenadas_casos_validos(valor, esperado):
    assert avanzadas_routes._parsear_coordenadas(valor) == esperado


@pytest.mark.parametrize(
    "valor",
    [
        None,
        "",
        "   ",
        "abc",
        "abc, def",
        "3.48",
        "3.48,-76.51,10",
        "3,48, -76,51",  # decimal-coma ambiguo contra el separador lat,lng -> se rechaza
        "300, -76.51",  # lat fuera de rango
        "3.48, -300",  # lng fuera de rango
        "-91, 0",
        "0, 181",
        123.45,
        ["3.48", "-76.51"],
        {"lat": 3.48, "lng": -76.51},
    ],
)
def test_parsear_coordenadas_casos_invalidos(valor):
    assert avanzadas_routes._parsear_coordenadas(valor) is None


# ──────────────────────────────────────────────────────────────────────────
# Autenticación
# ──────────────────────────────────────────────────────────────────────────

def test_geo_requiere_autenticacion(unauthenticated_client):
    response = unauthenticated_client.get("/avanzadas/geo")
    assert response.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# Orden de registro de rutas: /geo NO debe caer en el handler de /{client_id}
# ──────────────────────────────────────────────────────────────────────────

def test_geo_no_es_interceptada_por_ruta_dinamica_client_id(client, fake_db):
    # No existe ninguna avanzada con client_id == "geo". Si la ruta dinámica
    # interceptara la petición, respondería 404 "Avanzada 'geo' no
    # encontrada" en vez de la forma de /avanzadas/geo.
    response = client.get("/avanzadas/geo")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"avanzadas", "requerimientos", "jornadas", "omitidos"}


# ──────────────────────────────────────────────────────────────────────────
# Caso vacío
# ──────────────────────────────────────────────────────────────────────────

def test_geo_db_vacia(client):
    response = client.get("/avanzadas/geo")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "avanzadas": [],
        "requerimientos": [],
        "jornadas": [],
        "omitidos": {"avanzadas": 0, "requerimientos": 0, "jornadas": 0},
    }


# ──────────────────────────────────────────────────────────────────────────
# Avanzadas: coords válidas incluidas, inválidas/ausentes omitidas
# ──────────────────────────────────────────────────────────────────────────

def test_geo_avanzada_con_coords_validas_se_incluye(client, fake_db):
    _set_avanzada(
        fake_db, "cid-1",
        nombre_avanzada="Avanzada Norte",
        fecha="2026-02-01",
        estrategia="En Un 2x3",
        comuna="COMUNA 03",
        barrio="San Antonio",
        coordenadas="3.483293, -76.515065",
        requerimientos_count=5,
    )

    body = client.get("/avanzadas/geo").json()
    assert len(body["avanzadas"]) == 1
    punto = body["avanzadas"][0]
    assert punto == {
        "client_id": "cid-1",
        "nombre_avanzada": "Avanzada Norte",
        "fecha": "2026-02-01",
        "estrategia": "En Un 2x3",
        "comuna": "COMUNA 03",
        "barrio": "San Antonio",
        "lat": 3.483293,
        "lng": -76.515065,
        "requerimientos_count": 5,
    }
    assert body["omitidos"]["avanzadas"] == 0


@pytest.mark.parametrize("coords_malas", [None, "", "abc", "3.48"])
def test_geo_avanzada_con_coords_invalidas_se_omite_y_cuenta(client, fake_db, coords_malas):
    _set_avanzada(fake_db, "cid-mala", coordenadas=coords_malas)
    _set_avanzada(fake_db, "cid-buena", coordenadas="3.45, -76.53")

    body = client.get("/avanzadas/geo").json()
    assert len(body["avanzadas"]) == 1
    assert body["avanzadas"][0]["client_id"] == "cid-buena"
    assert body["omitidos"]["avanzadas"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Requerimientos: categoria efectiva, fotos_count, sin fallback a coords padre
# ──────────────────────────────────────────────────────────────────────────

def test_geo_requerimiento_con_coords_validas_se_incluye(client, fake_db):
    _set_avanzada(fake_db, "cid-1", coordenadas="3.45, -76.53")
    _set_requerimiento(
        fake_db, "req-1", avanzada_client_id="cid-1",
        entidad="DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
        categoria="Poda de árboles (autorización)",
        categoria_personalizada=None,
        requerimiento="Árbol caído",
        ubicacion="Parque central",
        coordenadas="3.4520, -76.5322",
        fotos_urls=["url1", "url2"],
        fecha="2026-01-05",
    )

    body = client.get("/avanzadas/geo").json()
    assert len(body["requerimientos"]) == 1
    punto = body["requerimientos"][0]
    assert punto["id"] == "req-1"
    assert punto["avanzada_client_id"] == "cid-1"
    assert punto["sigla"] == "DAGMA"
    assert punto["entidad"] == "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente"
    assert punto["categoria"] == "Poda de árboles (autorización)"
    assert punto["requerimiento"] == "Árbol caído"
    assert punto["ubicacion"] == "Parque central"
    assert punto["fecha"] == "2026-01-05"
    assert punto["lat"] == 3.452
    assert punto["lng"] == -76.5322
    assert punto["fotos_count"] == 2


def test_geo_requerimiento_categoria_personalizada_tiene_preferencia(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    _set_requerimiento(
        fake_db, "req-1", avanzada_client_id="cid-1",
        categoria="Categoria original", categoria_personalizada="Categoria custom",
    )

    body = client.get("/avanzadas/geo").json()
    assert body["requerimientos"][0]["categoria"] == "Categoria custom"


def test_geo_requerimiento_sin_fotos_cuenta_cero(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    _set_requerimiento(fake_db, "req-1", avanzada_client_id="cid-1", fotos_urls=None)

    body = client.get("/avanzadas/geo").json()
    assert body["requerimientos"][0]["fotos_count"] == 0


@pytest.mark.parametrize("coords_malas", [None, "", "abc"])
def test_geo_requerimiento_sin_coords_propias_se_omite_sin_fallback_a_avanzada(client, fake_db, coords_malas):
    # La avanzada padre SÍ tiene coordenadas válidas -- el requerimiento no
    # debe heredarlas: eso fabricaría una ubicación inexistente.
    _set_avanzada(fake_db, "cid-1", coordenadas="3.45, -76.53")
    _set_requerimiento(fake_db, "req-sin-coords", avanzada_client_id="cid-1", coordenadas=coords_malas)

    body = client.get("/avanzadas/geo").json()
    assert body["requerimientos"] == []
    assert body["omitidos"]["requerimientos"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Jornadas
# ──────────────────────────────────────────────────────────────────────────

def test_geo_jornada_con_coords_validas_se_incluye(client, fake_db):
    _set_jornada(
        fake_db, "jor-1",
        nombre_jornada="Jornada Integral Comuna 3",
        fecha="2026-03-01",
        comuna="COMUNA 03",
        barrio="San Antonio",
        estado="finalizada",
        coordenadas_encuentro="3.4700, -76.5500",
    )

    body = client.get("/avanzadas/geo").json()
    assert len(body["jornadas"]) == 1
    punto = body["jornadas"][0]
    assert punto == {
        "client_id": "jor-1",
        "nombre_jornada": "Jornada Integral Comuna 3",
        "fecha": "2026-03-01",
        "comuna": "COMUNA 03",
        "barrio": "San Antonio",
        "estado": "finalizada",
        "lat": 3.47,
        "lng": -76.55,
    }
    assert body["omitidos"]["jornadas"] == 0


@pytest.mark.parametrize("coords_malas", [None, "", "abc"])
def test_geo_jornada_sin_coords_validas_se_omite_y_cuenta(client, fake_db, coords_malas):
    _set_jornada(fake_db, "jor-mala", coordenadas_encuentro=coords_malas)

    body = client.get("/avanzadas/geo").json()
    assert body["jornadas"] == []
    assert body["omitidos"]["jornadas"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Cache TTL en memoria
# ──────────────────────────────────────────────────────────────────────────

def test_geo_cache_evita_streams_repetidos(client, fake_db, monkeypatch):
    calls_avanzadas = _spy_stream_calls(monkeypatch, "avanzadas")
    calls_requerimientos = _spy_stream_calls(monkeypatch, "avanzadas_requerimientos")
    calls_jornadas = _spy_stream_calls(monkeypatch, "jornadas_integrales")

    r1 = client.get("/avanzadas/geo")
    r2 = client.get("/avanzadas/geo")
    r3 = client.get("/avanzadas/geo")

    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert calls_avanzadas["stream"] == 1
    assert calls_requerimientos["stream"] == 1
    assert calls_jornadas["stream"] == 1


def test_geo_cache_expira_por_ttl(client, fake_db, monkeypatch):
    calls_avanzadas = _spy_stream_calls(monkeypatch, "avanzadas")

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(avanzadas_routes.time, "monotonic", lambda: fake_now["t"])

    client.get("/avanzadas/geo")
    assert calls_avanzadas["stream"] == 1

    fake_now["t"] += avanzadas_routes._AVANZADAS_GEO_TTL_SECONDS - 1
    client.get("/avanzadas/geo")
    assert calls_avanzadas["stream"] == 1

    fake_now["t"] += 2
    client.get("/avanzadas/geo")
    assert calls_avanzadas["stream"] == 2


def test_geo_cache_se_invalida_al_crear_avanzada_nueva(client, fake_db, monkeypatch):
    calls_avanzadas = _spy_stream_calls(monkeypatch, "avanzadas")

    primera = client.get("/avanzadas/geo").json()
    assert calls_avanzadas["stream"] == 1
    assert primera["avanzadas"] == []

    response = _post_avanzada(client, _valid_datos(client_id="cid-nueva"))
    assert response.status_code == 201

    segunda = client.get("/avanzadas/geo").json()
    assert calls_avanzadas["stream"] == 2
    assert len(segunda["avanzadas"]) == 1


def test_geo_cache_getter_no_permite_aliasing(client, fake_db):
    _set_avanzada(fake_db, "cid-1", coordenadas="3.45, -76.53")

    primera = avanzadas_routes._obtener_geo_cacheado()
    primera["avanzadas"][0]["lat"] = 999.0
    primera["omitidos"]["avanzadas"] = 999

    segunda = avanzadas_routes._obtener_geo_cacheado()
    assert segunda["avanzadas"][0]["lat"] == 3.45
    assert segunda["omitidos"]["avanzadas"] == 0


# ──────────────────────────────────────────────────────────────────────────
# OpenAPI: la ruta debe quedar registrada en el schema de la app real
# ──────────────────────────────────────────────────────────────────────────

def test_geo_route_aparece_en_openapi_schema():
    from app.main import app as real_app

    schema = real_app.openapi()
    assert "/avanzadas/geo" in schema["paths"]
