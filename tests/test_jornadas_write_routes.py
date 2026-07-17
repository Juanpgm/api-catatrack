"""
Tests de los endpoints de escritura de Jornadas Integrales
(POST/PATCH/DELETE bajo el prefijo ``/jornadas``).

Cubre: creación idempotente de jornada, transición de estado,
subida de croquis, compromisos (creación idempotente, validación de
tipo/meta_cuantitativa, edición, borrado con seguimientos asociados),
seguimientos (denormalización de jornada_client_id, validación de
estado, actualización del compromiso padre), verificación en campo
(multipart con fotos), encuestas (validación de calif, borrado),
listado y detalle, orden de registro de rutas estáticas vs.
dinámicas, invalidación de caches (jornadas/estadisticas y
avanzadas/geo) y autenticación.

Sigue el mismo estilo de fixtures que ``test_avanzadas_routes.py`` /
``test_jornadas_routes.py`` (no hay conftest.py compartido en el
proyecto).
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
    monkeypatch.setattr(jornadas_routes, "db", db)
    # avanzadas_routes.db también apunta a la misma instancia: los
    # requerimientos de jornada se escriben en la colección compartida
    # 'avanzadas_requerimientos' y el cache de /avanzadas/geo se invalida
    # desde jornadas_routes.
    monkeypatch.setattr(avanzadas_routes, "db", db)
    return db


@pytest.fixture()
def fake_s3(monkeypatch):
    s3 = FakeS3Client()
    monkeypatch.setattr(avanzadas_routes, "get_s3_client", lambda: s3)
    return s3


@pytest.fixture(autouse=True)
def _reset_caches():
    jornadas_routes._jornadas_estadisticas_cache = None
    avanzadas_routes._geo_cache = None
    avanzadas_routes._estadisticas_cache = None
    avanzadas_routes._catalogos_cache = None
    yield
    jornadas_routes._jornadas_estadisticas_cache = None
    avanzadas_routes._geo_cache = None
    avanzadas_routes._estadisticas_cache = None
    avanzadas_routes._catalogos_cache = None


def _build_app():
    app = FastAPI()
    app.include_router(jornadas_routes.router)
    app.include_router(avanzadas_routes.router)
    return app


@pytest.fixture()
def client(fake_db, fake_s3):
    app = _build_app()
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    return TestClient(app)


@pytest.fixture()
def unauthenticated_client(fake_db, fake_s3):
    return TestClient(_build_app())


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _valid_jornada_datos(client_id: str = "jor_001", **overrides) -> dict:
    datos = {
        "client_id": client_id,
        "nombre_jornada": "Jornada Comuna 3",
        "fecha": "2026-07-10",
        "sector_punto_reconocimiento": "Sector A",
        "punto_encuentro": "Cancha comunal",
        "direccion_punto_encuentro": "Calle 5 # 10-20",
        "coordenadas_encuentro": "3.4516, -76.5320",
        "comuna": "COMUNA 03",
        "barrio": "San Antonio",
        "direcciones_recuperadas": ["Calle 1", "Calle 2"],
    }
    datos.update(overrides)
    return datos


def _crear_jornada(client: TestClient, client_id: str = "jor_001", **overrides) -> dict:
    response = client.post("/jornadas", json=_valid_jornada_datos(client_id, **overrides))
    assert response.status_code in (200, 201), response.text
    return response.json()


def _valid_compromiso_datos(client_id: str = "com_001", **overrides) -> dict:
    datos = {
        "client_id": client_id,
        "organismo": "DAGMA",
        "oferta_servicio": "Poda de árboles",
        "responsable_organismo": "Juan Pérez",
        "celular_responsable": "3001234567",
        "tipo": "cualitativo",
        "compromiso": "Podar los árboles del parque",
        "unidad_medida": None,
        "meta_cuantitativa": 0,
    }
    datos.update(overrides)
    return datos


def _crear_compromiso(client: TestClient, jornada_client_id: str, client_id: str = "com_001", **overrides) -> dict:
    response = client.post(
        f"/jornadas/{jornada_client_id}/compromisos",
        json=_valid_compromiso_datos(client_id, **overrides),
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


# ──────────────────────────────────────────────────────────────────────────
# Autenticación
# ──────────────────────────────────────────────────────────────────────────

def test_crear_jornada_requiere_autenticacion(unauthenticated_client):
    response = unauthenticated_client.post("/jornadas", json=_valid_jornada_datos())
    assert response.status_code == 403


def test_listar_jornadas_requiere_autenticacion(unauthenticated_client):
    assert unauthenticated_client.get("/jornadas").status_code == 403


def test_detalle_jornada_requiere_autenticacion(unauthenticated_client):
    assert unauthenticated_client.get("/jornadas/cualquier-id").status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# POST /jornadas — creación
# ──────────────────────────────────────────────────────────────────────────

def test_crear_jornada_exitosa(client, fake_db):
    response = client.post("/jornadas", json=_valid_jornada_datos())
    assert response.status_code == 201
    body = response.json()

    assert body["client_id"] == "jor_001"
    assert body["estado"] == "planificacion"
    assert body["numero"] == 1
    assert body["nombre_jornada"] == "Jornada Comuna 3"

    doc = fake_db.collection("jornadas_integrales").document("jor_001").get()
    assert doc.exists


def test_crear_jornada_numero_incrementa(client):
    _crear_jornada(client, client_id="jor_a")
    body_b = _crear_jornada(client, client_id="jor_b")
    assert body_b["numero"] == 2


def test_crear_jornada_idempotente_por_client_id(client, fake_db):
    datos = _valid_jornada_datos(client_id="jor_dup")
    first = client.post("/jornadas", json=datos)
    assert first.status_code == 201

    second = client.post("/jornadas", json=datos)
    assert second.status_code == 200
    assert second.json()["client_id"] == "jor_dup"

    assert len(fake_db.collection("jornadas_integrales").stream()) == 1


@pytest.mark.parametrize("campo", [
    "nombre_jornada", "fecha", "punto_encuentro", "direccion_punto_encuentro",
    "coordenadas_encuentro", "comuna", "barrio",
])
def test_crear_jornada_rechaza_campo_obligatorio_vacio(client, campo):
    datos = _valid_jornada_datos()
    datos[campo] = ""
    response = client.post("/jornadas", json=datos)
    assert response.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# PATCH /jornadas/{client_id}
# ──────────────────────────────────────────────────────────────────────────

def test_patch_jornada_actualiza_campos_generales(client):
    _crear_jornada(client, client_id="jor_patch")
    response = client.patch("/jornadas/jor_patch", json={"barrio": "Nuevo Barrio", "comuna": "COMUNA 05"})
    assert response.status_code == 200
    body = response.json()
    assert body["barrio"] == "Nuevo Barrio"
    assert body["comuna"] == "COMUNA 05"


@pytest.mark.parametrize("estado", ["planificacion", "seguimiento", "ejecucion", "completada"])
def test_patch_jornada_acepta_estados_validos(client, estado):
    _crear_jornada(client, client_id="jor_estado")
    response = client.patch("/jornadas/jor_estado", json={"estado": estado})
    assert response.status_code == 200
    assert response.json()["estado"] == estado


def test_patch_jornada_rechaza_estado_invalido(client):
    _crear_jornada(client, client_id="jor_estado_malo")
    response = client.patch("/jornadas/jor_estado_malo", json={"estado": "no-es-un-estado"})
    assert response.status_code == 422


def test_patch_jornada_actualiza_campos_de_cierre(client):
    _crear_jornada(client, client_id="jor_cierre")
    response = client.patch("/jornadas/jor_cierre", json={
        "asistencia_aproximada": 42,
        "observaciones_generales": "Todo salió bien",
        "peticiones_comunidad": "Más alumbrado",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["asistencia_aproximada"] == 42
    assert body["observaciones_generales"] == "Todo salió bien"
    assert body["peticiones_comunidad"] == "Más alumbrado"


def test_patch_jornada_no_encontrada(client):
    response = client.patch("/jornadas/no-existe", json={"barrio": "X"})
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# POST /jornadas/{client_id}/croquis
# ──────────────────────────────────────────────────────────────────────────

def test_subir_croquis_actualiza_url(client, fake_s3):
    _crear_jornada(client, client_id="jor_croquis")
    response = client.post(
        "/jornadas/jor_croquis/croquis",
        files={"foto": ("croquis.jpg", b"fake-bytes", "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["url_croquis"] is not None
    assert "jor_croquis" in body["url_croquis"]
    assert len(fake_s3.uploaded) == 1


def test_subir_croquis_jornada_no_encontrada(client):
    response = client.post(
        "/jornadas/no-existe/croquis",
        files={"foto": ("croquis.jpg", b"fake-bytes", "image/jpeg")},
    )
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# POST /jornadas/{client_id}/compromisos
# ──────────────────────────────────────────────────────────────────────────

def test_crear_compromiso_exitoso(client, fake_db):
    _crear_jornada(client, client_id="jor_com")
    body = _crear_compromiso(client, "jor_com", client_id="com_001")
    assert body["jornada_client_id"] == "jor_com"
    assert body["organismo"] == "DAGMA"
    assert body["estado_seguimiento"] is None

    doc = fake_db.collection("jornadas_compromisos").document("com_001").get()
    assert doc.exists
    assert doc.to_dict()["nombre_jornada"] == "Jornada Comuna 3"


def test_crear_compromiso_jornada_no_encontrada(client):
    response = client.post("/jornadas/no-existe/compromisos", json=_valid_compromiso_datos())
    assert response.status_code == 404


def test_crear_compromiso_idempotente_por_client_id(client, fake_db):
    _crear_jornada(client, client_id="jor_com_dup")
    datos = _valid_compromiso_datos(client_id="com_dup")

    first = client.post("/jornadas/jor_com_dup/compromisos", json=datos)
    assert first.status_code == 201

    second = client.post("/jornadas/jor_com_dup/compromisos", json=datos)
    assert second.status_code == 200

    assert len(fake_db.collection("jornadas_compromisos").stream()) == 1


def test_crear_compromiso_rechaza_tipo_invalido(client):
    _crear_jornada(client, client_id="jor_tipo")
    datos = _valid_compromiso_datos(client_id="com_tipo", tipo="no-es-un-tipo")
    response = client.post("/jornadas/jor_tipo/compromisos", json=datos)
    assert response.status_code == 422


def test_crear_compromiso_cualitativo_rechaza_meta_cuantitativa_no_cero(client):
    """Decisión de diseño: un compromiso 'cualitativo' con
    meta_cuantitativa != 0 se RECHAZA con 422 (en vez de coaccionarlo
    silenciosamente a 0), para no ocultar un error de captura."""
    _crear_jornada(client, client_id="jor_meta")
    datos = _valid_compromiso_datos(client_id="com_meta", tipo="cualitativo", meta_cuantitativa=5)
    response = client.post("/jornadas/jor_meta/compromisos", json=datos)
    assert response.status_code == 422


def test_crear_compromiso_cuantitativo_acepta_meta(client):
    _crear_jornada(client, client_id="jor_meta_ok")
    datos = _valid_compromiso_datos(
        client_id="com_meta_ok", tipo="cuantitativo", unidad_medida="árboles", meta_cuantitativa=10,
    )
    response = client.post("/jornadas/jor_meta_ok/compromisos", json=datos)
    assert response.status_code == 201
    assert response.json()["meta_cuantitativa"] == 10


# ──────────────────────────────────────────────────────────────────────────
# PATCH /jornadas/compromisos/{client_id}
# ──────────────────────────────────────────────────────────────────────────

def test_patch_compromiso_edita_campos(client):
    _crear_jornada(client, client_id="jor_edit")
    _crear_compromiso(client, "jor_edit", client_id="com_edit")

    response = client.patch("/jornadas/compromisos/com_edit", json={"organismo": "EMCALI"})
    assert response.status_code == 200
    assert response.json()["organismo"] == "EMCALI"


def test_patch_compromiso_no_encontrado(client):
    response = client.patch("/jornadas/compromisos/no-existe", json={"organismo": "EMCALI"})
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# DELETE /jornadas/compromisos/{client_id}
# ──────────────────────────────────────────────────────────────────────────

def test_delete_compromiso_sin_seguimientos_se_elimina(client, fake_db):
    _crear_jornada(client, client_id="jor_del")
    _crear_compromiso(client, "jor_del", client_id="com_del")

    response = client.delete("/jornadas/compromisos/com_del")
    assert response.status_code == 200

    doc = fake_db.collection("jornadas_compromisos").document("com_del").get()
    assert not doc.exists


def test_delete_compromiso_con_seguimientos_se_rechaza(client, fake_db):
    """Decisión de diseño: se RECHAZA (409) el borrado de un compromiso
    con seguimientos asociados en vez de cascadearlos, para no destruir
    el historial de verificación en campo implícitamente."""
    _crear_jornada(client, client_id="jor_del2")
    _crear_compromiso(client, "jor_del2", client_id="com_del2")

    seg = client.post(
        "/jornadas/compromisos/com_del2/seguimientos",
        json={"client_id": "seg_del2", "fecha_seguimiento": "2026-07-15", "estado": "ok"},
    )
    assert seg.status_code == 201

    response = client.delete("/jornadas/compromisos/com_del2")
    assert response.status_code == 409

    doc = fake_db.collection("jornadas_compromisos").document("com_del2").get()
    assert doc.exists


def test_delete_compromiso_no_encontrado(client):
    response = client.delete("/jornadas/compromisos/no-existe")
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# POST /jornadas/compromisos/{client_id}/seguimientos
# ──────────────────────────────────────────────────────────────────────────

def test_crear_seguimiento_denormaliza_jornada_client_id(client, fake_db):
    _crear_jornada(client, client_id="jor_seg")
    _crear_compromiso(client, "jor_seg", client_id="com_seg")

    response = client.post(
        "/jornadas/compromisos/com_seg/seguimientos",
        json={"client_id": "seg_001", "fecha_seguimiento": "2026-07-15", "estado": "ok", "responsable_seguimiento": "Ana"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["jornada_client_id"] == "jor_seg"
    assert body["compromiso_client_id"] == "com_seg"

    doc = fake_db.collection("jornadas_seguimientos").document("seg_001").get()
    assert doc.to_dict()["jornada_client_id"] == "jor_seg"


def test_crear_seguimiento_actualiza_estado_seguimiento_del_compromiso(client, fake_db):
    _crear_jornada(client, client_id="jor_seg2")
    _crear_compromiso(client, "jor_seg2", client_id="com_seg2")

    client.post(
        "/jornadas/compromisos/com_seg2/seguimientos",
        json={"client_id": "seg_002", "fecha_seguimiento": "2026-07-15", "estado": "novedad"},
    )

    compromiso_doc = fake_db.collection("jornadas_compromisos").document("com_seg2").get()
    assert compromiso_doc.to_dict()["estado_seguimiento"] == "novedad"


def test_crear_seguimiento_rechaza_estado_invalido(client):
    _crear_jornada(client, client_id="jor_seg3")
    _crear_compromiso(client, "jor_seg3", client_id="com_seg3")

    response = client.post(
        "/jornadas/compromisos/com_seg3/seguimientos",
        json={"client_id": "seg_003", "fecha_seguimiento": "2026-07-15", "estado": "no-valido"},
    )
    assert response.status_code == 422


def test_crear_seguimiento_compromiso_no_encontrado(client):
    response = client.post(
        "/jornadas/compromisos/no-existe/seguimientos",
        json={"client_id": "seg_x", "fecha_seguimiento": "2026-07-15", "estado": "ok"},
    )
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# PATCH /jornadas/compromisos/{client_id}/verificacion
# ──────────────────────────────────────────────────────────────────────────

def _patch_verificacion(client, compromiso_client_id, datos, files=None):
    return client.patch(
        f"/jornadas/compromisos/{compromiso_client_id}/verificacion",
        data={"datos": json.dumps(datos)},
        files=files or [],
    )


def test_patch_verificacion_actualiza_campos_y_sube_fotos(client, fake_s3):
    _crear_jornada(client, client_id="jor_verif")
    _crear_compromiso(client, "jor_verif", client_id="com_verif")

    datos = {
        "estado_verificacion_campo": "cumple",
        "fecha_verificacion": "2026-07-20",
        "responsable_verificacion": "Carlos",
        "representante_organismo": "Luisa",
        "resultado_obtenido": "Se podaron los árboles",
        "comentario_verificacion": "Sin novedades",
        "fotos_existentes": ["https://existente.example/foto1.jpg"],
    }
    files = [
        ("fotos", ("foto1.jpg", b"bytes1", "image/jpeg")),
        ("fotos", ("foto2.jpg", b"bytes2", "image/jpeg")),
    ]
    response = _patch_verificacion(client, "com_verif", datos, files)
    assert response.status_code == 200
    body = response.json()

    assert body["estado_verificacion_campo"] == "cumple"
    assert body["fecha_verificacion"] == "2026-07-20"
    assert len(body["fotos_verificacion"]) == 3
    assert "https://existente.example/foto1.jpg" in body["fotos_verificacion"]
    assert len(fake_s3.uploaded) == 2


def test_patch_verificacion_rechaza_estado_invalido(client):
    _crear_jornada(client, client_id="jor_verif2")
    _crear_compromiso(client, "jor_verif2", client_id="com_verif2")

    response = _patch_verificacion(client, "com_verif2", {"estado_verificacion_campo": "tal-vez"})
    assert response.status_code == 422


def test_patch_verificacion_compromiso_no_encontrado(client):
    response = _patch_verificacion(client, "no-existe", {"estado_verificacion_campo": "cumple"})
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# POST /jornadas/{client_id}/encuestas
# ──────────────────────────────────────────────────────────────────────────

def test_crear_encuesta_exitosa(client, fake_db):
    _crear_jornada(client, client_id="jor_enc")
    response = client.post("/jornadas/jor_enc/encuestas", json={
        "client_id": "enc_001",
        "nombre_participante": "Vecina X",
        "comuna": "COMUNA 03",
        "barrio": "San Antonio",
        "evaluaciones": [{"org": "DAGMA", "calif": "Bueno"}],
        "comentario_final": "Buena atención",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["jornada_client_id"] == "jor_enc"
    assert body["evaluaciones"][0]["calif"] == "Bueno"


@pytest.mark.parametrize("calif", ["Bueno", "Regular", "Malo", "N/A"])
def test_crear_encuesta_acepta_calificaciones_validas(client, calif):
    _crear_jornada(client, client_id="jor_enc_ok")
    response = client.post("/jornadas/jor_enc_ok/encuestas", json={
        "client_id": f"enc_{calif}",
        "evaluaciones": [{"org": "DAGMA", "calif": calif}],
    })
    assert response.status_code == 201


def test_crear_encuesta_rechaza_calificacion_invalida(client):
    _crear_jornada(client, client_id="jor_enc_bad")
    response = client.post("/jornadas/jor_enc_bad/encuestas", json={
        "client_id": "enc_bad",
        "evaluaciones": [{"org": "DAGMA", "calif": "Excelente"}],
    })
    assert response.status_code == 422


def test_crear_encuesta_jornada_no_encontrada(client):
    response = client.post("/jornadas/no-existe/encuestas", json={"client_id": "enc_x", "evaluaciones": []})
    assert response.status_code == 404


def test_crear_encuesta_idempotente(client, fake_db):
    _crear_jornada(client, client_id="jor_enc_idem")
    datos = {"client_id": "enc_idem", "evaluaciones": []}

    first = client.post("/jornadas/jor_enc_idem/encuestas", json=datos)
    assert first.status_code == 201
    second = client.post("/jornadas/jor_enc_idem/encuestas", json=datos)
    assert second.status_code == 200
    assert len(fake_db.collection("jornadas_encuestas").stream()) == 1


# ──────────────────────────────────────────────────────────────────────────
# DELETE /jornadas/encuestas/{client_id}
# ──────────────────────────────────────────────────────────────────────────

def test_delete_encuesta(client, fake_db):
    _crear_jornada(client, client_id="jor_enc_del")
    client.post("/jornadas/jor_enc_del/encuestas", json={"client_id": "enc_del", "evaluaciones": []})

    response = client.delete("/jornadas/encuestas/enc_del")
    assert response.status_code == 200

    doc = fake_db.collection("jornadas_encuestas").document("enc_del").get()
    assert not doc.exists


def test_delete_encuesta_no_encontrada(client):
    response = client.delete("/jornadas/encuestas/no-existe")
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# GET /jornadas — listado
# ──────────────────────────────────────────────────────────────────────────

def test_listar_jornadas_incluye_compromisos_count(client):
    _crear_jornada(client, client_id="jor_list1", fecha="2026-01-01")
    _crear_jornada(client, client_id="jor_list2", fecha="2026-06-01")
    _crear_compromiso(client, "jor_list1", client_id="com_list1")
    _crear_compromiso(client, "jor_list1", client_id="com_list1b")

    response = client.get("/jornadas")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["client_id"] == "jor_list2"  # fecha desc
    item1 = next(j for j in body if j["client_id"] == "jor_list1")
    assert item1["compromisos_count"] == 2


def test_listar_jornadas_respeta_limit(client):
    for i in range(3):
        _crear_jornada(client, client_id=f"jor_l{i}", fecha=f"2026-01-0{i + 1}")
    response = client.get("/jornadas", params={"limit": 2})
    assert len(response.json()) == 2


# ──────────────────────────────────────────────────────────────────────────
# GET /jornadas/{client_id} — detalle
# ──────────────────────────────────────────────────────────────────────────

def test_detalle_jornada_incluye_compromisos_seguimientos_encuestas(client):
    _crear_jornada(client, client_id="jor_det")
    _crear_compromiso(client, "jor_det", client_id="com_det")
    client.post(
        "/jornadas/compromisos/com_det/seguimientos",
        json={"client_id": "seg_det", "fecha_seguimiento": "2026-07-15", "estado": "ok"},
    )
    client.post("/jornadas/jor_det/encuestas", json={"client_id": "enc_det", "evaluaciones": []})

    response = client.get("/jornadas/jor_det")
    assert response.status_code == 200
    body = response.json()

    assert body["client_id"] == "jor_det"
    assert len(body["compromisos"]) == 1
    assert len(body["compromisos"][0]["seguimientos"]) == 1
    assert body["compromisos"][0]["seguimientos"][0]["id"] == "seg_det"
    assert len(body["encuestas"]) == 1
    assert body["requerimientos"] == []
    assert body["compromisos_count"] == 1


def test_detalle_jornada_no_encontrada(client):
    response = client.get("/jornadas/no-existe")
    assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────
# Orden de registro de rutas: estáticas no deben ser interceptadas por
# la ruta dinámica /jornadas/{client_id}
# ──────────────────────────────────────────────────────────────────────────

def test_estadisticas_no_es_interceptada_por_dinamica_client_id(client):
    # Si /jornadas/{client_id} interceptara esto, respondería 404
    # "Jornada 'estadisticas' no encontrada" en vez de la forma real.
    response = client.get("/jornadas/estadisticas")
    assert response.status_code == 200
    assert "totales" in response.json()


def test_compromisos_seguimientos_no_es_interceptada_por_dinamica_client_id(client):
    _crear_jornada(client, client_id="jor_route")
    _crear_compromiso(client, "jor_route", client_id="com_route")

    response = client.post(
        "/jornadas/compromisos/com_route/seguimientos",
        json={"client_id": "seg_route", "fecha_seguimiento": "2026-07-15", "estado": "ok"},
    )
    assert response.status_code == 201


def test_compromisos_verificacion_no_es_interceptada(client):
    _crear_jornada(client, client_id="jor_route2")
    _crear_compromiso(client, "jor_route2", client_id="com_route2")

    response = _patch_verificacion(client, "com_route2", {"estado_verificacion_campo": "cumple"})
    assert response.status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# Invalidación de caches (jornadas/estadisticas y avanzadas/geo)
# ──────────────────────────────────────────────────────────────────────────

def test_crear_jornada_invalida_cache_estadisticas_jornadas(client):
    primera = client.get("/jornadas/estadisticas").json()
    assert primera["totales"]["jornadas"] == 0

    _crear_jornada(client, client_id="jor_cache")

    segunda = client.get("/jornadas/estadisticas").json()
    assert segunda["totales"]["jornadas"] == 1


def test_crear_jornada_invalida_cache_geo_avanzadas(client):
    primera = client.get("/avanzadas/geo").json()
    assert primera["jornadas"] == []

    _crear_jornada(client, client_id="jor_cache_geo")

    segunda = client.get("/avanzadas/geo").json()
    assert len(segunda["jornadas"]) == 1


def test_crear_compromiso_invalida_cache_estadisticas_jornadas(client):
    _crear_jornada(client, client_id="jor_cache2")
    client.get("/jornadas/estadisticas")

    _crear_compromiso(client, "jor_cache2", client_id="com_cache2")

    segunda = client.get("/jornadas/estadisticas").json()
    assert segunda["totales"]["compromisos"] == 1


# ──────────────────────────────────────────────────────────────────────────
# OpenAPI: todas las rutas nuevas deben quedar registradas
# ──────────────────────────────────────────────────────────────────────────

def test_rutas_nuevas_aparecen_en_openapi_schema():
    from app.main import app as real_app

    schema = real_app.openapi()
    paths = schema["paths"]

    assert "/jornadas" in paths
    assert "/jornadas/{client_id}" in paths
    assert "/jornadas/{client_id}/croquis" in paths
    assert "/jornadas/{client_id}/compromisos" in paths
    assert "/jornadas/compromisos/{client_id}" in paths
    assert "/jornadas/compromisos/{client_id}/seguimientos" in paths
    assert "/jornadas/compromisos/{client_id}/verificacion" in paths
    assert "/jornadas/{client_id}/encuestas" in paths
    assert "/jornadas/encuestas/{client_id}" in paths
    assert "/jornadas/{client_id}/requerimientos" in paths
