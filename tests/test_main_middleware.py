"""
Tests de middlewares globales registrados en ``app.main``: compresión
gzip de respuestas (``GZipMiddleware``) y forzado de ``charset=utf-8`` en
JSON (``UTF8JSONMiddleware``).

Usa la app real (``app.main.app``) para validar el comportamiento tal como
queda configurado en producción -- incluyendo el orden real de
``add_middleware()`` -- en vez de reconstruir un stack de middlewares
aparte. Firestore y la autenticación se simulan igual que en
``tests/test_avanzadas_routes.py``, reutilizando el endpoint
``GET /avanzadas/catalogos`` como fuente de un payload JSON grande con
texto acentuado en español.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth_system.dependencies import get_current_user
from app.main import app
from app.routes import avanzadas_routes
from tests.fakes_firestore import FakeFirestore


_FAKE_USER = {"uid": "tester-uid", "email": "tester@catatrack.test"}


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr(avanzadas_routes, "db", db)
    return db


@pytest.fixture(autouse=True)
def _reset_catalogos_cache():
    avanzadas_routes._catalogos_cache = None
    yield
    avanzadas_routes._catalogos_cache = None


@pytest.fixture()
def client(fake_db):
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _sembrar_categoria_grande(fake_db) -> None:
    fake_db.collection("categorias_personalizadas").document().set({
        "entidad": "DAGMA",
        "categoria": "Categoría de Migración registrada en campo",
        "fecha": "2026-07-10",
    })


def test_catalogos_con_accept_encoding_gzip_devuelve_comprimido_y_utf8_correcto(client, fake_db):
    _sembrar_categoria_grande(fake_db)

    response = client.get(
        "/avanzadas/catalogos",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    # El catálogo por defecto (CATEGORIAS_DEFAULT) es grande de sobra para
    # superar el minimum_size de GZipMiddleware.
    assert response.headers.get("content-encoding") == "gzip"
    assert "charset=utf-8" in response.headers.get("content-type", "")

    body = response.json()
    assert "Categoría de Migración registrada en campo" in body["categorias"]["DAGMA"]


def test_catalogos_sin_accept_encoding_gzip_devuelve_utf8_sin_comprimir(client, fake_db):
    _sembrar_categoria_grande(fake_db)

    response = client.get(
        "/avanzadas/catalogos",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers.get("content-type") == "application/json; charset=utf-8"

    body = response.json()
    assert "Categoría de Migración registrada en campo" in body["categorias"]["DAGMA"]
