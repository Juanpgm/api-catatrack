#!/usr/bin/env python
"""
CLI gateada para purgar los datos legacy de ``artefacto_360`` (módulo
retirado por ``unify-avanzada-jornada-integral``) de S3 y Firestore.

USO (desde ``api-catatrack/``):
    python scripts/purge_legacy_artefacto.py
        # dry-run (default): no borra nada, solo reporta qué se borraría.

    python scripts/purge_legacy_artefacto.py \
        --i-confirm-bucket=<bucket-vivo> \
        --i-confirm-deprecated \
        --yes
        # ejecuta deletes reales SOLO si los 3 flags están presentes, el
        # bucket coincide EXACTAMENTE con S3_BUCKET_NAME, y además se
        # confirma interactivamente re-tipeando el nombre del bucket.

Gates obligatorios para ejecutar cualquier delete real (ver design.md,
sección "Legacy Purge Safeguard"):
    a) ``--i-confirm-deprecated`` — confirma que las rutas legacy de
       ``app/routes/artefacto_360_routes.py`` ya están marcadas
       ``deprecated=True`` (design decision #7).
    b) ``--i-confirm-bucket=<name>`` — ``<name>`` debe ser EXACTAMENTE
       igual al valor vivo de la env var ``S3_BUCKET_NAME``.
    c) ``--yes`` — confirmación explícita de ejecución.
    d) Confirmación interactiva adicional: se solicita re-tipear el
       nombre del bucket por stdin; si no coincide EXACTAMENTE (tras
       recortar espacios), aborta sin borrar nada.

Si falta CUALQUIERA de los gates a/b/c, o si el bucket no coincide, el
script cae a modo dry-run: reporta cuántos documentos/objetos SE
BORRARÍAN, sin ejecutar ningún delete.

Alcance de la purga:
    - S3: todos los objetos bajo el prefijo ``requerimientos/``.
    - Firestore: todos los documentos de las colecciones ``visitas``,
      ``requerimientos`` y ``requerimientos_dagma``.

Reutiliza el mismo patrón de carga de ``.env`` que
``scripts/migrate_formulario_avanzadas.py`` (parser KEY=VALUE propio,
resuelto por ruta absoluta relativa a este archivo, cargado ANTES de
importar ``app.firebase_config``/``app.utils.s3_storage``).

IMPORTANTE: la ejecución real de este script contra infraestructura viva
está FUERA DE ALCANCE del cambio ``unify-avanzada-jornada-integral`` (ver
design.md, "Open Questions" — falta confirmar el bucket S3 vivo en
Railway). Este archivo es un deliverable gateado, no algo que se corra
como parte de este cambio.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Optional

# ──────────────────────────────────────────────────────────────────────────
# 1) Cargar api-catatrack/.env ANTES de importar nada de `app.*` (mismo
#    patrón que scripts/migrate_formulario_avanzadas.py).
# ──────────────────────────────────────────────────────────────────────────


def _load_env_file(path: Path) -> None:
    """Parser mínimo de archivos .env: líneas ``KEY=VALUE``, ignora
    comentarios (``#``) y líneas vacías. No pisa variables ya seteadas
    en el entorno real del proceso (el entorno gana sobre el archivo).
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key:
            os.environ.setdefault(key, value)


_API_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _API_ROOT / ".env"
_load_env_file(_ENV_PATH)

# Asegura que `app` y `scripts` sean importables sin importar desde dónde
# se invoque este archivo.
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))


_S3_PREFIX = "requerimientos/"
_FIRESTORE_COLLECTIONS = ("visitas", "requerimientos", "requerimientos_dagma")


def _safe_print(*args, **kwargs) -> None:
    """``print`` con fallback ASCII-safe (mismo patrón que
    ``migrate_formulario_avanzadas._safe_print``): evita crashear en
    consolas Windows cp1252 que no pueden codificar tildes/emojis.
    """
    text = " ".join(str(a) for a in args)
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, errors="backslashreplace").decode(encoding), **kwargs)


# ──────────────────────────────────────────────────────────────────────────
# Gates
# ──────────────────────────────────────────────────────────────────────────


def _gates_a_b_c_pass(args: argparse.Namespace, live_bucket: str) -> bool:
    """Gates a) --i-confirm-deprecated, b) --i-confirm-bucket coincide, c) --yes.

    Cualquiera ausente o el bucket sin coincidir -> False (dry-run).
    """
    if not args.i_confirm_deprecated:
        _safe_print("ABORTADO: falta --i-confirm-deprecated")
        return False
    if not args.i_confirm_bucket:
        _safe_print("ABORTADO: falta --i-confirm-bucket=<nombre>")
        return False
    if args.i_confirm_bucket != live_bucket:
        _safe_print(
            f"ABORTADO: --i-confirm-bucket='{args.i_confirm_bucket}' no coincide "
            f"con el bucket vivo S3_BUCKET_NAME='{live_bucket}'"
        )
        return False
    if not args.yes:
        _safe_print("ABORTADO: falta --yes")
        return False
    return True


def _interactive_bucket_confirmation(live_bucket: str, input_fn: Callable[[str], str]) -> bool:
    """Gate d): re-tipear el nombre del bucket por stdin. No coincide -> False."""
    _safe_print(
        f"\nCONFIRMACION FINAL: esta operacion BORRA PERMANENTEMENTE datos legacy "
        f"de S3 (prefijo '{_S3_PREFIX}') y Firestore "
        f"({', '.join(_FIRESTORE_COLLECTIONS)}) en el bucket '{live_bucket}'."
    )
    typed = input_fn(f"Escribe el nombre del bucket ('{live_bucket}') para confirmar: ")
    if typed.strip() != live_bucket:
        _safe_print(f"ABORTADO: el nombre tipeado ('{typed.strip()}') no coincide con '{live_bucket}'")
        return False
    return True


# ──────────────────────────────────────────────────────────────────────────
# Operaciones de borrado / reporte (sobre clientes inyectados y testeables)
# ──────────────────────────────────────────────────────────────────────────


def _dry_run_counts(db, collections=_FIRESTORE_COLLECTIONS) -> dict:
    """Cuenta documentos que SE BORRARÍAN por colección, sin borrar nada."""
    return {name: len(list(db.collection(name).stream())) for name in collections}


def _delete_firestore_collections(db, collections=_FIRESTORE_COLLECTIONS) -> dict:
    """Borra todos los documentos de cada colección legacy. Retorna conteo
    de documentos borrados por colección.
    """
    counts = {}
    for name in collections:
        col = db.collection(name)
        docs = list(col.stream())
        for doc in docs:
            col.document(doc.id).delete()
        counts[name] = len(docs)
    return counts


# ──────────────────────────────────────────────────────────────────────────
# Punto de entrada testeable
# ──────────────────────────────────────────────────────────────────────────


def run_purge(
    args: argparse.Namespace,
    db=None,
    s3_client=None,
    live_bucket: Optional[str] = None,
    input_fn: Callable[[str], str] = input,
) -> dict:
    """Ejecuta (o simula, en dry-run) la purga legacy.

    ``db``/``s3_client`` son inyectables para tests (fakes en memoria);
    si no se pasan, se resuelven contra infraestructura real
    (``app.firebase_config.db`` / ``app.utils.s3_storage.get_s3_client``)
    SOLO cuando hace falta (después de pasar todos los gates), para que
    los tests nunca toquen credenciales reales.

    Retorna un dict-resumen: ``{"executed": bool, ...}``.
    """
    if live_bucket is None:
        live_bucket = os.getenv("S3_BUCKET_NAME", "catatrack-photos")

    if db is None:
        from app.firebase_config import db as _real_db  # noqa: E402

        db = _real_db

    if not _gates_a_b_c_pass(args, live_bucket):
        _safe_print("\n=== DRY-RUN (gates incompletos, no se borro nada) ===")
        counts = _dry_run_counts(db)
        for name, count in counts.items():
            _safe_print(f"Se BORRARIAN {count} documentos de '{name}' (dry-run)")
        _safe_print(
            f"Se BORRARIAN objetos S3 bajo el prefijo '{_S3_PREFIX}' "
            f"en el bucket '{live_bucket}' (dry-run)"
        )
        return {"executed": False, "reason": "gates_failed", "dry_run_counts": counts}

    if not _interactive_bucket_confirmation(live_bucket, input_fn=input_fn):
        return {"executed": False, "reason": "interactive_confirmation_failed"}

    if s3_client is None:
        from app.utils.s3_storage import get_s3_client as _get_real_s3_client  # noqa: E402

        s3_client = _get_real_s3_client()

    from app.utils.s3_storage import delete_prefix  # noqa: E402

    _safe_print(f"\n=== EJECUTANDO PURGA REAL sobre bucket '{live_bucket}' ===")
    s3_deleted = delete_prefix(_S3_PREFIX, s3_client=s3_client, bucket=live_bucket)
    firestore_deleted = _delete_firestore_collections(db)

    _safe_print(f"S3: {s3_deleted} objetos borrados bajo '{_S3_PREFIX}'")
    for name, count in firestore_deleted.items():
        _safe_print(f"Firestore '{name}': {count} documentos borrados")

    return {"executed": True, "s3_deleted": s3_deleted, "firestore_deleted": firestore_deleted}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--i-confirm-bucket",
        dest="i_confirm_bucket",
        default=None,
        metavar="<name>",
        help="Nombre del bucket S3 vivo; debe coincidir EXACTAMENTE con S3_BUCKET_NAME",
    )
    parser.add_argument(
        "--i-confirm-deprecated",
        dest="i_confirm_deprecated",
        action="store_true",
        help="Confirma que las rutas legacy ya estan marcadas deprecated (design decision #7)",
    )
    parser.add_argument(
        "--yes",
        dest="yes",
        action="store_true",
        help="Confirmacion explicita de ejecucion",
    )
    args = parser.parse_args()

    run_purge(args)


if __name__ == "__main__":
    main()
