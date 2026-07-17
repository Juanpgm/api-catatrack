#!/usr/bin/env python
"""
CLI one-off para migrar ``context/Formulario Avanzadas.xlsx`` a Firestore.

USO (desde ``api-catatrack/``):
    python scripts/migrate_formulario_avanzadas.py               # dry-run (default, no escribe nada)
    python scripts/migrate_formulario_avanzadas.py --dry-run      # idem, explicito
    python scripts/migrate_formulario_avanzadas.py --execute      # escribe en Firestore real

Requiere que ``api-catatrack/.env`` tenga ``FIREBASE_SERVICE_ACCOUNT_JSON``.
Este script carga ese archivo por su cuenta (parser KEY=VALUE propio,
resuelto por ruta absoluta relativa a este archivo, no al cwd) ANTES de
importar ``app.firebase_config``, para garantizar que la variable de
entorno esté lista cuando ese módulo inicializa Firebase Admin SDK al
importarse (mismo patrón que ``start-local.ps1`` usa para el backend).

Toda la lógica de transformación fila-de-Excel -> documento-Firestore vive
en ``scripts/migrate_formulario_avanzadas_transforms.py`` como funciones
puras (sin Firestore) cubiertas por
``tests/test_migrate_formulario_avanzadas.py``. Este archivo es solo el
wrapper de I/O: lee el Excel, llama a esas funciones y escribe/verifica en
Firestore.

NOTA de consola: en Windows con consola cp1252, imprimir texto con tildes
puede lanzar ``UnicodeEncodeError``. Este script usa ``_safe_print`` con
fallback automático a escapes ASCII; para salida sin fallback (tildes
reales en pantalla), ejecutar con la variable de entorno
``PYTHONIOENCODING=utf-8`` seteada antes de invocar el script.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# ──────────────────────────────────────────────────────────────────────────
# 1) Cargar api-catatrack/.env ANTES de importar nada de `app.*`
# ──────────────────────────────────────────────────────────────────────────


def _load_env_file(path: Path) -> None:
    """Parser mínimo de archivos .env: líneas ``KEY=VALUE``, ignora
    comentarios (``#``) y líneas vacías. Mismo comportamiento que
    ``Import-EnvFile`` en ``start-local.ps1``. No pisa variables que ya
    estén seteadas en el entorno real del proceso (el entorno gana sobre
    el archivo, igual que ``python-dotenv`` por default).
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
# se invoque este archivo (p.ej. `python scripts/migrate_....py` desde la
# raíz del repo, no solo `python -m scripts...` desde api-catatrack/).
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

# A partir de acá SÍ podemos importar `app.*` con seguridad: las env vars
# que `app.firebase_config` necesita (FIREBASE_SERVICE_ACCOUNT_JSON) ya
# están seteadas en `os.environ`.
import pandas as pd  # noqa: E402

from app.firebase_config import db  # noqa: E402
from scripts.migrate_formulario_avanzadas_transforms import (  # noqa: E402
    build_asistentes_by_avanzada,
    build_avanzadas,
    build_categorias_personalizadas,
    build_compromisos,
    build_encuestas,
    build_jornadas,
    build_requerimientos,
    build_seguimientos,
    count_requerimientos_by_avanzada,
)

_EXCEL_PATH = Path(__file__).resolve().parent.parent.parent / "context" / "Formulario Avanzadas.xlsx"

_BATCH_LIMIT = 500  # límite de operaciones por WriteBatch de Firestore

_SHEET_NAMES = [
    "Avanzadas",
    "Asistencia",
    "Requerimientos",
    "CategoriasPersonalizadas",
    "JornadasIntegrales",
    "EncuestasExperiencia",
    "SeguimientosHistorial",
    "Compromisos",
]

_COLLECTION_NAMES = [
    "avanzadas",
    "avanzadas_requerimientos",
    "categorias_personalizadas",
    "jornadas_integrales",
    "jornadas_compromisos",
    "jornadas_seguimientos",
    "jornadas_encuestas",
]

# Avanzada conocida usada como ancla de verificación post-ejecución (ver
# instrucciones de la migración: debe existir con este nombre exacto y
# tener requerimientos/asistentes asociados).
_VERIFY_AVANZADA_ID = "56f7fc52-27f0-40a2-98ff-fd8a182d1187"
_VERIFY_AVANZADA_NOMBRE = "Comuna 2 - (Urb. La Flora - Vipasa)"


def _safe_print(*args, **kwargs) -> None:
    """``print`` con fallback ASCII-safe: si la consola no puede codificar
    algún caracter (p.ej. tildes en cp1252), reintenta con escapes en vez
    de crashear a mitad de la migración.
    """
    text = " ".join(str(a) for a in args)
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, errors="backslashreplace").decode(encoding), **kwargs)


def _json_safe(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=True, default=str, indent=2)


def _load_sheets(excel_path: Path) -> Dict[str, List[dict]]:
    sheets: Dict[str, List[dict]] = {}
    for name in _SHEET_NAMES:
        df = pd.read_excel(excel_path, sheet_name=name)
        sheets[name] = df.to_dict("records")
    return sheets


def _build_all_collections(sheets: Dict[str, List[dict]]) -> Tuple[Dict[str, Dict[str, dict]], List[str]]:
    warnings: List[str] = []

    asistentes_by_client, w = build_asistentes_by_avanzada(sheets["Asistencia"])
    warnings.extend(w)

    req_docs, w = build_requerimientos(sheets["Requerimientos"])
    warnings.extend(w)
    req_counts = count_requerimientos_by_avanzada(req_docs)

    av_docs, w = build_avanzadas(sheets["Avanzadas"], asistentes_by_client, req_counts)
    warnings.extend(w)

    cat_docs, w = build_categorias_personalizadas(sheets["CategoriasPersonalizadas"])
    warnings.extend(w)

    jornada_docs, w = build_jornadas(sheets["JornadasIntegrales"])
    warnings.extend(w)

    compromiso_docs, w = build_compromisos(sheets["Compromisos"])
    warnings.extend(w)

    compromiso_to_jornada = {
        cid: doc.get("jornada_client_id") for cid, doc in compromiso_docs.items()
    }
    seguimiento_docs, w = build_seguimientos(sheets["SeguimientosHistorial"], compromiso_to_jornada)
    warnings.extend(w)

    encuesta_docs, w = build_encuestas(sheets["EncuestasExperiencia"])
    warnings.extend(w)

    collections = {
        "avanzadas": av_docs,
        "avanzadas_requerimientos": req_docs,
        "categorias_personalizadas": cat_docs,
        "jornadas_integrales": jornada_docs,
        "jornadas_compromisos": compromiso_docs,
        "jornadas_seguimientos": seguimiento_docs,
        "jornadas_encuestas": encuesta_docs,
    }
    return collections, warnings


def _write_collection_batched(collection_name: str, docs: Dict[str, dict]) -> int:
    """Escribe ``docs`` en ``collection_name`` usando WriteBatch, respetando
    el límite de 500 operaciones por batch. ``set()`` sobreescribe el doc
    completo, así que reejecutar el script con el mismo Excel es idempotente.
    """
    items = list(docs.items())
    written = 0
    for start in range(0, len(items), _BATCH_LIMIT):
        chunk = items[start : start + _BATCH_LIMIT]
        batch = db.batch()
        for doc_id, data in chunk:
            batch.set(db.collection(collection_name).document(doc_id), data)
        batch.commit()
        written += len(chunk)
    return written


def _verify() -> None:
    _safe_print("\n=== VERIFICACION POST-EJECUCION ===")
    for name in _COLLECTION_NAMES:
        count_result = list(db.collection(name).count().get())
        count_value = count_result[0][0].value
        _safe_print(f"{name}: {count_value} documentos (conteo en Firestore)")

    doc = db.collection("avanzadas").document(_VERIFY_AVANZADA_ID).get()
    if not doc.exists:
        _safe_print(f"ERROR: avanzada '{_VERIFY_AVANZADA_ID}' NO existe en Firestore")
        return

    data = doc.to_dict() or {}
    nombre_ok = data.get("nombre_avanzada") == _VERIFY_AVANZADA_NOMBRE
    _safe_print(f"avanzada '{_VERIFY_AVANZADA_ID}': existe = SI")
    _safe_print(
        f"  nombre_avanzada = {data.get('nombre_avanzada')!r} "
        f"(esperado {_VERIFY_AVANZADA_NOMBRE!r}) -> {'OK' if nombre_ok else 'MISMATCH'}"
    )
    asistentes = data.get("asistentes") or []
    _safe_print(f"  asistentes: {len(asistentes)} -> {'OK (no vacio)' if asistentes else 'VACIO'}")

    req_docs = (
        db.collection("avanzadas_requerimientos")
        .where("avanzada_client_id", "==", _VERIFY_AVANZADA_ID)
        .get()
    )
    req_count = len(req_docs)
    _safe_print(
        f"  avanzadas_requerimientos asociados: {req_count} -> "
        f"{'OK (no vacio)' if req_count else 'VACIO'}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Solo parsea/transforma e imprime (default)")
    mode.add_argument("--execute", action="store_true", help="Escribe en Firestore real")
    args = parser.parse_args()

    execute = args.execute
    dry_run = not execute

    if not _EXCEL_PATH.exists():
        _safe_print(f"ERROR: no se encontro el Excel en {_EXCEL_PATH}")
        sys.exit(1)

    _safe_print(f"Leyendo {_EXCEL_PATH} ...")
    sheets = _load_sheets(_EXCEL_PATH)
    for name, rows in sheets.items():
        _safe_print(f"  hoja '{name}': {len(rows)} filas de datos")

    collections, warnings = _build_all_collections(sheets)

    _safe_print("\n=== RESUMEN POR COLECCION ===")
    for name, docs in collections.items():
        _safe_print(f"{name}: {len(docs)} documentos")

    if warnings:
        _safe_print(f"\n=== WARNINGS ({len(warnings)}) ===")
        for w in warnings:
            _safe_print(f"  - {w}")
    else:
        _safe_print("\n=== WARNINGS ===\n  (ninguno)")

    if dry_run:
        _safe_print("\n=== MUESTRAS (2 por coleccion, DRY-RUN, no se escribio nada) ===")
        for name, docs in collections.items():
            _safe_print(f"\n-- {name} --")
            for doc_id, data in list(docs.items())[:2]:
                _safe_print(f"[{doc_id}]")
                _safe_print(_json_safe(data))
        _safe_print("\nDRY-RUN completo. Use --execute para escribir en Firestore real.")
        return

    _safe_print("\n=== EJECUTANDO ESCRITURA EN FIRESTORE REAL ===")
    for name, docs in collections.items():
        written = _write_collection_batched(name, docs)
        _safe_print(f"{name}: {written} documentos escritos")

    _verify()


if __name__ == "__main__":
    main()
