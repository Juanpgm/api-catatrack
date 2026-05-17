"""
Singleton del modelo de embeddings + matriz pre-computada de
descripciones canónicas de la taxonomía.

Patrón equivalente a `_get_whisper_model()` en `artefacto_360_routes.py`:
el modelo (~120 MB) se carga **lazy** en el primer uso y se mantiene
en memoria. Si la variable de entorno `CLASSIFIER_PRELOAD=true` se
exporta, el clasificador puede forzar la carga al arranque.

Caché en disco: respeta `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME`
configurados como env vars (en Railway, apuntan al volumen montado
en `/app/.cache/huggingface`).
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

_MODEL = None
_MATRIX = None  # numpy ndarray (n_filas, dim)
_MODEL_NAME = os.getenv(
    "CLASSIFIER_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


def _get_model():
    """Carga el modelo SentenceTransformer una sola vez."""
    global _MODEL
    if _MODEL is None:
        # Import diferido para no obligar a tener torch instalado en entornos
        # donde solo se usen las reglas léxicas (p. ej. tests rápidos).
        from sentence_transformers import SentenceTransformer

        print(f"🔄 Cargando modelo de embeddings '{_MODEL_NAME}'...")
        _MODEL = SentenceTransformer(_MODEL_NAME, device="cpu")
        print(f"✅ Modelo de embeddings '{_MODEL_NAME}' cargado")
    return _MODEL


def _get_matrix():
    """Pre-computa y cachea la matriz de embeddings de la taxonomía."""
    global _MATRIX
    if _MATRIX is None:
        from .taxonomia import listar_descripciones_canonicas

        modelo = _get_model()
        descripciones = listar_descripciones_canonicas()
        print(f"🔄 Calculando embeddings de {len(descripciones)} filas de taxonomía...")
        _MATRIX = modelo.encode(
            descripciones,
            normalize_embeddings=True,  # cosine == dot product
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        print(f"✅ Matriz de embeddings lista: shape={_MATRIX.shape}")
    return _MATRIX


def calcular_similitudes(texto: str, top_k: int = 5) -> List[Tuple[int, float]]:
    """
    Embebe `texto`, calcula similitud coseno contra la matriz
    pre-computada y devuelve los top-k (idx_fila, score).
    """
    if not texto or not texto.strip():
        return []

    modelo = _get_model()
    matriz = _get_matrix()
    vec = modelo.encode(
        [texto],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )[0]
    # producto punto (vectores ya normalizados) = similitud coseno
    sims = matriz @ vec  # shape (n_filas,)
    # top-k índices ordenados desc
    top_idx = sims.argsort()[::-1][:top_k]
    return [(int(i), float(sims[i])) for i in top_idx]


def precargar(force: bool = False) -> bool:
    """
    Fuerza la carga del modelo y la matriz. Útil para pre-warming en
    `app.main` cuando `CLASSIFIER_PRELOAD=true`. Devuelve True si se
    cargó correctamente; False si falló (no rompe el arranque).
    """
    flag = os.getenv("CLASSIFIER_PRELOAD", "").lower() in ("1", "true", "yes", "y")
    if not force and not flag:
        return False
    try:
        _get_matrix()
        return True
    except Exception as e:  # pragma: no cover - defensivo
        print(f"⚠️ No se pudo precargar el clasificador: {e}")
        return False


def esta_disponible() -> bool:
    """Indica si `sentence-transformers` está instalado y se puede cargar."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False
