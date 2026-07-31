"""
Tests para app.auth_system.dependencies.get_current_user.

Cubre la corrección del bug de producción "GET /avanzadas failed (401):
Token inválido o expirado": un except Exception genérico catalogaba
CUALQUIER falla durante la autenticación (incluyendo errores de Firestore
con un token 100% válido) como token inválido, forzando un logout indebido
en el frontend (ApiClient.fetchWithRetry sólo reintenta en 401 y cierra
sesión si el reintento también falla). Ahora sólo las excepciones que
realmente indican un token inválido/expirado devuelven 401.
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from firebase_admin import auth as firebase_auth

from app.auth_system import dependencies
from tests.fakes_firestore import FakeFirestore

AUTH_HEADERS = {"Authorization": "Bearer cualquier-token"}


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr(dependencies, "db", db)
    return db


@pytest.fixture()
def client(fake_db):
    app = FastAPI()

    @app.get("/protegido")
    async def protegido(current_user: dict = Depends(dependencies.get_current_user)):
        return {"uid": current_user["uid"]}

    return TestClient(app, raise_server_exceptions=False)


def test_token_realmente_invalido_devuelve_401(monkeypatch, client):
    def _raise(*args, **kwargs):
        raise firebase_auth.InvalidIdTokenError("malformado")

    monkeypatch.setattr(dependencies.auth_client, "verify_id_token", _raise)

    response = client.get("/protegido", headers=AUTH_HEADERS)

    assert response.status_code == 401
    assert response.json()["detail"] == "Token inválido o expirado"


def test_certificate_fetch_error_no_es_401(monkeypatch, client):
    def _raise(*args, **kwargs):
        raise firebase_auth.CertificateFetchError("timeout", cause=Exception("boom"))

    monkeypatch.setattr(dependencies.auth_client, "verify_id_token", _raise)

    response = client.get("/protegido", headers=AUTH_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] != "Token inválido o expirado"


def test_error_de_firestore_con_token_valido_no_es_401(monkeypatch, client, fake_db):
    monkeypatch.setattr(
        dependencies.auth_client, "verify_id_token", lambda *a, **k: {"uid": "user-1"}
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("Firestore timeout simulado")

    monkeypatch.setattr(fake_db.collection("users"), "document", _boom)

    response = client.get("/protegido", headers=AUTH_HEADERS)

    assert response.status_code == 500
    assert response.status_code != 401


def test_flujo_valido_sigue_funcionando(monkeypatch, client, fake_db):
    fake_db.collection("users").document("user-1").set({"email": "a@b.com", "is_active": True})
    monkeypatch.setattr(
        dependencies.auth_client, "verify_id_token", lambda *a, **k: {"uid": "user-1"}
    )

    response = client.get("/protegido", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["uid"] == "user-1"


def test_usuario_inactivo_sigue_dando_403(monkeypatch, client, fake_db):
    fake_db.collection("users").document("user-1").set({"email": "a@b.com", "is_active": False})
    monkeypatch.setattr(
        dependencies.auth_client, "verify_id_token", lambda *a, **k: {"uid": "user-1"}
    )

    response = client.get("/protegido", headers=AUTH_HEADERS)

    assert response.status_code == 403


def test_usuario_no_encontrado_sigue_dando_404(monkeypatch, client, fake_db):
    monkeypatch.setattr(
        dependencies.auth_client, "verify_id_token", lambda *a, **k: {"uid": "user-inexistente"}
    )

    response = client.get("/protegido", headers=AUTH_HEADERS)

    assert response.status_code == 404
