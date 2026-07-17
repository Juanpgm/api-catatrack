"""
Tests de ``POST /seguimiento/evidencias`` — subida de evidencias
fotográficas del Kanban de Seguimiento.

Reemplaza el flujo legacy que llamaba a
``/registrar-requerimiento`` del artefacto de captura DAGMA solo para
subir fotos; ahora usa ``app.utils.s3_storage`` directamente (módulo
``seguimiento``). Firestore no se toca en este endpoint, así que solo
se simula S3.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_system.dependencies import get_current_user
from app.routes import seguimiento_routes
from tests.fakes_firestore import FakeS3Client


_FAKE_USER = {"uid": "tester-uid", "email": "tester@catatrack.test"}


@pytest.fixture()
def fake_s3(monkeypatch):
    s3 = FakeS3Client()
    monkeypatch.setattr(seguimiento_routes.s3_storage, "get_s3_client", lambda: s3)
    return s3


@pytest.fixture()
def client(fake_s3):
    app = FastAPI()
    app.include_router(seguimiento_routes.router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    return TestClient(app)


def _post_evidencias(client, files, **data):
    return client.post("/seguimiento/evidencias", files=files, data=data)


def test_subir_evidencias_retorna_forma_unificada_de_s3_storage(client, fake_s3):
    files = [
        ("archivos", ("foto1.jpg", b"contenido-1", "image/jpeg")),
        ("archivos", ("foto2.png", b"contenido-2", "image/png")),
    ]

    response = _post_evidencias(client, files)

    assert response.status_code == 201
    body = response.json()
    assert len(body) == 2
    for item in body:
        assert set(item.keys()) == {"filename", "s3_key", "s3_url", "content_type", "size"}
    assert body[0]["filename"] == "foto1.jpg"
    assert body[0]["content_type"] == "image/jpeg"
    assert body[0]["size"] == len(b"contenido-1")
    assert body[0]["s3_url"].startswith("https://")
    assert "seguimiento/" in body[0]["s3_key"]


def test_subir_evidencias_sube_cada_archivo_a_s3(client, fake_s3):
    files = [("archivos", ("foto1.jpg", b"contenido-1", "image/jpeg"))]

    _post_evidencias(client, files)

    assert len(fake_s3.uploaded) == 1


def test_subir_evidencias_usa_requerimiento_id_como_client_id_en_la_key(client, fake_s3):
    files = [("archivos", ("foto1.jpg", b"contenido-1", "image/jpeg"))]

    response = _post_evidencias(client, files, requerimiento_id="req-042")

    body = response.json()
    assert "seguimiento/req-042/" in body[0]["s3_key"]


def test_subir_evidencias_sin_archivos_retorna_422(client):
    response = client.post("/seguimiento/evidencias", files=[])

    assert response.status_code == 422


def test_subir_evidencias_falla_s3_retorna_502(client, monkeypatch):
    fake_fail = FakeS3Client(fail_on_upload=True)
    monkeypatch.setattr(seguimiento_routes.s3_storage, "get_s3_client", lambda: fake_fail)
    files = [("archivos", ("foto1.jpg", b"contenido-1", "image/jpeg"))]

    response = _post_evidencias(client, files)

    assert response.status_code == 502


def test_subir_evidencias_requiere_autenticacion():
    app = FastAPI()
    app.include_router(seguimiento_routes.router)
    unauthenticated_client = TestClient(app)
    files = [("archivos", ("foto1.jpg", b"contenido-1", "image/jpeg"))]

    response = unauthenticated_client.post("/seguimiento/evidencias", files=files)

    assert response.status_code in (401, 403)
