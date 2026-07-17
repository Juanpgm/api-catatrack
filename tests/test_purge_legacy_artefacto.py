"""
Tests del script de purga gateada de datos legacy de artefacto_360
(``scripts/purge_legacy_artefacto.py``).

Cubre los 4 gates obligatorios antes de ejecutar cualquier delete real
(ver design.md, "Legacy Purge Safeguard"):
  a) --i-confirm-deprecated
  b) --i-confirm-bucket=<name> (debe coincidir EXACTAMENTE con el bucket vivo)
  c) --yes
  d) confirmación interactiva: re-tipear el nombre del bucket por stdin

Si falta cualquiera de los 4 gates, el script NO debe ejecutar ningún
delete (ni en S3 ni en Firestore) — solo reporta (dry-run) qué se
borraría. Usa ``FakeFirestore``/``FakeS3Client`` de
``tests/fakes_firestore.py`` — no requiere red ni credenciales reales.
"""
from __future__ import annotations

import argparse

import pytest

from scripts import purge_legacy_artefacto as purge
from tests.fakes_firestore import FakeFirestore, FakeS3Client


LIVE_BUCKET = "catatrack-photos"


def _args(
    i_confirm_bucket=None,
    i_confirm_deprecated=False,
    yes=False,
) -> argparse.Namespace:
    return argparse.Namespace(
        i_confirm_bucket=i_confirm_bucket,
        i_confirm_deprecated=i_confirm_deprecated,
        yes=yes,
    )


def _seeded_db() -> FakeFirestore:
    """Firestore fake con un documento en cada colección legacy objetivo."""
    db = FakeFirestore()
    db.collection("visitas").document("VID-1").set({"vid": "VID-1"})
    db.collection("requerimientos").document("VID-1_REQ-1").set({"rid": "REQ-1"})
    db.collection("requerimientos_dagma").document("abc-123").set({"id": "abc-123"})
    return db


def _seeded_s3() -> FakeS3Client:
    """S3 fake con objetos bajo el prefijo legacy y uno fuera de alcance."""
    return FakeS3Client(
        objects=[
            {"Key": "requerimientos/VID-1/REQ-1/foto.jpg", "Size": 10},
            {"Key": "requerimientos/VID-1/REQ-1/nota_voz.mp3.gz", "Size": 20},
            {"Key": "avanzadas/cid-1/equipo/otra.jpg", "Size": 30},
        ]
    )


def _assert_nothing_was_deleted(db: FakeFirestore, s3: FakeS3Client) -> None:
    assert s3.deleted == []
    for name in ("visitas", "requerimientos", "requerimientos_dagma"):
        assert len(list(db.collection(name).stream())) == 1


# ──────────────────────────────────────────────────────────────────────────
# Gate a/b/c: flags obligatorios
# ──────────────────────────────────────────────────────────────────────────

def test_refuses_when_missing_i_confirm_bucket():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args(i_confirm_bucket=None, i_confirm_deprecated=True, yes=True)

    result = purge.run_purge(args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET)

    assert result["executed"] is False
    _assert_nothing_was_deleted(db, s3)


def test_refuses_when_missing_i_confirm_deprecated():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args(i_confirm_bucket=LIVE_BUCKET, i_confirm_deprecated=False, yes=True)

    result = purge.run_purge(args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET)

    assert result["executed"] is False
    _assert_nothing_was_deleted(db, s3)


def test_refuses_when_missing_yes():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args(i_confirm_bucket=LIVE_BUCKET, i_confirm_deprecated=True, yes=False)

    result = purge.run_purge(args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET)

    assert result["executed"] is False
    _assert_nothing_was_deleted(db, s3)


# ──────────────────────────────────────────────────────────────────────────
# Dry-run por defecto (sin flags)
# ──────────────────────────────────────────────────────────────────────────

def test_dry_run_default_no_flags_performs_zero_deletions_and_reports_counts():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args()  # sin flags, todo default

    result = purge.run_purge(args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET)

    assert result["executed"] is False
    assert result["dry_run_counts"] == {
        "visitas": 1,
        "requerimientos": 1,
        "requerimientos_dagma": 1,
    }
    _assert_nothing_was_deleted(db, s3)


# ──────────────────────────────────────────────────────────────────────────
# Gate b: mismatch de bucket
# ──────────────────────────────────────────────────────────────────────────

def test_bucket_mismatch_aborts_with_zero_deletions():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args(
        i_confirm_bucket="bucket-incorrecto",
        i_confirm_deprecated=True,
        yes=True,
    )

    result = purge.run_purge(args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET)

    assert result["executed"] is False
    _assert_nothing_was_deleted(db, s3)


# ──────────────────────────────────────────────────────────────────────────
# Gate d: confirmación interactiva (re-tipear nombre del bucket)
# ──────────────────────────────────────────────────────────────────────────

def test_all_flags_present_but_wrong_typed_bucket_name_aborts():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args(i_confirm_bucket=LIVE_BUCKET, i_confirm_deprecated=True, yes=True)

    def fake_input(_prompt: str) -> str:
        return "nombre-incorrecto"

    result = purge.run_purge(
        args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET, input_fn=fake_input
    )

    assert result["executed"] is False
    assert result["reason"] == "interactive_confirmation_failed"
    _assert_nothing_was_deleted(db, s3)


def test_all_flags_present_and_correct_typed_bucket_name_proceeds_to_deletion():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args(i_confirm_bucket=LIVE_BUCKET, i_confirm_deprecated=True, yes=True)

    def fake_input(_prompt: str) -> str:
        return LIVE_BUCKET

    result = purge.run_purge(
        args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET, input_fn=fake_input
    )

    assert result["executed"] is True
    # S3: solo se borran objetos bajo el prefijo requerimientos/, no otros módulos.
    assert set(s3.deleted) == {
        "requerimientos/VID-1/REQ-1/foto.jpg",
        "requerimientos/VID-1/REQ-1/nota_voz.mp3.gz",
    }
    assert "avanzadas/cid-1/equipo/otra.jpg" not in s3.deleted
    # Firestore: las 3 colecciones legacy quedan vacías.
    for name in ("visitas", "requerimientos", "requerimientos_dagma"):
        assert list(db.collection(name).stream()) == []
    assert result["s3_deleted"] == 2
    assert result["firestore_deleted"] == {
        "visitas": 1,
        "requerimientos": 1,
        "requerimientos_dagma": 1,
    }


def test_interactive_confirmation_strips_whitespace_but_requires_exact_name():
    db = _seeded_db()
    s3 = _seeded_s3()
    args = _args(i_confirm_bucket=LIVE_BUCKET, i_confirm_deprecated=True, yes=True)

    def fake_input(_prompt: str) -> str:
        return f"  {LIVE_BUCKET}  \n"

    result = purge.run_purge(
        args, db=db, s3_client=s3, live_bucket=LIVE_BUCKET, input_fn=fake_input
    )

    assert result["executed"] is True
