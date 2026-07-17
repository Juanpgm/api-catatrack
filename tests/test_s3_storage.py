"""
Tests del módulo unificado de S3 (``app/utils/s3_storage.py``).

Cubre: formato de key, resolución de bucket, creación de cliente
(credenciales faltantes), subida con forma enriquecida, borrado
best-effort (por lista de keys y por prefijo) y listado con URLs
presignadas. Usa ``FakeS3Client`` de ``tests/fakes_firestore.py`` — no
requiere red ni credenciales reales.
"""
from __future__ import annotations

import re

import pytest

from app.utils import s3_storage
from tests.fakes_firestore import FakeS3Client


# ──────────────────────────────────────────────────────────────────────────
# build_key
# ──────────────────────────────────────────────────────────────────────────

def test_build_key_sigue_el_formato_modulo_client_categoria_uuid_filename():
    key = s3_storage.build_key("avanzadas", "cid-001", "equipo", "foto.jpg")

    match = re.fullmatch(r"avanzadas/cid-001/equipo/([0-9a-f]{32})_foto\.jpg", key)
    assert match is not None


def test_build_key_sanea_caracteres_no_seguros_del_filename():
    key = s3_storage.build_key("jornadas", "cid-002", "croquis", "foto raro!.jpg")

    assert "foto_raro_.jpg" in key
    assert " " not in key
    assert "!" not in key


def test_build_key_permite_categoria_con_subrutas():
    key = s3_storage.build_key("avanzadas", "cid-003", "requerimientos/0", "foto.png")

    assert key.startswith("avanzadas/cid-003/requerimientos/0/")


def test_build_key_genera_uuid_distinto_en_cada_llamada():
    key1 = s3_storage.build_key("avanzadas", "cid-004", "equipo", "foto.jpg")
    key2 = s3_storage.build_key("avanzadas", "cid-004", "equipo", "foto.jpg")

    assert key1 != key2


# ──────────────────────────────────────────────────────────────────────────
# bucket_name
# ──────────────────────────────────────────────────────────────────────────

def test_bucket_name_usa_default_cuando_no_hay_env(monkeypatch):
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)

    assert s3_storage.bucket_name() == "catatrack-photos"


def test_bucket_name_usa_env_cuando_esta_configurada(monkeypatch):
    monkeypatch.setenv("S3_BUCKET_NAME", "bucket-custom")

    assert s3_storage.bucket_name() == "bucket-custom"


# ──────────────────────────────────────────────────────────────────────────
# get_s3_client
# ──────────────────────────────────────────────────────────────────────────

def test_get_s3_client_lanza_valueerror_sin_credenciales(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setattr(s3_storage, "load_dotenv", lambda *a, **k: None)

    with pytest.raises(ValueError):
        s3_storage.get_s3_client()


def test_get_s3_client_retorna_cliente_boto3_con_credenciales(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setattr(s3_storage, "load_dotenv", lambda *a, **k: None)

    client = s3_storage.get_s3_client()

    assert client.meta.region_name == "us-east-2"


# ──────────────────────────────────────────────────────────────────────────
# upload_file
# ──────────────────────────────────────────────────────────────────────────

def test_upload_file_retorna_forma_enriquecida():
    fake = FakeS3Client()

    resultado = s3_storage.upload_file(
        b"contenido-fake",
        modulo="avanzadas",
        client_id="cid-010",
        categoria="equipo",
        filename="foto.jpg",
        content_type="image/jpeg",
        s3_client=fake,
        bucket="test-bucket",
    )

    assert set(resultado.keys()) == {"filename", "s3_key", "s3_url", "content_type", "size"}
    assert resultado["filename"] == "foto.jpg"
    assert resultado["content_type"] == "image/jpeg"
    assert resultado["size"] == len(b"contenido-fake")
    assert resultado["s3_key"].startswith("avanzadas/cid-010/equipo/")
    assert resultado["s3_url"] == f"https://test-bucket.s3.amazonaws.com/{resultado['s3_key']}"
    assert len(fake.uploaded) == 1
    assert fake.uploaded[0]["Bucket"] == "test-bucket"
    assert fake.uploaded[0]["Key"] == resultado["s3_key"]
    assert fake.uploaded[0]["ContentType"] == "image/jpeg"


def test_upload_file_content_type_por_defecto_cuando_es_none():
    fake = FakeS3Client()

    resultado = s3_storage.upload_file(
        b"x",
        modulo="jornadas",
        client_id="cid-011",
        categoria="croquis",
        filename="foto.png",
        content_type=None,
        s3_client=fake,
        bucket="test-bucket",
    )

    assert resultado["content_type"] == "application/octet-stream"


def test_upload_file_usa_bucket_name_por_defecto_si_no_se_pasa(monkeypatch):
    monkeypatch.setenv("S3_BUCKET_NAME", "bucket-por-defecto")
    fake = FakeS3Client()

    resultado = s3_storage.upload_file(
        b"x",
        modulo="avanzadas",
        client_id="cid-012",
        categoria="equipo",
        filename="foto.jpg",
        content_type="image/jpeg",
        s3_client=fake,
    )

    assert resultado["s3_url"].startswith("https://bucket-por-defecto.s3.amazonaws.com/")


# ──────────────────────────────────────────────────────────────────────────
# delete_keys
# ──────────────────────────────────────────────────────────────────────────

def test_delete_keys_llama_delete_objects_con_las_keys_dadas():
    fake = FakeS3Client()

    s3_storage.delete_keys(["a/b.jpg", "a/c.jpg"], s3_client=fake, bucket="test-bucket")

    assert set(fake.deleted) == {"a/b.jpg", "a/c.jpg"}


def test_delete_keys_no_hace_nada_con_lista_vacia():
    fake = FakeS3Client()

    s3_storage.delete_keys([], s3_client=fake, bucket="test-bucket")

    assert fake.deleted == []


def test_delete_keys_es_best_effort_y_no_propaga_errores():
    fake = FakeS3Client(fail_on_delete=True)

    # No debe lanzar excepción aunque el cliente S3 falle.
    s3_storage.delete_keys(["a/b.jpg"], s3_client=fake, bucket="test-bucket")


# ──────────────────────────────────────────────────────────────────────────
# delete_prefix
# ──────────────────────────────────────────────────────────────────────────

def test_delete_prefix_borra_todos_los_objetos_bajo_el_prefijo():
    fake = FakeS3Client(
        objects=[
            {"Key": "avanzadas/cid-020/equipo/a.jpg", "Size": 10},
            {"Key": "avanzadas/cid-020/requerimientos/0/b.jpg", "Size": 20},
            {"Key": "avanzadas/otro-cid/equipo/c.jpg", "Size": 30},
        ]
    )

    borrados = s3_storage.delete_prefix("avanzadas/cid-020/", s3_client=fake, bucket="test-bucket")

    assert borrados == 2
    assert "avanzadas/cid-020/equipo/a.jpg" in fake.deleted
    assert "avanzadas/cid-020/requerimientos/0/b.jpg" in fake.deleted
    assert "avanzadas/otro-cid/equipo/c.jpg" not in fake.deleted


def test_delete_prefix_es_best_effort_y_retorna_cero_en_error():
    fake = FakeS3Client(fail_on_list=True)

    borrados = s3_storage.delete_prefix("avanzadas/cid-021/", s3_client=fake, bucket="test-bucket")

    assert borrados == 0


# ──────────────────────────────────────────────────────────────────────────
# list_documents
# ──────────────────────────────────────────────────────────────────────────

def test_list_documents_retorna_forma_con_urls_presignadas():
    fake = FakeS3Client(
        objects=[{"Key": "avanzadas/cid-030/equipo/foto.jpg", "Size": 123}],
    )

    documentos = s3_storage.list_documents(
        "avanzadas/cid-030/equipo/", s3_client=fake, bucket="test-bucket"
    )

    assert len(documentos) == 1
    doc = documentos[0]
    assert doc["filename"] == "foto.jpg"
    assert doc["s3_key"] == "avanzadas/cid-030/equipo/foto.jpg"
    assert doc["size"] == 123
    assert "url_descarga" in doc
    assert "url_visualizar" in doc


def test_list_documents_retorna_lista_vacia_sin_coincidencias():
    fake = FakeS3Client(objects=[])

    documentos = s3_storage.list_documents("prefijo/vacio/", s3_client=fake, bucket="test-bucket")

    assert documentos == []


# ──────────────────────────────────────────────────────────────────────────
# presign_url
# ──────────────────────────────────────────────────────────────────────────

def test_presign_url_retorna_url_firmada():
    fake = FakeS3Client()

    url = s3_storage.presign_url(
        "avanzadas/cid-040/equipo/foto.jpg", s3_client=fake, bucket="test-bucket"
    )

    assert url.startswith("https://test-bucket.s3.amazonaws.com/avanzadas/cid-040/equipo/foto.jpg")
