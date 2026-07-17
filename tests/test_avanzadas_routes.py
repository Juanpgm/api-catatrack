"""
Tests del módulo de Avanzadas Diagnósticas (captura de campo).

Cubre: catálogos, creación (con idempotencia, validación y fotos),
listado y detalle. Firestore y S3 se simulan con los fakes de
``tests/fakes_firestore.py`` — no se requiere red ni credenciales reales.
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
def _reset_catalogos_cache():
    """El cache TTL de catálogos es module-level: sin este reset, el valor
    calculado con el ``fake_db`` de un test se filtraría al siguiente.
    """
    avanzadas_routes._catalogos_cache = None
    yield
    avanzadas_routes._catalogos_cache = None


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
        "asistentes": [
            {
                "nombre": "Juan Pérez",
                "organismo": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
                "celular": "3001234567",
                "correo": "juan@test.com",
            }
        ],
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


# ──────────────────────────────────────────────────────────────────────────
# Autenticación
# ──────────────────────────────────────────────────────────────────────────

def test_catalogos_requiere_autenticacion(unauthenticated_client):
    response = unauthenticated_client.get("/avanzadas/catalogos")
    assert response.status_code == 403


def test_crear_avanzada_requiere_autenticacion(unauthenticated_client):
    response = _post_avanzada(unauthenticated_client, _valid_datos())
    assert response.status_code == 403


def test_listar_requiere_autenticacion(unauthenticated_client):
    assert unauthenticated_client.get("/avanzadas").status_code == 403


def test_detalle_requiere_autenticacion(unauthenticated_client):
    assert unauthenticated_client.get("/avanzadas/cualquier-id").status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# GET /avanzadas/catalogos
# ──────────────────────────────────────────────────────────────────────────

def test_catalogos_devuelve_defaults(client):
    response = client.get("/avanzadas/catalogos")
    assert response.status_code == 200
    body = response.json()

    assert "En Un 2x3" in body["estrategias"]
    assert "Ana Maria Carabali" in body["equipo"]
    assert any(d.startswith("DAGMA - ") for d in body["dependencias"])
    assert "Poda de árboles (autorización)" in body["categorias"]["DAGMA"]


def test_catalogos_incluye_categorias_personalizadas(client, fake_db):
    fake_db.collection("categorias_personalizadas").document().set({
        "entidad": "DAGMA",
        "categoria": "Categoría custom de prueba",
        "fecha": "2026-07-10",
    })

    body = client.get("/avanzadas/catalogos").json()

    categorias_dagma = body["categorias"]["DAGMA"]
    assert "Categoría custom de prueba" in categorias_dagma
    # Los defaults van primero.
    assert categorias_dagma[0] == "Poda de árboles (autorización)"


def test_catalogos_no_duplica_categoria_personalizada_ya_en_defaults(client, fake_db):
    fake_db.collection("categorias_personalizadas").document().set({
        "entidad": "DAGMA",
        "categoria": "Poda de árboles (autorización)",
        "fecha": "2026-07-10",
    })

    body = client.get("/avanzadas/catalogos").json()
    categorias_dagma = body["categorias"]["DAGMA"]
    assert categorias_dagma.count("Poda de árboles (autorización)") == 1


def test_catalogos_categoria_personalizada_crea_entrada_para_entidad_nueva(client, fake_db):
    fake_db.collection("categorias_personalizadas").document().set({
        "entidad": "Metro Cali",
        "categoria": "Nueva categoría metro",
        "fecha": "2026-07-10",
    })

    body = client.get("/avanzadas/catalogos").json()
    assert "Nueva categoría metro" in body["categorias"]["Metro Cali"]


# ──────────────────────────────────────────────────────────────────────────
# GET /avanzadas/catalogos — cache TTL en memoria
# ──────────────────────────────────────────────────────────────────────────

def _spy_stream_calls(monkeypatch, collection_name: str) -> dict:
    """Instrumenta FakeCollection.stream para contar streams de una
    colección puntual, siguiendo el mismo patrón que
    ``test_crear_avanzada_numero_usa_count_en_lugar_de_stream``.
    """
    from tests.fakes_firestore import FakeCollection

    calls = {"stream": 0}
    original_stream = FakeCollection.stream

    def spy_stream(self):
        if self.name == collection_name:
            calls["stream"] += 1
        return original_stream(self)

    monkeypatch.setattr(FakeCollection, "stream", spy_stream)
    return calls


def test_catalogos_usa_cache_evita_segundo_stream(client, fake_db, monkeypatch):
    calls = _spy_stream_calls(monkeypatch, "categorias_personalizadas")

    r1 = client.get("/avanzadas/catalogos")
    r2 = client.get("/avanzadas/catalogos")
    r3 = client.get("/avanzadas/catalogos")

    assert r1.status_code == r2.status_code == r3.status_code == 200
    # 3 requests dentro del TTL -> Firestore solo se consulta 1 vez.
    assert calls["stream"] == 1


def test_catalogos_cache_expira_por_ttl(client, fake_db, monkeypatch):
    calls = _spy_stream_calls(monkeypatch, "categorias_personalizadas")

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(avanzadas_routes.time, "monotonic", lambda: fake_now["t"])

    client.get("/avanzadas/catalogos")
    assert calls["stream"] == 1

    # Todavía dentro del TTL: no debe volver a streamear.
    fake_now["t"] += avanzadas_routes._AVANZADAS_CATALOGOS_TTL_SECONDS - 1
    client.get("/avanzadas/catalogos")
    assert calls["stream"] == 1

    # Pasado el TTL: debe refrescar.
    fake_now["t"] += 2
    client.get("/avanzadas/catalogos")
    assert calls["stream"] == 2


def test_catalogos_cache_se_invalida_al_crear_categoria_nueva(client, fake_db, monkeypatch):
    calls = _spy_stream_calls(monkeypatch, "categorias_personalizadas")

    client.get("/avanzadas/catalogos")
    assert calls["stream"] == 1

    datos = _valid_datos(client_id="cid-cache-invalida")
    datos["requerimientos"][0]["categoria_personalizada"] = "Categoría recién creada en campo"
    response = _post_avanzada(client, datos)
    assert response.status_code == 201

    body = client.get("/avanzadas/catalogos").json()
    # La nueva categoría personalizada está disponible sin esperar el TTL...
    assert "Categoría recién creada en campo" in body["categorias"]["DAGMA"]
    # ...porque el upsert forzó un refresh (segundo stream).
    assert calls["stream"] == 2


def test_catalogos_upsert_categoria_existente_no_invalida_cache_ni_falla(client, fake_db, monkeypatch):
    fake_db.collection("categorias_personalizadas").document().set({
        "entidad": "DAGMA",
        "categoria": "Categoría inventada en campo",
        "fecha": "2026-07-01",
    })

    calls = _spy_stream_calls(monkeypatch, "categorias_personalizadas")

    primera = client.get("/avanzadas/catalogos").json()
    assert calls["stream"] == 1
    assert "Categoría inventada en campo" in primera["categorias"]["DAGMA"]

    datos = _valid_datos(client_id="cid-cache-dup")
    datos["requerimientos"][0]["categoria_personalizada"] = "Categoría inventada en campo"
    response = _post_avanzada(client, datos)
    assert response.status_code == 201

    segunda = client.get("/avanzadas/catalogos").json()
    # No se rompió nada y no se duplicó la categoría.
    assert segunda["categorias"]["DAGMA"].count("Categoría inventada en campo") == 1
    # El upsert fue un duplicado: no tenía por qué invalidar el cache, así
    # que la segunda consulta de catálogos se sirvió del cache (sin stream
    # adicional).
    assert calls["stream"] == 1


def test_catalogos_payload_igual_en_cache_y_fresco(client, fake_db):
    fake_db.collection("categorias_personalizadas").document().set({
        "entidad": "DAGMA",
        "categoria": "Categoría para comparar cache vs fresco",
        "fecha": "2026-07-10",
    })

    primera = client.get("/avanzadas/catalogos").json()  # calcula y cachea
    segunda = client.get("/avanzadas/catalogos").json()  # servida desde cache

    assert primera == segunda


# ──────────────────────────────────────────────────────────────────────────
# POST /avanzadas — creación
# ──────────────────────────────────────────────────────────────────────────

def test_crear_avanzada_exitosa(client, fake_db):
    response = _post_avanzada(client, _valid_datos())
    assert response.status_code == 201
    body = response.json()

    assert body["client_id"] == "cid-001"
    assert body["id"] == "cid-001"
    assert body["nombre_avanzada"] == "Avanzada Comuna 3"
    assert body["created_by"] == "tester-uid"
    assert body["numero"] == 1
    assert body["requerimientos_count"] == 1
    assert len(body["requerimientos"]) == 1

    req = body["requerimientos"][0]
    assert req["avanzada_client_id"] == "cid-001"
    assert req["req_index"] == 0
    assert req["entidad"].startswith("DAGMA")
    assert req["fecha"] == "2026-07-10"
    assert req["nombre_avanzada"] == "Avanzada Comuna 3"
    assert req["estrategia"] == "En Un 2x3"
    assert req["fotos_urls"] == []

    # Persistencia real en el fake Firestore.
    avanzada_doc = fake_db.collection("avanzadas").document("cid-001").get()
    assert avanzada_doc.exists
    assert len(fake_db.collection("avanzadas_requerimientos").stream()) == 1


def test_crear_avanzada_numero_incrementa(client):
    _post_avanzada(client, _valid_datos(client_id="cid-a"))
    r2 = _post_avanzada(client, _valid_datos(client_id="cid-b"))
    assert r2.json()["numero"] == 2


def test_crear_avanzada_sube_fotos_a_s3(client, fake_s3):
    files = [
        ("foto_equipo", ("equipo.jpg", b"fake-equipo-bytes", "image/jpeg")),
        ("fotos_req_0", ("foto1.jpg", b"foto1-bytes", "image/jpeg")),
        ("fotos_req_0", ("foto2.jpg", b"foto2-bytes", "image/jpeg")),
    ]
    response = _post_avanzada(client, _valid_datos(client_id="cid-fotos"), files=files)
    assert response.status_code == 201
    body = response.json()

    assert body["foto_equipo_url"] is not None
    assert "cid-fotos" in body["foto_equipo_url"]
    assert len(body["requerimientos"][0]["fotos_urls"]) == 2
    # 1 foto de equipo + 2 fotos del requerimiento = 3 subidas a S3.
    assert len(fake_s3.uploaded) == 3


def test_crear_avanzada_trunca_a_5_fotos_por_requerimiento(client, fake_s3):
    files = [
        ("fotos_req_0", (f"foto{i}.jpg", f"bytes-{i}".encode(), "image/jpeg"))
        for i in range(7)
    ]
    response = _post_avanzada(client, _valid_datos(client_id="cid-trunca"), files=files)
    assert response.status_code == 201
    body = response.json()

    assert len(body["requerimientos"][0]["fotos_urls"]) == 5
    assert len(fake_s3.uploaded) == 5


def test_crear_avanzada_idempotente_por_client_id(client, fake_db):
    datos = _valid_datos(client_id="cid-dup")

    first = _post_avanzada(client, datos)
    assert first.status_code == 201

    second = _post_avanzada(client, datos)
    assert second.status_code == 200
    assert second.json()["client_id"] == "cid-dup"

    # No se duplicó el documento de avanzada ni sus requerimientos.
    assert len(fake_db.collection("avanzadas").stream()) == 1
    assert len(fake_db.collection("avanzadas_requerimientos").stream()) == 1


def test_crear_avanzada_upsert_categoria_personalizada(client, fake_db):
    datos = _valid_datos(client_id="cid-cat")
    datos["requerimientos"][0]["categoria_personalizada"] = "Categoría inventada en campo"

    response = _post_avanzada(client, datos)
    assert response.status_code == 201

    personalizadas = [d.to_dict() for d in fake_db.collection("categorias_personalizadas").stream()]
    assert len(personalizadas) == 1
    assert personalizadas[0]["entidad"] == "DAGMA"
    assert personalizadas[0]["categoria"] == "Categoría inventada en campo"


def test_crear_avanzada_no_duplica_categoria_personalizada_existente(client, fake_db):
    fake_db.collection("categorias_personalizadas").document().set({
        "entidad": "DAGMA",
        "categoria": "Categoría inventada en campo",
        "fecha": "2026-07-01",
    })

    datos = _valid_datos(client_id="cid-cat-2")
    datos["requerimientos"][0]["categoria_personalizada"] = "Categoría inventada en campo"

    _post_avanzada(client, datos)

    personalizadas = [d.to_dict() for d in fake_db.collection("categorias_personalizadas").stream()]
    assert len(personalizadas) == 1


@pytest.mark.parametrize("campo", [
    "nombre_avanzada", "fecha", "estrategia", "comuna", "barrio", "direccion", "coordenadas",
])
def test_crear_avanzada_rechaza_campo_obligatorio_vacio(client, campo):
    datos = _valid_datos()
    datos[campo] = ""
    response = _post_avanzada(client, datos)
    assert response.status_code == 422


def test_crear_avanzada_rechaza_encargados_vacio(client):
    datos = _valid_datos()
    datos["encargados"] = []
    response = _post_avanzada(client, datos)
    assert response.status_code == 422


def test_crear_avanzada_rechaza_sin_requerimientos(client):
    datos = _valid_datos()
    datos["requerimientos"] = []
    response = _post_avanzada(client, datos)
    assert response.status_code == 422


@pytest.mark.parametrize("campo", ["entidad", "requerimiento", "ubicacion"])
def test_crear_avanzada_rechaza_requerimiento_incompleto(client, campo):
    datos = _valid_datos()
    datos["requerimientos"][0][campo] = ""
    response = _post_avanzada(client, datos)
    assert response.status_code == 422


def test_crear_avanzada_rechaza_json_malformado(client):
    response = client.post("/avanzadas", data={"datos": "{no es json"}, files=[])
    assert response.status_code == 422


def test_crear_avanzada_rechaza_client_id_vacio(client):
    datos = _valid_datos(client_id="")
    response = _post_avanzada(client, datos)
    assert response.status_code == 422


def test_crear_avanzada_falla_s3_no_escribe_en_firestore(fake_db, monkeypatch):
    s3 = FakeS3Client(fail_on_upload=True)
    monkeypatch.setattr(avanzadas_routes, "get_s3_client", lambda: s3)
    app = FastAPI()
    app.include_router(avanzadas_routes.router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    client = TestClient(app)

    files = [
        ("foto_equipo", ("equipo.jpg", b"fake-equipo-bytes", "image/jpeg")),
    ]
    response = _post_avanzada(client, _valid_datos(client_id="cid-s3-fail"), files=files)

    assert response.status_code == 502
    assert "boto" not in response.json()["detail"].lower()
    assert "s3" not in response.json()["detail"].lower() or "error" in response.json()["detail"].lower()

    assert len(fake_db.collection("avanzadas").stream()) == 0
    assert len(fake_db.collection("avanzadas_requerimientos").stream()) == 0


def test_crear_avanzada_reintento_no_duplica_requerimientos(client, fake_db):
    datos = _valid_datos(client_id="cid-retry")

    # Simula un intento previo parcialmente fallido: el requerimiento 0 ya
    # quedó escrito bajo el id determinístico que generaría el endpoint.
    fake_db.collection("avanzadas_requerimientos").document("cid-retry_0").set({
        "avanzada_client_id": "cid-retry",
        "req_index": 0,
        "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
        "categoria": "Poda de árboles (autorización)",
        "categoria_personalizada": None,
        "requerimiento": "Árbol caído bloquea la vía",
        "ubicacion": "Frente al parque central",
        "coordenadas": "3.4520, -76.5322",
        "fotos_urls": [],
        "fecha": "2026-07-10",
        "nombre_avanzada": "Avanzada Comuna 3",
        "estrategia": "En Un 2x3",
        "created_at": "2026-07-10T00:00:00-05:00",
    })

    response = _post_avanzada(client, datos)
    assert response.status_code == 201

    reqs = list(fake_db.collection("avanzadas_requerimientos").stream())
    reqs_de_avanzada = [
        d for d in reqs if d.to_dict().get("avanzada_client_id") == "cid-retry"
    ]
    assert len(reqs_de_avanzada) == 1
    assert reqs_de_avanzada[0].id == "cid-retry_0"


def test_crear_avanzada_numero_usa_count_en_lugar_de_stream(client, fake_db, monkeypatch):
    from tests.fakes_firestore import FakeCollection

    calls = {"count": 0, "stream_avanzadas": 0}

    original_count = FakeCollection.count
    original_stream = FakeCollection.stream

    def spy_count(self):
        if self.name == "avanzadas":
            calls["count"] += 1
        return original_count(self)

    def spy_stream(self):
        if self.name == "avanzadas":
            calls["stream_avanzadas"] += 1
        return original_stream(self)

    monkeypatch.setattr(FakeCollection, "count", spy_count)
    monkeypatch.setattr(FakeCollection, "stream", spy_stream)

    response = _post_avanzada(client, _valid_datos(client_id="cid-count"))
    assert response.status_code == 201
    assert response.json()["numero"] == 1

    assert calls["count"] == 1
    assert calls["stream_avanzadas"] == 0


# ──────────────────────────────────────────────────────────────────────────
# GET /avanzadas — listado
# ──────────────────────────────────────────────────────────────────────────

def test_listar_avanzadas_orden_y_conteo(client):
    _post_avanzada(client, _valid_datos(client_id="cid-old", fecha="2026-01-01"))
    _post_avanzada(client, _valid_datos(client_id="cid-new", fecha="2026-06-01"))

    response = client.get("/avanzadas")
    assert response.status_code == 200
    body = response.json()

    assert len(body) == 2
    assert body[0]["client_id"] == "cid-new"
    assert body[1]["client_id"] == "cid-old"
    assert body[0]["requerimientos_count"] == 1
    # El listado no expone requerimientos completos, solo el conteo.
    assert "requerimientos" not in body[0]


def test_listar_avanzadas_respeta_limit(client):
    for i in range(3):
        _post_avanzada(client, _valid_datos(client_id=f"cid-{i}", fecha=f"2026-01-0{i + 1}"))

    response = client.get("/avanzadas", params={"limit": 2})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_listar_avanzadas_vacio(client):
    response = client.get("/avanzadas")
    assert response.status_code == 200
    assert response.json() == []


# ──────────────────────────────────────────────────────────────────────────
# GET /avanzadas/{client_id} — detalle
# ──────────────────────────────────────────────────────────────────────────

def test_detalle_avanzada_incluye_requerimientos(client):
    _post_avanzada(client, _valid_datos(client_id="cid-detalle"))

    response = client.get("/avanzadas/cid-detalle")
    assert response.status_code == 200
    body = response.json()

    assert body["client_id"] == "cid-detalle"
    assert len(body["requerimientos"]) == 1
    assert body["requerimientos"][0]["avanzada_client_id"] == "cid-detalle"


def test_detalle_avanzada_no_encontrada(client):
    response = client.get("/avanzadas/no-existe")
    assert response.status_code == 404
