"""
Tests de ``GET /avanzadas/estadisticas``.

Cubre las agregaciones server-side (totales, por entidad, por categoría,
por comuna, por estrategia, por mes), el cache TTL en memoria (mismo
patrón que el de ``/avanzadas/catalogos``) y los casos borde de datos
reales: requerimientos huérfanos, meses con huecos y empates
deterministas.

Este módulo tiene su propio set de fixtures (no hay ``conftest.py`` en
el proyecto, así que nada se comparte automáticamente entre archivos de
test) siguiendo el mismo estilo que ``test_avanzadas_routes.py``.
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
# Fixtures / helpers (duplicados de test_avanzadas_routes.py: no hay
# conftest.py compartido en este proyecto)
# ──────────────────────────────────────────────────────────────────────────

_FAKE_USER = {"uid": "tester-uid", "email": "tester@catatrack.test"}


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr(avanzadas_routes, "db", db)
    return db


@pytest.fixture(autouse=True)
def _reset_caches():
    """Los caches TTL de catálogos y estadísticas son module-level: sin
    este reset, el valor calculado con el ``fake_db`` de un test se
    filtraría al siguiente.
    """
    avanzadas_routes._catalogos_cache = None
    avanzadas_routes._estadisticas_cache = None
    yield
    avanzadas_routes._catalogos_cache = None
    avanzadas_routes._estadisticas_cache = None


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


def _spy_stream_calls(monkeypatch, collection_name: str) -> dict:
    """Instrumenta FakeCollection.stream para contar streams de una
    colección puntual (mismo patrón que en test_avanzadas_routes.py).
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


def _set_avanzada(fake_db, doc_id: str, **campos) -> dict:
    """Escribe un doc mínimo de 'avanzadas' directamente en el fake
    Firestore, sin pasar por el endpoint POST (para tests de reglas de
    agregación puntuales que no necesitan el flujo HTTP completo).
    """
    data = {
        "client_id": doc_id,
        "nombre_avanzada": "Avanzada de prueba",
        "fecha": "2026-01-01",
        "estrategia": "En Un 2x3",
        "comuna": "COMUNA 01",
        "asistentes": [],
    }
    data.update(campos)
    fake_db.collection("avanzadas").document(doc_id).set(data)
    return data


def _set_requerimiento(fake_db, doc_id: str, avanzada_client_id: str, **campos) -> dict:
    """Escribe un doc mínimo de 'avanzadas_requerimientos' directamente."""
    data = {
        "avanzada_client_id": avanzada_client_id,
        "req_index": 0,
        "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
        "categoria": "Poda de árboles (autorización)",
        "categoria_personalizada": None,
        "requerimiento": "Requerimiento de prueba",
        "ubicacion": "Ubicación de prueba",
        "fecha": "2026-01-01",
        "estrategia": "En Un 2x3",
    }
    data.update(campos)
    fake_db.collection("avanzadas_requerimientos").document(doc_id).set(data)
    return data


# ──────────────────────────────────────────────────────────────────────────
# Autenticación
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_requiere_autenticacion(unauthenticated_client):
    response = unauthenticated_client.get("/avanzadas/estadisticas")
    assert response.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# Caso vacío
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_db_vacia(client):
    response = client.get("/avanzadas/estadisticas")
    assert response.status_code == 200
    body = response.json()

    assert body["totales"] == {
        "avanzadas": 0,
        "requerimientos": 0,
        "comunas": 0,
        "entidades": 0,
        "asistentes": 0,
        "promedio_requerimientos": 0.0,
    }
    assert body["por_entidad"] == []
    assert body["por_categoria"] == []
    assert body["por_comuna"] == []
    assert body["por_estrategia"] == []
    assert body["por_mes"] == []


# ──────────────────────────────────────────────────────────────────────────
# Requerimiento huérfano (avanzada_client_id sin avanzada padre)
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_requerimiento_huerfano_no_rompe_y_no_cuenta(client, fake_db):
    _set_avanzada(fake_db, "cid-1", comuna="COMUNA 03", estrategia="En Un 2x3")
    _set_requerimiento(fake_db, "req-1", avanzada_client_id="cid-1", entidad="DAGMA - Depto")

    # Huérfano: su avanzada_client_id no corresponde a ninguna avanzada.
    _set_requerimiento(fake_db, "req-huerfano", avanzada_client_id="no-existe", entidad="DAGMA - Depto")

    response = client.get("/avanzadas/estadisticas")
    assert response.status_code == 200
    body = response.json()

    # El huérfano SÍ cuenta en el total global de requerimientos...
    assert body["totales"]["requerimientos"] == 2

    # ...pero NO se contabiliza en ninguna comuna ni estrategia (solo se
    # puede unir a través de la avanzada padre, que no existe).
    comuna_03 = next(c for c in body["por_comuna"] if c["comuna"] == "COMUNA 03")
    assert comuna_03["requerimientos"] == 1
    total_requerimientos_en_comunas = sum(c["requerimientos"] for c in body["por_comuna"])
    assert total_requerimientos_en_comunas == 1

    estrategia = next(e for e in body["por_estrategia"] if e["estrategia"] == "En Un 2x3")
    assert estrategia["requerimientos"] == 1
    total_requerimientos_en_estrategias = sum(e["requerimientos"] for e in body["por_estrategia"])
    assert total_requerimientos_en_estrategias == 1


# ──────────────────────────────────────────────────────────────────────────
# por_mes: relleno de huecos
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_por_mes_rellena_huecos_cronologicamente(client, fake_db):
    _set_avanzada(fake_db, "cid-ene", fecha="2026-01-15")
    _set_avanzada(fake_db, "cid-abr", fecha="2026-04-02")
    _set_requerimiento(fake_db, "req-ene", avanzada_client_id="cid-ene", fecha="2026-01-15")

    response = client.get("/avanzadas/estadisticas")
    body = response.json()

    meses = [m["mes"] for m in body["por_mes"]]
    assert meses == ["2026-01", "2026-02", "2026-03", "2026-04"]

    por_mes = {m["mes"]: m for m in body["por_mes"]}
    assert por_mes["2026-01"] == {"mes": "2026-01", "avanzadas": 1, "requerimientos": 1}
    assert por_mes["2026-02"] == {"mes": "2026-02", "avanzadas": 0, "requerimientos": 0}
    assert por_mes["2026-03"] == {"mes": "2026-03", "avanzadas": 0, "requerimientos": 0}
    assert por_mes["2026-04"] == {"mes": "2026-04", "avanzadas": 1, "requerimientos": 0}


def test_estadisticas_por_mes_ignora_fechas_malformadas(client, fake_db):
    _set_avanzada(fake_db, "cid-ok", fecha="2026-02-01")
    _set_avanzada(fake_db, "cid-corta", fecha="26-0")
    _set_avanzada(fake_db, "cid-none", fecha=None)

    response = client.get("/avanzadas/estadisticas")
    body = response.json()

    assert [m["mes"] for m in body["por_mes"]] == ["2026-02"]


# ──────────────────────────────────────────────────────────────────────────
# Orden determinista / empates
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_por_entidad_empate_ordena_por_sigla(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    # Insertamos primero "ZZZ" y luego "AAA" con el MISMO total (2 c/u).
    _set_requerimiento(fake_db, "req-z1", avanzada_client_id="cid-1", entidad="ZZZ - Entidad Z")
    _set_requerimiento(fake_db, "req-z2", avanzada_client_id="cid-1", entidad="ZZZ - Entidad Z")
    _set_requerimiento(fake_db, "req-a1", avanzada_client_id="cid-1", entidad="AAA - Entidad A")
    _set_requerimiento(fake_db, "req-a2", avanzada_client_id="cid-1", entidad="AAA - Entidad A")

    body = client.get("/avanzadas/estadisticas").json()

    siglas = [e["sigla"] for e in body["por_entidad"]]
    # A pesar de que "ZZZ" se insertó primero, el empate en total se
    # rompe por sigla ASC -> "AAA" va antes.
    assert siglas == ["AAA", "ZZZ"]


def test_estadisticas_por_categoria_empate_total_y_categoria_ordena_por_sigla(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    # Misma categoría, mismo total (1 c/u), distinta sigla. Se inserta
    # primero la de sigla "ZZZ" para probar que el orden NO depende de
    # la iteración del stream sino del tie-break explícito por sigla.
    _set_requerimiento(
        fake_db, "req-z", avanzada_client_id="cid-1",
        entidad="ZZZ - Entidad Z", categoria="Poda", categoria_personalizada=None,
    )
    _set_requerimiento(
        fake_db, "req-a", avanzada_client_id="cid-1",
        entidad="AAA - Entidad A", categoria="Poda", categoria_personalizada=None,
    )

    body = client.get("/avanzadas/estadisticas").json()

    siglas = [c["sigla"] for c in body["por_categoria"] if c["categoria"] == "Poda"]
    assert siglas == ["AAA", "ZZZ"]


def test_estadisticas_por_categoria_top_12(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    for i in range(15):
        _set_requerimiento(
            fake_db, f"req-{i}", avanzada_client_id="cid-1",
            categoria=f"Categoria {i:02d}", categoria_personalizada=None,
        )

    body = client.get("/avanzadas/estadisticas").json()
    assert len(body["por_categoria"]) == 12


# ──────────────────────────────────────────────────────────────────────────
# categoria_personalizada tiene preferencia sobre categoria
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_prefiere_categoria_personalizada_si_no_esta_vacia(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    _set_requerimiento(
        fake_db, "req-1", avanzada_client_id="cid-1",
        categoria="Categoria original", categoria_personalizada="Categoria custom",
    )

    body = client.get("/avanzadas/estadisticas").json()
    categorias = [c["categoria"] for c in body["por_categoria"]]
    assert "Categoria custom" in categorias
    assert "Categoria original" not in categorias


def test_estadisticas_categoria_personalizada_vacia_usa_categoria(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    _set_requerimiento(
        fake_db, "req-1", avanzada_client_id="cid-1",
        categoria="Categoria original", categoria_personalizada="   ",
    )
    _set_requerimiento(
        fake_db, "req-2", avanzada_client_id="cid-1",
        categoria="Otra categoria", categoria_personalizada=None,
    )

    body = client.get("/avanzadas/estadisticas").json()
    categorias = [c["categoria"] for c in body["por_categoria"]]
    assert "Categoria original" in categorias
    assert "Otra categoria" in categorias


def test_estadisticas_sin_categoria_efectiva_se_excluye(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    _set_requerimiento(
        fake_db, "req-vacio", avanzada_client_id="cid-1",
        categoria=None, categoria_personalizada="   ",
    )
    _set_requerimiento(
        fake_db, "req-con-cat", avanzada_client_id="cid-1",
        categoria="Categoria valida", categoria_personalizada=None,
    )

    body = client.get("/avanzadas/estadisticas").json()
    total_por_categoria = sum(c["total"] for c in body["por_categoria"])
    # Solo el requerimiento con categoría efectiva no vacía se agrega.
    assert total_por_categoria == 1
    assert body["por_categoria"][0]["categoria"] == "Categoria valida"


# ──────────────────────────────────────────────────────────────────────────
# Totales: comunas / entidades / asistentes / promedio
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_totales_comunas_entidades_asistentes_promedio(client, fake_db):
    _set_avanzada(
        fake_db, "cid-1", comuna="COMUNA 03",
        asistentes=[{"nombre": "A"}, {"nombre": "B"}],
    )
    _set_avanzada(fake_db, "cid-2", comuna="COMUNA 03", asistentes=[{"nombre": "C"}])
    _set_avanzada(fake_db, "cid-3", comuna="COMUNA 05", asistentes=[])
    # Avanzada sin campo 'asistentes' en absoluto -> debe contar como 0.
    fake_db.collection("avanzadas").document("cid-4").set({
        "comuna": "COMUNA 05", "fecha": "2026-01-01", "estrategia": "En Un 2x3",
    })

    _set_requerimiento(fake_db, "req-1", avanzada_client_id="cid-1", entidad="DAGMA - Depto Ambiente")
    _set_requerimiento(fake_db, "req-2", avanzada_client_id="cid-1", entidad="EMCALI - Empresa Municipal")

    body = client.get("/avanzadas/estadisticas").json()
    totales = body["totales"]

    assert totales["avanzadas"] == 4
    assert totales["requerimientos"] == 2
    assert totales["comunas"] == 2  # COMUNA 03, COMUNA 05
    assert totales["entidades"] == 2  # DAGMA, EMCALI
    assert totales["asistentes"] == 3  # 2 + 1 + 0 + 0
    assert totales["promedio_requerimientos"] == 0.5  # 2 requerimientos / 4 avanzadas


# ──────────────────────────────────────────────────────────────────────────
# Cache TTL en memoria
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_cache_evita_streams_repetidos(client, fake_db, monkeypatch):
    calls_avanzadas = _spy_stream_calls(monkeypatch, "avanzadas")
    calls_requerimientos = _spy_stream_calls(monkeypatch, "avanzadas_requerimientos")

    r1 = client.get("/avanzadas/estadisticas")
    r2 = client.get("/avanzadas/estadisticas")
    r3 = client.get("/avanzadas/estadisticas")

    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert calls_avanzadas["stream"] == 1
    assert calls_requerimientos["stream"] == 1


def test_estadisticas_cache_expira_por_ttl(client, fake_db, monkeypatch):
    calls_avanzadas = _spy_stream_calls(monkeypatch, "avanzadas")

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(avanzadas_routes.time, "monotonic", lambda: fake_now["t"])

    client.get("/avanzadas/estadisticas")
    assert calls_avanzadas["stream"] == 1

    fake_now["t"] += avanzadas_routes._AVANZADAS_ESTADISTICAS_TTL_SECONDS - 1
    client.get("/avanzadas/estadisticas")
    assert calls_avanzadas["stream"] == 1

    fake_now["t"] += 2
    client.get("/avanzadas/estadisticas")
    assert calls_avanzadas["stream"] == 2


def test_estadisticas_cache_se_invalida_al_crear_avanzada_nueva(client, fake_db, monkeypatch):
    calls_avanzadas = _spy_stream_calls(monkeypatch, "avanzadas")

    primera = client.get("/avanzadas/estadisticas").json()
    assert calls_avanzadas["stream"] == 1
    assert primera["totales"]["avanzadas"] == 0

    response = _post_avanzada(client, _valid_datos(client_id="cid-nueva"))
    assert response.status_code == 201

    segunda = client.get("/avanzadas/estadisticas").json()
    assert calls_avanzadas["stream"] == 2
    assert segunda["totales"]["avanzadas"] == 1
    assert segunda["totales"]["requerimientos"] == 1


def test_estadisticas_cache_no_se_invalida_en_creacion_idempotente(client, fake_db, monkeypatch):
    datos = _valid_datos(client_id="cid-idem")
    _post_avanzada(client, datos)

    calls_avanzadas = _spy_stream_calls(monkeypatch, "avanzadas")
    client.get("/avanzadas/estadisticas")
    assert calls_avanzadas["stream"] == 1

    # Reintento con el mismo client_id -> rama idempotente (200), no debe
    # invalidar el cache de estadísticas.
    repetida = _post_avanzada(client, datos)
    assert repetida.status_code == 200

    client.get("/avanzadas/estadisticas")
    assert calls_avanzadas["stream"] == 1


def test_estadisticas_cache_getter_no_permite_aliasing(client, fake_db):
    """Llama al getter interno dos veces y muta el resultado de la
    primera llamada; la segunda debe seguir devolviendo datos prístinos
    (el cache no puede quedar corrompido por un caller que muta el
    dict/objeto recibido).
    """
    _set_avanzada(fake_db, "cid-1", comuna="COMUNA 03")
    _set_requerimiento(fake_db, "req-1", avanzada_client_id="cid-1")

    primera = avanzadas_routes._obtener_estadisticas_cacheado()
    primera["totales"]["avanzadas"] = 999
    primera["por_comuna"].append({"comuna": "FANTASMA", "avanzadas": 1, "requerimientos": 1})

    segunda = avanzadas_routes._obtener_estadisticas_cacheado()
    assert segunda["totales"]["avanzadas"] == 1
    assert all(c["comuna"] != "FANTASMA" for c in segunda["por_comuna"])


# ──────────────────────────────────────────────────────────────────────────
# End-to-end realista: POST real -> GET estadísticas
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_end_to_end_via_post_real(client):
    datos_1 = _valid_datos(client_id="cid-e2e-1", comuna="COMUNA 03", fecha="2026-01-10")
    datos_1["requerimientos"] = [
        {
            "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
            "categoria": "Poda de árboles (autorización)",
            "categoria_personalizada": None,
            "requerimiento": "Árbol caído",
            "ubicacion": "Parque central",
            "coordenadas": "3.45, -76.53",
        },
        {
            "entidad": "EMCALI - Empresas Municipales de Cali",
            "categoria": "Fuga de agua",
            "categoria_personalizada": None,
            "requerimiento": "Fuga en la calle",
            "ubicacion": "Calle 10",
            "coordenadas": "3.46, -76.54",
        },
    ]
    r1 = _post_avanzada(client, datos_1)
    assert r1.status_code == 201

    datos_2 = _valid_datos(client_id="cid-e2e-2", comuna="COMUNA 03", fecha="2026-01-20")
    datos_2["requerimientos"] = [
        {
            "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
            "categoria": "Poda de árboles (autorización)",
            "categoria_personalizada": None,
            "requerimiento": "Rama peligrosa",
            "ubicacion": "Av. principal",
            "coordenadas": "3.47, -76.55",
        },
    ]
    r2 = _post_avanzada(client, datos_2)
    assert r2.status_code == 201

    body = client.get("/avanzadas/estadisticas").json()

    assert body["totales"]["avanzadas"] == 2
    assert body["totales"]["requerimientos"] == 3
    assert body["totales"]["comunas"] == 1
    assert body["totales"]["entidades"] == 2
    assert body["totales"]["promedio_requerimientos"] == 1.5

    por_entidad = {e["sigla"]: e["total"] for e in body["por_entidad"]}
    assert por_entidad["DAGMA"] == 2
    assert por_entidad["EMCALI"] == 1

    comuna_03 = next(c for c in body["por_comuna"] if c["comuna"] == "COMUNA 03")
    assert comuna_03["avanzadas"] == 2
    assert comuna_03["requerimientos"] == 3

    meses = [m["mes"] for m in body["por_mes"]]
    assert meses == ["2026-01"]
    assert body["por_mes"][0]["avanzadas"] == 2
    assert body["por_mes"][0]["requerimientos"] == 3
