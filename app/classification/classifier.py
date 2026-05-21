"""
API pública del clasificador de centros gestores
(equivalente al campo `organismos_encargados`).

Algoritmo:
    1. Normaliza el texto y aplica reglas léxicas (`rules.aplicar_reglas`).
    2. Si hay candidatos con `score >= UMBRAL_REGLAS`, devuelve los
       responsables únicos de esas filas (método = "reglas").
    3. Si no, intenta embeddings semánticos
       (`embeddings.calcular_similitudes`) y toma los top-k cuya
       similitud >= `UMBRAL_EMBEDDINGS`. Método = "embeddings".
    4. Si embeddings no está disponible o no hay candidatos válidos,
       devuelve lista vacía con método = "ninguno". El endpoint que
       consuma esto debe decidir si exigir input manual o devolver
       una lista vacía al cliente.

La función nunca lanza excepciones por fallas del modelo: degrada
gracefully a reglas / a lista vacía.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional

from . import embeddings as _emb
from .rules import aplicar_reglas
from .taxonomia import TAXONOMIA, mapear_tipo_requerimiento_front

UMBRAL_REGLAS = int(os.getenv("CLASSIFIER_RULES_MIN_HITS", "1"))
UMBRAL_EMBEDDINGS = float(os.getenv("CLASSIFIER_EMB_THRESHOLD", "0.45"))


def _unir_textos(*textos: Optional[str]) -> str:
    """Concatena fragmentos no vacíos con separador ' . '."""
    partes = [t.strip() for t in textos if t and t.strip()]
    return " . ".join(partes)


def _responsables_unicos(filas: Iterable[Dict]) -> List[str]:
    """Preserva orden de aparición."""
    vistos: List[str] = []
    for f in filas:
        for r in f["responsables"]:
            if r not in vistos:
                vistos.append(r)
    return vistos


def _derivar_tipo_y_acciones(
    matches: List[Dict],
    filas: Iterable[Dict],
) -> Dict:
    """
    A partir de los matches y sus filas de taxonomía:
      - Tipo de requerimiento: mapping desde la categoría/subcategoría del
        match de mayor score (el primero, ya ordenados).
      - Acciones por organismo: dict {organismo: [acciones_unicas]}.
    """
    if not matches:
        return {"tipo_requerimiento": "Otros", "acciones_por_organismo": {}}

    top = matches[0]
    tipo = mapear_tipo_requerimiento_front(
        top.get("categoria", ""),
        top.get("subcategoria", "") or "",
    )

    acciones: Dict[str, List[str]] = {}
    for fila in filas:
        accion = (fila.get("accion") or "").strip()
        if not accion:
            continue
        for organismo in fila.get("responsables", []):
            lista = acciones.setdefault(organismo, [])
            if accion not in lista:
                lista.append(accion)

    return {"tipo_requerimiento": tipo, "acciones_por_organismo": acciones}


def clasificar_centros_gestores(
    requerimiento: str,
    tipo_requerimiento: Optional[str] = None,
    observaciones: Optional[str] = None,
    transcripciones: Optional[List[Dict]] = None,
    top_k: int = 3,
) -> Dict:
    """
    Clasifica el texto combinado y devuelve los centros gestores
    sugeridos junto con metadata auditable.

    Parámetros:
        requerimiento: texto principal (obligatorio).
        tipo_requerimiento, observaciones: contexto adicional.
        transcripciones: lista de dicts (ej. salida de Whisper) con
            clave "texto"; se concatena su contenido para enriquecer.
        top_k: número máximo de filas candidatas a considerar.

    Devuelve:
        {
            "centros_gestores": ["DAGMA", "UAESP"],
            "confianza": 0.82,
            "metodo": "reglas" | "embeddings" | "ninguno",
            "matches": [
                {"categoria", "subcategoria", "condicion", "accion",
                 "responsables", "score", "hits"},
                ...
            ],
            "tipo_requerimiento": "Poda de árboles",
            "acciones_por_organismo": {"DAGMA": ["Atención prioritaria"], ...},
        }
    """
    transcripciones_txt = ""
    if transcripciones:
        try:
            transcripciones_txt = " ".join(
                (t.get("texto") or "") for t in transcripciones if isinstance(t, dict)
            )
        except Exception:
            transcripciones_txt = ""

    texto = _unir_textos(requerimiento, tipo_requerimiento, observaciones, transcripciones_txt)

    # ---------- 1) Reglas ----------
    candidatos_reglas = aplicar_reglas(texto)
    candidatos_validos = [c for c in candidatos_reglas if c["score"] >= UMBRAL_REGLAS]

    if candidatos_validos:
        top = candidatos_validos[:top_k]
        max_score = max(c["score"] for c in top)
        confianza = min(1.0, 0.5 + 0.15 * max_score)  # heurística simple
        matches = [
            {
                "categoria": c["fila"]["categoria"],
                "subcategoria": c["fila"]["subcategoria"],
                "condicion": c["fila"]["condicion"],
                "accion": c["fila"].get("accion", ""),
                "responsables": c["fila"]["responsables"],
                "score": c["score"],
                "hits": c["hits"],
            }
            for c in top
        ]
        derivado = _derivar_tipo_y_acciones(matches, (c["fila"] for c in top))
        return {
            "centros_gestores": _responsables_unicos(c["fila"] for c in top),
            "confianza": round(confianza, 3),
            "metodo": "reglas",
            "matches": matches,
            "tipo_requerimiento": derivado["tipo_requerimiento"],
            "acciones_por_organismo": derivado["acciones_por_organismo"],
        }

    # ---------- 2) Embeddings ----------
    if _emb.esta_disponible() and texto:
        try:
            sims = _emb.calcular_similitudes(texto, top_k=max(top_k, 5))
        except Exception as e:
            print(f"⚠️ Embeddings fallaron, devolviendo vacío: {e}")
            sims = []

        sims_validas = [(i, s) for i, s in sims if s >= UMBRAL_EMBEDDINGS][:top_k]
        if sims_validas:
            filas = [TAXONOMIA[i] for i, _ in sims_validas]
            matches = [
                {
                    "categoria": TAXONOMIA[i]["categoria"],
                    "subcategoria": TAXONOMIA[i]["subcategoria"],
                    "condicion": TAXONOMIA[i]["condicion"],
                    "accion": TAXONOMIA[i].get("accion", ""),
                    "responsables": TAXONOMIA[i]["responsables"],
                    "score": round(s, 3),
                    "hits": [],
                }
                for i, s in sims_validas
            ]
            max_sim = sims_validas[0][1]
            derivado = _derivar_tipo_y_acciones(matches, filas)
            return {
                "centros_gestores": _responsables_unicos(filas),
                "confianza": round(float(max_sim), 3),
                "metodo": "embeddings",
                "matches": matches,
                "tipo_requerimiento": derivado["tipo_requerimiento"],
                "acciones_por_organismo": derivado["acciones_por_organismo"],
            }

    # ---------- 3) Sin clasificación ----------
    return {
        "centros_gestores": [],
        "confianza": 0.0,
        "metodo": "ninguno",
        "matches": [],
        "tipo_requerimiento": "Otros",
        "acciones_por_organismo": {},
    }
