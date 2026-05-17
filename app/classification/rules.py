"""
Matcher léxico determinista basado en `keywords` declaradas por fila
en `taxonomia.TAXONOMIA`.

Devuelve una lista de candidatos `[{fila, score, hits}]` ordenados
por score descendente. El score es simplemente el número de keywords
matcheadas (case/tilde insensitive) en el texto normalizado.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List

from .taxonomia import TAXONOMIA


def normalizar(texto: str) -> str:
    """Lowercase + remoción de tildes + colapsar espacios."""
    if not texto:
        return ""
    # NFD descompone "á" en "a" + acento; el filtro elimina los marks.
    desc = unicodedata.normalize("NFD", texto)
    sin_tildes = "".join(ch for ch in desc if unicodedata.category(ch) != "Mn")
    sin_tildes = sin_tildes.lower()
    sin_tildes = re.sub(r"\s+", " ", sin_tildes).strip()
    return sin_tildes


def aplicar_reglas(texto: str) -> List[Dict]:
    """
    Recorre la taxonomía y cuenta keywords coincidentes (substring match)
    en el texto normalizado. Solo devuelve filas con score >= 1.
    """
    normalizado = normalizar(texto)
    if not normalizado:
        return []

    candidatos: List[Dict] = []
    for fila in TAXONOMIA:
        hits: List[str] = []
        for kw in fila["keywords"]:
            kw_norm = normalizar(kw)
            if kw_norm and kw_norm in normalizado:
                hits.append(kw)
        if hits:
            candidatos.append({
                "fila": fila,
                "score": len(hits),
                "hits": hits,
            })

    candidatos.sort(key=lambda c: c["score"], reverse=True)
    return candidatos
