"""
Tests de ``GET /jornadas/estadisticas``.

Cubre las agregaciones server-side sobre las colecciones migradas de
Jornadas Integrales (jornadas_integrales, jornadas_compromisos,
jornadas_seguimientos, jornadas_encuestas): totales, cumplimiento,
compromisos por organismo/verificación, seguimientos por estado,
encuestas por organismo (parseo defensivo de ``evaluaciones``), jornadas
por comuna, listado de jornadas, orden determinista, cache TTL en
memoria (mismo patrón que ``/avanzadas/estadisticas``) y el caso de base
de datos vacía.

Este módulo tiene su propio set de fixtures (no hay ``conftest.py``
compartido en el proyecto), siguiendo el mismo estilo que
``test_avanzadas_estadisticas.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_system.dependencies import get_current_user
from app.routes import jornadas_routes
from tests.fakes_firestore import FakeFirestore


# ──────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────

_FAKE_USER = {"uid": "tester-uid", "email": "tester@catatrack.test"}


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr(jornadas_routes, "db", db)
    return db


@pytest.fixture(autouse=True)
def _reset_cache():
    jornadas_routes._jornadas_estadisticas_cache = None
    yield
    jornadas_routes._jornadas_estadisticas_cache = None


@pytest.fixture()
def client(fake_db):
    app = FastAPI()
    app.include_router(jornadas_routes.router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    return TestClient(app)


@pytest.fixture()
def unauthenticated_client(fake_db):
    app = FastAPI()
    app.include_router(jornadas_routes.router)
    return TestClient(app)


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


def _set_jornada(fake_db, doc_id: str, **campos) -> dict:
    data = {
        "numero": 1,
        "fecha": "2026-01-01",
        "nombre_jornada": "Jornada de prueba",
        "comuna": "COMUNA 01",
        "barrio": "Barrio X",
        "estado": "finalizada",
        "asistencia_aproximada": 10,
        "coordenadas_encuentro": "3.47, -76.55",
        "creado": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "actualizado": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    data.update(campos)
    fake_db.collection("jornadas_integrales").document(doc_id).set(data)
    return data


def _set_compromiso(fake_db, doc_id: str, jornada_client_id: str, **campos) -> dict:
    data = {
        "jornada_client_id": jornada_client_id,
        "nombre_jornada": "Jornada de prueba",
        "organismo": "DAGMA",
        "oferta_servicio": "Servicio X",
        "tipo": "cualitativo",
        "compromiso": "Compromiso de prueba",
        "estado_verificacion_campo": "cumple",
        "creado": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    data.update(campos)
    fake_db.collection("jornadas_compromisos").document(doc_id).set(data)
    return data


def _set_seguimiento(fake_db, doc_id: str, compromiso_client_id: str, jornada_client_id: str, **campos) -> dict:
    data = {
        "compromiso_client_id": compromiso_client_id,
        "jornada_client_id": jornada_client_id,
        "fecha_seguimiento": "2026-01-10",
        "estado": "ok",
        "responsable_seguimiento": "Fulano",
        "creado": datetime(2026, 1, 10, tzinfo=timezone.utc),
    }
    data.update(campos)
    fake_db.collection("jornadas_seguimientos").document(doc_id).set(data)
    return data


def _set_encuesta(fake_db, doc_id: str, jornada_client_id: str, **campos) -> dict:
    data = {
        "jornada_client_id": jornada_client_id,
        "nombre_participante": "Participante",
        "comuna": "COMUNA 01",
        "barrio": "Barrio X",
        "evaluaciones": [{"org": "UAESP", "calif": "Bueno"}],
        "creado": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    data.update(campos)
    fake_db.collection("jornadas_encuestas").document(doc_id).set(data)
    return data


# ──────────────────────────────────────────────────────────────────────────
# Autenticación
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_requiere_autenticacion(unauthenticated_client):
    response = unauthenticated_client.get("/jornadas/estadisticas")
    assert response.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# Caso vacío
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_db_vacia(client):
    response = client.get("/jornadas/estadisticas")
    assert response.status_code == 200
    body = response.json()

    assert body["totales"] == {
        "jornadas": 0,
        "compromisos": 0,
        "seguimientos": 0,
        "encuestas": 0,
        "asistencia_total": 0,
        "cumplimiento_pct": 0.0,
    }
    assert body["compromisos_por_organismo"] == []
    assert body["compromisos_por_verificacion"] == []
    assert body["seguimientos_por_estado"] == []
    assert body["encuestas_por_organismo"] == []
    assert body["jornadas_por_comuna"] == []
    assert body["jornadas_lista"] == []


# ──────────────────────────────────────────────────────────────────────────
# Totales / cumplimiento
# ──────────────────────────────────────────────────────────────────────────

def test_totales_cuenta_documentos_y_asistencia(client, fake_db):
    _set_jornada(fake_db, "jor-1", asistencia_aproximada=10)
    _set_jornada(fake_db, "jor-2", asistencia_aproximada=25)
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1")
    _set_seguimiento(fake_db, "seg-1", compromiso_client_id="com-1", jornada_client_id="jor-1")
    _set_encuesta(fake_db, "enc-1", jornada_client_id="jor-1")

    body = client.get("/jornadas/estadisticas").json()
    totales = body["totales"]
    assert totales["jornadas"] == 2
    assert totales["compromisos"] == 1
    assert totales["seguimientos"] == 1
    assert totales["encuestas"] == 1
    assert totales["asistencia_total"] == 35


def test_totales_asistencia_no_entera_se_trata_como_cero(client, fake_db):
    _set_jornada(fake_db, "jor-1", asistencia_aproximada="no-es-numero")
    _set_jornada(fake_db, "jor-2", asistencia_aproximada=None)
    _set_jornada(fake_db, "jor-3", asistencia_aproximada=5)

    body = client.get("/jornadas/estadisticas").json()
    assert body["totales"]["asistencia_total"] == 5


def test_cumplimiento_pct_calculado_sobre_total_compromisos(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1", estado_verificacion_campo="cumple")
    _set_compromiso(fake_db, "com-2", jornada_client_id="jor-1", estado_verificacion_campo="cumple")
    _set_compromiso(fake_db, "com-3", jornada_client_id="jor-1", estado_verificacion_campo="no-cumple")
    _set_compromiso(fake_db, "com-4", jornada_client_id="jor-1", estado_verificacion_campo="novedad")

    body = client.get("/jornadas/estadisticas").json()
    # 2 de 4 cumplen -> 50.0%
    assert body["totales"]["cumplimiento_pct"] == 50.0


def test_cumplimiento_pct_redondea_a_un_decimal(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1", estado_verificacion_campo="cumple")
    _set_compromiso(fake_db, "com-2", jornada_client_id="jor-1", estado_verificacion_campo="no-cumple")
    _set_compromiso(fake_db, "com-3", jornada_client_id="jor-1", estado_verificacion_campo="no-cumple")

    body = client.get("/jornadas/estadisticas").json()
    # 1 de 3 -> 33.333...% -> redondeado a 33.3
    assert body["totales"]["cumplimiento_pct"] == 33.3


def test_cumplimiento_pct_cero_sin_compromisos(client, fake_db):
    _set_jornada(fake_db, "jor-1")

    body = client.get("/jornadas/estadisticas").json()
    assert body["totales"]["cumplimiento_pct"] == 0.0


# ──────────────────────────────────────────────────────────────────────────
# compromisos_por_organismo
# ──────────────────────────────────────────────────────────────────────────

def test_compromisos_por_organismo_cuenta_estados(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1", organismo="DAGMA", estado_verificacion_campo="cumple")
    _set_compromiso(fake_db, "com-2", jornada_client_id="jor-1", organismo="DAGMA", estado_verificacion_campo="no-cumple")
    _set_compromiso(fake_db, "com-3", jornada_client_id="jor-1", organismo="DAGMA", estado_verificacion_campo="novedad")
    _set_compromiso(fake_db, "com-4", jornada_client_id="jor-1", organismo="EMCALI", estado_verificacion_campo="cumple")

    body = client.get("/jornadas/estadisticas").json()
    por_organismo = {o["organismo"]: o for o in body["compromisos_por_organismo"]}

    assert por_organismo["DAGMA"] == {
        "organismo": "DAGMA", "total": 3, "cumple": 1, "no_cumple": 1, "novedad": 1,
    }
    assert por_organismo["EMCALI"] == {
        "organismo": "EMCALI", "total": 1, "cumple": 1, "no_cumple": 0, "novedad": 0,
    }


def test_compromisos_por_organismo_orden_total_desc_organismo_asc(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    # ZZZ y AAA empatan en total (1 c/u) -> tie-break por organismo ASC.
    _set_compromiso(fake_db, "com-z", jornada_client_id="jor-1", organismo="ZZZ")
    _set_compromiso(fake_db, "com-a", jornada_client_id="jor-1", organismo="AAA")
    _set_compromiso(fake_db, "com-b1", jornada_client_id="jor-1", organismo="BBB")
    _set_compromiso(fake_db, "com-b2", jornada_client_id="jor-1", organismo="BBB")

    body = client.get("/jornadas/estadisticas").json()
    organismos = [o["organismo"] for o in body["compromisos_por_organismo"]]
    assert organismos == ["BBB", "AAA", "ZZZ"]


def test_compromisos_por_organismo_faltante_se_agrupa_como_sin_organismo(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1", organismo=None)
    _set_compromiso(fake_db, "com-2", jornada_client_id="jor-1", organismo="   ")

    body = client.get("/jornadas/estadisticas").json()
    organismos = [o["organismo"] for o in body["compromisos_por_organismo"]]
    assert organismos == ["Sin organismo"]
    assert body["compromisos_por_organismo"][0]["total"] == 2


# ──────────────────────────────────────────────────────────────────────────
# compromisos_por_verificacion
# ──────────────────────────────────────────────────────────────────────────

def test_compromisos_por_verificacion_buckets(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1", estado_verificacion_campo="cumple")
    _set_compromiso(fake_db, "com-2", jornada_client_id="jor-1", estado_verificacion_campo="cumple")
    _set_compromiso(fake_db, "com-3", jornada_client_id="jor-1", estado_verificacion_campo="no-cumple")
    _set_compromiso(fake_db, "com-4", jornada_client_id="jor-1", estado_verificacion_campo=None)

    body = client.get("/jornadas/estadisticas").json()
    por_estado = {e["estado"]: e["total"] for e in body["compromisos_por_verificacion"]}
    assert por_estado == {"cumple": 2, "no-cumple": 1, "sin_verificar": 1}
    # Invariante: la suma de los buckets = total de compromisos.
    assert sum(por_estado.values()) == 4


def test_compromisos_por_verificacion_no_crashea_con_valores_no_string(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1", estado_verificacion_campo=123)

    response = client.get("/jornadas/estadisticas")
    assert response.status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# seguimientos_por_estado
# ──────────────────────────────────────────────────────────────────────────

def test_seguimientos_por_estado_buckets(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_seguimiento(fake_db, "seg-1", compromiso_client_id="com-1", jornada_client_id="jor-1", estado="ok")
    _set_seguimiento(fake_db, "seg-2", compromiso_client_id="com-1", jornada_client_id="jor-1", estado="ok")
    _set_seguimiento(fake_db, "seg-3", compromiso_client_id="com-1", jornada_client_id="jor-1", estado="novedad")
    _set_seguimiento(fake_db, "seg-4", compromiso_client_id="com-1", jornada_client_id="jor-1", estado="cancelado")

    body = client.get("/jornadas/estadisticas").json()
    por_estado = {e["estado"]: e["total"] for e in body["seguimientos_por_estado"]}
    assert por_estado == {"ok": 2, "novedad": 1, "cancelado": 1}


def test_seguimientos_por_estado_faltante_se_agrupa_sin_estado(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_seguimiento(fake_db, "seg-1", compromiso_client_id="com-1", jornada_client_id="jor-1", estado=None)

    body = client.get("/jornadas/estadisticas").json()
    por_estado = {e["estado"]: e["total"] for e in body["seguimientos_por_estado"]}
    assert por_estado == {"sin_estado": 1}


# ──────────────────────────────────────────────────────────────────────────
# encuestas_por_organismo (parseo defensivo de 'evaluaciones')
# ──────────────────────────────────────────────────────────────────────────

def test_encuestas_por_organismo_bucketiza_calificaciones(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_encuesta(fake_db, "enc-1", jornada_client_id="jor-1", evaluaciones=[
        {"org": "UAESP", "calif": "Bueno"},
        {"org": "UAESP", "calif": "bueno"},
        {"org": "UAESP", "calif": "Regular"},
        {"org": "UAESP", "calif": "Malo"},
        {"org": "UAESP", "calif": "N/A"},
    ])

    body = client.get("/jornadas/estadisticas").json()
    uaesp = next(o for o in body["encuestas_por_organismo"] if o["org"] == "UAESP")
    assert uaesp == {"org": "UAESP", "bueno": 2, "regular": 1, "malo": 1, "na": 1, "total": 5}


def test_encuestas_por_organismo_evaluaciones_no_es_lista_no_crashea(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_encuesta(fake_db, "enc-1", jornada_client_id="jor-1", evaluaciones="no-es-una-lista")
    _set_encuesta(fake_db, "enc-2", jornada_client_id="jor-1", evaluaciones=None)

    response = client.get("/jornadas/estadisticas")
    assert response.status_code == 200
    assert response.json()["encuestas_por_organismo"] == []


def test_encuestas_por_organismo_items_malformados_se_ignoran(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_encuesta(fake_db, "enc-1", jornada_client_id="jor-1", evaluaciones=[
        "no-es-un-dict",
        123,
        None,
        {"org": "UAESP"},  # falta 'calif'
        {"calif": "Bueno"},  # falta 'org'
        {"org": "UAESP", "calif": "Bueno"},  # válido
        {"org": "UAESP", "calif": "Excelente"},  # calif desconocida -> se ignora
    ])

    body = client.get("/jornadas/estadisticas").json()
    uaesp = next(o for o in body["encuestas_por_organismo"] if o["org"] == "UAESP")
    assert uaesp["total"] == 1
    assert uaesp["bueno"] == 1


def test_encuestas_por_organismo_orden_total_desc_org_asc(client, fake_db):
    _set_jornada(fake_db, "jor-1")
    _set_encuesta(fake_db, "enc-1", jornada_client_id="jor-1", evaluaciones=[
        {"org": "ZZZ", "calif": "Bueno"},
        {"org": "AAA", "calif": "Bueno"},
    ])

    body = client.get("/jornadas/estadisticas").json()
    orgs = [o["org"] for o in body["encuestas_por_organismo"]]
    assert orgs == ["AAA", "ZZZ"]


# ──────────────────────────────────────────────────────────────────────────
# jornadas_por_comuna
# ──────────────────────────────────────────────────────────────────────────

def test_jornadas_por_comuna_cuenta_jornadas_y_compromisos(client, fake_db):
    _set_jornada(fake_db, "jor-1", comuna="COMUNA 03")
    _set_jornada(fake_db, "jor-2", comuna="COMUNA 03")
    _set_jornada(fake_db, "jor-3", comuna="COMUNA 05")
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1")
    _set_compromiso(fake_db, "com-2", jornada_client_id="jor-1")
    _set_compromiso(fake_db, "com-3", jornada_client_id="jor-3")

    body = client.get("/jornadas/estadisticas").json()
    por_comuna = {c["comuna"]: c for c in body["jornadas_por_comuna"]}
    assert por_comuna["COMUNA 03"] == {"comuna": "COMUNA 03", "jornadas": 2, "compromisos": 2}
    assert por_comuna["COMUNA 05"] == {"comuna": "COMUNA 05", "jornadas": 1, "compromisos": 1}


def test_jornadas_por_comuna_compromiso_huerfano_no_rompe_y_no_cuenta(client, fake_db):
    _set_jornada(fake_db, "jor-1", comuna="COMUNA 03")
    _set_compromiso(fake_db, "com-huerfano", jornada_client_id="no-existe")

    response = client.get("/jornadas/estadisticas")
    assert response.status_code == 200
    body = response.json()
    comuna_03 = next(c for c in body["jornadas_por_comuna"] if c["comuna"] == "COMUNA 03")
    assert comuna_03["compromisos"] == 0


# ──────────────────────────────────────────────────────────────────────────
# jornadas_lista
# ──────────────────────────────────────────────────────────────────────────

def test_jornadas_lista_incluye_compromisos_count_y_campos(client, fake_db):
    _set_jornada(
        fake_db, "jor-1",
        nombre_jornada="Jornada Comuna 3",
        fecha="2026-01-15",
        comuna="COMUNA 03",
        barrio="San Antonio",
        estado="finalizada",
        asistencia_aproximada=42,
    )
    _set_compromiso(fake_db, "com-1", jornada_client_id="jor-1")
    _set_compromiso(fake_db, "com-2", jornada_client_id="jor-1")

    body = client.get("/jornadas/estadisticas").json()
    item = body["jornadas_lista"][0]
    assert item == {
        "client_id": "jor-1",
        "nombre_jornada": "Jornada Comuna 3",
        "fecha": "2026-01-15",
        "comuna": "COMUNA 03",
        "barrio": "San Antonio",
        "estado": "finalizada",
        "asistencia_aproximada": 42,
        "compromisos_count": 2,
    }


def test_jornadas_lista_orden_fecha_desc_con_tiebreak_client_id(client, fake_db):
    _set_jornada(fake_db, "jor-b", fecha="2026-01-10")
    _set_jornada(fake_db, "jor-a", fecha="2026-01-10")
    _set_jornada(fake_db, "jor-mas-reciente", fecha="2026-02-01")

    body = client.get("/jornadas/estadisticas").json()
    ids = [j["client_id"] for j in body["jornadas_lista"]]
    assert ids == ["jor-mas-reciente", "jor-a", "jor-b"]


# ──────────────────────────────────────────────────────────────────────────
# Cache TTL en memoria
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_cache_evita_streams_repetidos(client, fake_db, monkeypatch):
    calls_jornadas = _spy_stream_calls(monkeypatch, "jornadas_integrales")
    calls_compromisos = _spy_stream_calls(monkeypatch, "jornadas_compromisos")

    r1 = client.get("/jornadas/estadisticas")
    r2 = client.get("/jornadas/estadisticas")
    r3 = client.get("/jornadas/estadisticas")

    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert calls_jornadas["stream"] == 1
    assert calls_compromisos["stream"] == 1


def test_estadisticas_cache_expira_por_ttl(client, fake_db, monkeypatch):
    calls_jornadas = _spy_stream_calls(monkeypatch, "jornadas_integrales")

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(jornadas_routes.time, "monotonic", lambda: fake_now["t"])

    client.get("/jornadas/estadisticas")
    assert calls_jornadas["stream"] == 1

    fake_now["t"] += jornadas_routes.JORNADAS_ESTADISTICAS_TTL_SECONDS - 1
    client.get("/jornadas/estadisticas")
    assert calls_jornadas["stream"] == 1

    fake_now["t"] += 2
    client.get("/jornadas/estadisticas")
    assert calls_jornadas["stream"] == 2


def test_estadisticas_cache_invalidacion_manual_fuerza_recalculo(client, fake_db, monkeypatch):
    calls_jornadas = _spy_stream_calls(monkeypatch, "jornadas_integrales")

    client.get("/jornadas/estadisticas")
    assert calls_jornadas["stream"] == 1

    jornadas_routes._invalidar_cache_estadisticas_jornadas()

    client.get("/jornadas/estadisticas")
    assert calls_jornadas["stream"] == 2


def test_estadisticas_cache_getter_no_permite_aliasing(client, fake_db):
    _set_jornada(fake_db, "jor-1", comuna="COMUNA 03")

    primera = jornadas_routes._obtener_estadisticas_jornadas_cacheado()
    primera["totales"]["jornadas"] = 999
    primera["jornadas_por_comuna"].append({"comuna": "FANTASMA", "jornadas": 1, "compromisos": 1})

    segunda = jornadas_routes._obtener_estadisticas_jornadas_cacheado()
    assert segunda["totales"]["jornadas"] == 1
    assert all(c["comuna"] != "FANTASMA" for c in segunda["jornadas_por_comuna"])


# ──────────────────────────────────────────────────────────────────────────
# OpenAPI: la ruta debe quedar registrada en la app real
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_route_aparece_en_openapi_schema():
    from app.main import app as real_app

    schema = real_app.openapi()
    assert "/jornadas/estadisticas" in schema["paths"]
