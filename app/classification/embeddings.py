"""
Módulo de embeddings semánticos (retirado en favor del clasificador de reglas léxicas).

Conserva este stub de compatibilidad para evitar errores de importación en código
legacy o tests. Siempre reporta no disponible (False) y no carga librerías pesadas.
"""
from __future__ import annotations

from typing import List, Tuple


def esta_disponible() -> bool:
    """Retorna False: la clasificación por embeddings ha sido retirada."""
    return False


def precargar(force: bool = False) -> bool:
    """No-op defensivo: no precarga ningún modelo."""
    return False


def calcular_similitudes(texto: str, top_k: int = 5) -> List[Tuple[int, float]]:
    """Stub que retorna lista vacía sin intentar cargar SentenceTransformer."""
    return []
