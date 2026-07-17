"""
Tests de la Parte 2 del feature de Jornadas Integrales: los
requerimientos originados en una jornada se guardan en la MISMA
colección compartida ``avanzadas_requerimientos`` que usa Avanzadas
Diagnósticas (no una colección nueva), marcados con
``origen='jornada'`` y ``jornada_client_id``.

Cubre:
- Back-compat: un doc SIN el campo ``origen`` (los 326 preexistentes de
  la migración) se trata como ``origen == 'avanzada'``.
- ``POST /jornadas/{client_id}/requerimientos`` escribe en la colección
  compartida con los campos correctos y reutiliza el upsert de
  categorías personalizadas (aparecen en ``/avanzadas/catalogos``).
- ``/avanzadas/estadisticas``: por_entidad, por_categoria y
  totales.requerimientos cuentan AMBOS orígenes; por_comuna hace join
  con jornadas_integrales para el origen 'jornada'; por_estrategia
  sigue siendo exclusivo de avanzadas.
- ``/avanzadas/geo``: el arreglo de requerimientos incluye ambos
  orígenes con un campo ``origen`` explícito, y sigue omitiendo
  huérfanos (contra avanzada O jornada según corresponda).
- ``GET /avanzadas/{client_id}`` NUNCA expone requerimientos de origen
  'jornada' (no-leakage).

Este módulo tiene su propio set de fixtures (no hay conftest.py
compartido en el proyecto).
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_system.dependencies import get_current_user
from app.routes import avanzadas_routes, jornadas_routes
from tests.fakes_firestore import FakeFirestore, FakeS3Client


_FAKE_USER = {"uid": "tester-uid", "email": "tester@catatrack.test"}


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr(avanzadas_routes, "db", db)
    monkeypatch.setattr(jornadas_routes, "db", db)
    return db


@pytest.fixture()
def fake_s3(monkeypatch):
    s3 = FakeS3Client()
    monkeypatch.setattr(avanzadas_routes, "get_s3_client", lambda: s3)
    return s3


@pytest.fixture(autouse=True)
def _reset_caches():
    avanzadas_routes._catalogos_cache = None
    avanzadas_routes._estadisticas_cache = None
    avanzadas_routes._geo_cache = None
    jornadas_routes._jornadas_estadisticas_cache = None
    yield
    avanzadas_routes._catalogos_cache = None
    avanzadas_routes._estadisticas_cache = None
    avanzadas_routes._geo_cache = None
    jornadas_routes._jornadas_estadisticas_cache = None


@pytest.fixture()
def client(fake_db, fake_s3):
    app = FastAPI()
    app.include_router(avanzadas_routes.router)
    app.include_router(jornadas_routes.router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _set_avanzada(fake_db, doc_id: str, **campos) -> dict:
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


def _set_requerimiento(fake_db, doc_id: str, **campos) -> dict:
    data = {
        "avanzada_client_id": None,
        "req_index": 0,
        "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
        "categoria": "Poda de árboles (autorización)",
        "categoria_personalizada": None,
        "requerimiento": "Requerimiento de prueba",
        "ubicacion": "Ubicación de prueba",
        "coordenadas": "3.46, -76.54",
        "fotos_urls": [],
        "fecha": "2026-01-01",
        "nombre_avanzada": "Avanzada de prueba",
        "estrategia": "En Un 2x3",
        "created_at": "2026-01-01T00:00:00-05:00",
    }
    data.update(campos)
    fake_db.collection("avanzadas_requerimientos").document(doc_id).set(data)
    return data


def _set_jornada(fake_db, doc_id: str, **campos) -> dict:
    data = {
        "numero": 1,
        "fecha": "2026-01-01",
        "nombre_jornada": "Jornada de prueba",
        "comuna": "COMUNA 02",
        "barrio": "Barrio X",
        "estado": "planificacion",
        "coordenadas_encuentro": "3.47, -76.55",
    }
    data.update(campos)
    fake_db.collection("jornadas_integrales").document(doc_id).set(data)
    return data


def _crear_jornada_http(client, client_id="jor_001", **overrides):
    datos = {
        "client_id": client_id,
        "nombre_jornada": "Jornada HTTP",
        "fecha": "2026-02-01",
        "punto_encuentro": "Cancha",
        "direccion_punto_encuentro": "Calle 1",
        "coordenadas_encuentro": "3.47, -76.55",
        "comuna": "COMUNA 02",
        "barrio": "Barrio X",
    }
    datos.update(overrides)
    response = client.post("/jornadas", json=datos)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _post_requerimientos_jornada(client, jornada_client_id, requerimientos, files=None):
    datos = {"requerimientos": requerimientos}
    return client.post(
        f"/jornadas/{jornada_client_id}/requerimientos",
        data={"datos": json.dumps(datos)},
        files=files or [],
    )


# ──────────────────────────────────────────────────────────────────────────
# Back-compat: origen ausente == 'avanzada'
# ──────────────────────────────────────────────────────────────────────────

def test_requerimiento_sin_campo_origen_se_trata_como_avanzada(client, fake_db):
    _set_avanzada(fake_db, "cid-legacy", comuna="COMUNA 03")
    # Doc "legacy": exactamente como quedaron los 326 migrados, SIN el
    # campo 'origen' en absoluto.
    _set_requerimiento(fake_db, "req-legacy", avanzada_client_id="cid-legacy", entidad="DAGMA - Depto")
    assert "origen" not in fake_db.collection("avanzadas_requerimientos").document("req-legacy").get().to_dict()

    body = client.get("/avanzadas/estadisticas").json()
    assert body["totales"]["requerimientos"] == 1
    comuna_03 = next(c for c in body["por_comuna"] if c["comuna"] == "COMUNA 03")
    assert comuna_03["requerimientos"] == 1

    geo = client.get("/avanzadas/geo").json()
    assert len(geo["requerimientos"]) == 1
    assert geo["requerimientos"][0]["origen"] == "avanzada"


# ──────────────────────────────────────────────────────────────────────────
# POST /jornadas/{client_id}/requerimientos
# ──────────────────────────────────────────────────────────────────────────

def test_crear_requerimientos_jornada_persiste_en_coleccion_compartida(client, fake_db):
    _crear_jornada_http(client, client_id="jor_req")

    response = _post_requerimientos_jornada(client, "jor_req", [
        {
            "entidad": "EMCALI - Empresas Municipales de Cali",
            "categoria": "Fuga de agua",
            "categoria_personalizada": None,
            "requerimiento": "Fuga en la calle",
            "ubicacion": "Calle 10",
            "coordenadas": "3.48, -76.56",
        },
    ])
    assert response.status_code == 201
    body = response.json()
    assert len(body["requerimientos"]) == 1
    creado = body["requerimientos"][0]
    assert creado["jornada_client_id"] == "jor_req"
    assert creado["origen"] == "jornada"
    assert creado["avanzada_client_id"] is None
    assert creado["nombre_origen"] == "Jornada HTTP"
    assert creado["estrategia"] is None

    doc = fake_db.collection("avanzadas_requerimientos").document("jor_req_0").get()
    assert doc.exists
    assert doc.to_dict()["origen"] == "jornada"


def test_crear_requerimientos_jornada_sube_fotos_a_s3(client, fake_s3):
    _crear_jornada_http(client, client_id="jor_req_fotos")
    files = [
        ("fotos_req_0", ("foto1.jpg", b"bytes1", "image/jpeg")),
        ("fotos_req_0", ("foto2.jpg", b"bytes2", "image/jpeg")),
    ]
    response = _post_requerimientos_jornada(client, "jor_req_fotos", [
        {
            "entidad": "DAGMA - Depto",
            "requerimiento": "Árbol caído",
            "ubicacion": "Parque",
        },
    ], files=files)
    assert response.status_code == 201
    assert len(response.json()["requerimientos"][0]["fotos_urls"]) == 2
    assert len(fake_s3.uploaded) == 2


def test_crear_requerimientos_jornada_continua_numeracion_incremental(client, fake_db):
    _crear_jornada_http(client, client_id="jor_incremental")
    _post_requerimientos_jornada(client, "jor_incremental", [
        {"entidad": "DAGMA - Depto", "requerimiento": "Req 1", "ubicacion": "U1"},
    ])
    r2 = _post_requerimientos_jornada(client, "jor_incremental", [
        {"entidad": "DAGMA - Depto", "requerimiento": "Req 2", "ubicacion": "U2"},
    ])
    assert r2.status_code == 201
    assert r2.json()["requerimientos"][0]["req_index"] == 1

    ids = sorted(d.id for d in fake_db.collection("avanzadas_requerimientos").stream())
    assert ids == ["jor_incremental_0", "jor_incremental_1"]


def test_crear_requerimientos_jornada_no_colisiona_tras_borrar_indice_intermedio(client, fake_db):
    """Invariante de la Decisión de diseño #5, aplicada también del lado
    de Jornadas Integrales (ver Open Question de design.md): el próximo
    ``req_index`` debe ser ``max(existentes) + 1``, no ``len(existentes)``.
    Secuencia: idx0, idx1, idx2 -> se borra el idx1 INTERMEDIO (queda
    [0, 2], len=2 pero max=2) -> el próximo:
    - con len(): asignaría 2 -> COLISIONA con el idx2 que sigue vivo
      (pisaría su documento).
    - con max()+1: asigna 3 -> sin colisión.

    No existe todavía un endpoint DELETE de requerimiento individual del
    lado de Jornadas, así que el borrado del índice intermedio se simula
    manipulando directamente el fake_db (mismo criterio que el resto de
    los tests de este módulo).
    """
    _crear_jornada_http(client, client_id="jor_maxplus1")
    _post_requerimientos_jornada(client, "jor_maxplus1", [
        {"entidad": "DAGMA - Depto", "requerimiento": "Req 0", "ubicacion": "U0"},
    ])
    _post_requerimientos_jornada(client, "jor_maxplus1", [
        {"entidad": "DAGMA - Depto", "requerimiento": "Req 1", "ubicacion": "U1"},
    ])
    r3 = _post_requerimientos_jornada(client, "jor_maxplus1", [
        {"entidad": "DAGMA - Depto", "requerimiento": "Req 2", "ubicacion": "U2"},
    ])
    assert r3.json()["requerimientos"][0]["req_index"] == 2

    fake_db.collection("avanzadas_requerimientos").document("jor_maxplus1_1").delete()

    r4 = _post_requerimientos_jornada(client, "jor_maxplus1", [
        {"entidad": "DAGMA - Depto", "requerimiento": "Req 3", "ubicacion": "U3"},
    ])
    assert r4.status_code == 201
    creado = r4.json()["requerimientos"][0]
    assert creado["req_index"] == 3
    assert creado["id"] == "jor_maxplus1_3"

    # El idx2 preexistente sigue intacto -- no fue pisado por una colisión.
    ids = sorted(d.id for d in fake_db.collection("avanzadas_requerimientos").stream())
    assert ids == ["jor_maxplus1_0", "jor_maxplus1_2", "jor_maxplus1_3"]


def test_crear_requerimientos_jornada_upsert_categoria_personalizada(client, fake_db):
    _crear_jornada_http(client, client_id="jor_cat")
    response = _post_requerimientos_jornada(client, "jor_cat", [
        {
            "entidad": "DAGMA - Departamento Administrativo de Gestión del Medio Ambiente",
            "categoria_personalizada": "Categoría inventada en jornada",
            "requerimiento": "Req custom",
            "ubicacion": "U",
        },
    ])
    assert response.status_code == 201

    catalogos = client.get("/avanzadas/catalogos").json()
    assert "Categoría inventada en jornada" in catalogos["categorias"]["DAGMA"]


def test_crear_requerimientos_jornada_no_encontrada(client):
    response = _post_requerimientos_jornada(client, "no-existe", [
        {"entidad": "DAGMA - Depto", "requerimiento": "Req", "ubicacion": "U"},
    ])
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# /avanzadas/estadisticas -- ambos orígenes
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_por_entidad_y_categoria_cuentan_ambos_origenes(client, fake_db):
    _set_avanzada(fake_db, "cid-1")
    _set_requerimiento(
        fake_db, "req-avz", avanzada_client_id="cid-1", origen="avanzada",
        entidad="DAGMA - Depto", categoria="Poda", categoria_personalizada=None,
    )
    _set_jornada(fake_db, "jor-1")
    _set_requerimiento(
        fake_db, "req-jor", jornada_client_id="jor-1", avanzada_client_id=None, origen="jornada",
        entidad="DAGMA - Depto", categoria="Poda", categoria_personalizada=None,
    )

    body = client.get("/avanzadas/estadisticas").json()
    assert body["totales"]["requerimientos"] == 2

    dagma = next(e for e in body["por_entidad"] if e["sigla"] == "DAGMA")
    assert dagma["total"] == 2

    poda = next(c for c in body["por_categoria"] if c["categoria"] == "Poda")
    assert poda["total"] == 2


def test_estadisticas_por_comuna_hace_join_con_jornada_para_origen_jornada(client, fake_db):
    _set_jornada(fake_db, "jor-comuna", comuna="COMUNA 09")
    _set_requerimiento(
        fake_db, "req-jor-comuna", jornada_client_id="jor-comuna", avanzada_client_id=None, origen="jornada",
    )

    body = client.get("/avanzadas/estadisticas").json()
    comuna_09 = next(c for c in body["por_comuna"] if c["comuna"] == "COMUNA 09")
    assert comuna_09["requerimientos"] == 1


def test_estadisticas_por_comuna_requerimiento_jornada_huerfano_no_cuenta(client, fake_db):
    _set_requerimiento(
        fake_db, "req-jor-huerfano", jornada_client_id="no-existe", avanzada_client_id=None, origen="jornada",
    )

    response = client.get("/avanzadas/estadisticas")
    assert response.status_code == 200
    body = response.json()
    # Cuenta en el total global...
    assert body["totales"]["requerimientos"] == 1
    # ...pero no aporta a ninguna comuna (no se puede unir con la jornada).
    assert sum(c["requerimientos"] for c in body["por_comuna"]) == 0


def test_estadisticas_por_estrategia_es_exclusivo_de_avanzadas(client, fake_db):
    _set_avanzada(fake_db, "cid-estr", estrategia="En Un 2x3")
    _set_requerimiento(fake_db, "req-estr", avanzada_client_id="cid-estr", origen="avanzada")

    _set_jornada(fake_db, "jor-estr")
    _set_requerimiento(
        fake_db, "req-jor-estr", jornada_client_id="jor-estr", avanzada_client_id=None, origen="jornada",
    )

    body = client.get("/avanzadas/estadisticas").json()
    total_en_estrategias = sum(e["requerimientos"] for e in body["por_estrategia"])
    # Solo el requerimiento de origen avanzada aporta a por_estrategia.
    assert total_en_estrategias == 1


# ──────────────────────────────────────────────────────────────────────────
# /avanzadas/geo -- ambos orígenes + campo 'origen' + huérfanos omitidos
# ──────────────────────────────────────────────────────────────────────────

def test_geo_requerimientos_incluye_ambos_origenes_con_campo_origen(client, fake_db):
    _set_avanzada(fake_db, "cid-geo")
    _set_requerimiento(fake_db, "req-geo-avz", avanzada_client_id="cid-geo", origen="avanzada", coordenadas="3.45, -76.53")

    _set_jornada(fake_db, "jor-geo")
    _set_requerimiento(
        fake_db, "req-geo-jor", jornada_client_id="jor-geo", avanzada_client_id=None, origen="jornada",
        coordenadas="3.46, -76.54",
    )

    body = client.get("/avanzadas/geo").json()
    origenes = {p["id"]: p["origen"] for p in body["requerimientos"]}
    assert origenes["req-geo-avz"] == "avanzada"
    assert origenes["req-geo-jor"] == "jornada"
    assert body["omitidos"]["requerimientos"] == 0


def test_geo_requerimiento_jornada_huerfano_se_omite_y_cuenta(client, fake_db):
    _set_requerimiento(
        fake_db, "req-jor-huerfano-geo", jornada_client_id="no-existe", avanzada_client_id=None,
        origen="jornada", coordenadas="3.46, -76.54",
    )
    body = client.get("/avanzadas/geo").json()
    assert body["requerimientos"] == []
    assert body["omitidos"]["requerimientos"] == 1


def test_geo_requerimiento_avanzada_huerfano_se_omite_y_cuenta(client, fake_db):
    _set_requerimiento(
        fake_db, "req-avz-huerfano-geo", avanzada_client_id="no-existe", origen="avanzada",
        coordenadas="3.46, -76.54",
    )
    body = client.get("/avanzadas/geo").json()
    assert body["requerimientos"] == []
    assert body["omitidos"]["requerimientos"] == 1


# ──────────────────────────────────────────────────────────────────────────
# GET /avanzadas/{client_id} -- no-leakage de requerimientos de jornada
# ──────────────────────────────────────────────────────────────────────────

def test_detalle_avanzada_no_filtra_requerimientos_de_jornada(client, fake_db):
    _set_avanzada(fake_db, "cid-noleak")
    _set_requerimiento(
        fake_db, "req-propio", avanzada_client_id="cid-noleak", origen="avanzada",
        requerimiento="Requerimiento propio de la avanzada",
    )
    _set_jornada(fake_db, "jor-noleak")
    _set_requerimiento(
        fake_db, "req-ajeno", jornada_client_id="jor-noleak", avanzada_client_id=None, origen="jornada",
        requerimiento="Requerimiento de una jornada, no debe aparecer acá",
    )

    response = client.get("/avanzadas/cid-noleak")
    assert response.status_code == 200
    body = response.json()

    assert len(body["requerimientos"]) == 1
    assert body["requerimientos"][0]["id"] == "req-propio"
    ids = [r["id"] for r in body["requerimientos"]]
    assert "req-ajeno" not in ids
