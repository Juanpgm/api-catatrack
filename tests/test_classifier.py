"""
Tests del clasificador de centros gestores.

Estos tests SOLO ejercitan la rama de **reglas léxicas** para no
depender de `sentence-transformers` / `torch` en CI (que añaden
~700 MB de wheels). La rama de embeddings se valida en el endpoint
manualmente o con un test marcado con `@pytest.mark.slow` cuando
se decida instalar las deps en CI.
"""

from __future__ import annotations

import pytest

from app.classification.classifier import clasificar_centros_gestores
from app.classification.rules import normalizar, aplicar_reglas


# --------- Casos directos (frases típicas de la plantilla) ---------
CASOS_DIRECTOS = [
    ("Se cayó un árbol grande en la cuadra y bloquea el paso", {"DAGMA"}),
    ("Hay un árbol enfermo a punto de caerse", {"DAGMA"}),
    ("Necesitamos podar un árbol que está enredado en los cables eléctricos", {"EMCALI"}),
    ("Solicito poda normal del árbol del parque", {"UAESP"}),
    ("Luminaria apagada hace 3 días en el poste de la esquina", {"UAESP", "EMCALI"}),
    ("El semáforo no funciona en la intersección principal", {"Secretaría de Movilidad"}),
    ("Hay un sumidero tapado y se inunda la calle", {"EMCALI"}),
    ("Falta la tapa de la alcantarilla, es peligroso", {"EMCALI"}),
    ("No pasa el carro de la basura desde hace una semana", {"UAESP"}),
    ("Hay escombros botados en el lote", {"UAESP"}),
    ("Colchón botado en el andén", {"UAESP"}),
    ("Pasto crecido en zona verde sin mantenimiento", {"UAESP"}),
    ("Cambuche de habitante de calle en el parque", {"Bienestar Social", "SSJ", "UAESP"}),
    ("Ruido excesivo en el bar de la esquina toda la noche", {"SSJ", "Policía", "DAGMA"}),
    ("Música alta del vecino de al lado", {"SSJ", "Policía"}),
    ("Vendedor ambulante ocupando el andén", {"SSJ", "Desarrollo Económico", "Salud"}),
    ("Bolardo dañado al frente del colegio", {"Secretaría de Movilidad"}),
    ("Reductor de velocidad dañado", {"Secretaría de Movilidad"}),
    ("Barandal oxidado del puente peatonal", {"UAESP"}),
    ("Pintura del bordillo descolorida", {"Participación"}),
]


@pytest.mark.parametrize("texto,esperados", CASOS_DIRECTOS)
def test_clasificacion_reglas_directas(texto, esperados):
    """Cada frase debe activar por reglas y devolver al menos los responsables esperados."""
    resultado = clasificar_centros_gestores(texto)
    assert resultado["metodo"] == "reglas", (
        f"Esperaba método 'reglas', vino '{resultado['metodo']}' para: {texto!r}"
    )
    obtenidos = set(resultado["centros_gestores"])
    assert esperados.issubset(obtenidos), (
        f"Para {texto!r} esperaba que {esperados} estuviera en {obtenidos}"
    )
    assert resultado["confianza"] >= 0.5
    assert len(resultado["matches"]) >= 1


def test_multi_responsable_se_explota_correctamente():
    """'UAESP / EMCALI' debe devolver ambos responsables en la lista."""
    resultado = clasificar_centros_gestores("La luminaria del parque está apagada")
    assert "UAESP" in resultado["centros_gestores"]
    assert "EMCALI" in resultado["centros_gestores"]


def test_normalizacion_tildes_y_mayusculas():
    """El matching debe ignorar tildes y mayúsculas."""
    assert normalizar("Árbol Caído") == "arbol caido"
    assert normalizar("SEMÁFORO") == "semaforo"
    # Frase con tildes y mayúsculas debe seguir clasificando
    res = clasificar_centros_gestores("ÁRBOL CAÍDO EN LA VÍA")
    assert "DAGMA" in res["centros_gestores"]


def test_texto_vacio_devuelve_ninguno():
    """Texto vacío → método 'ninguno' y lista vacía."""
    res = clasificar_centros_gestores("")
    assert res["metodo"] == "ninguno"
    assert res["centros_gestores"] == []
    assert res["confianza"] == 0.0


def test_texto_sin_keywords_no_revienta():
    """Texto ajeno al dominio debe degradar gracefully (no excepciones)."""
    res = clasificar_centros_gestores("xkjsdh wqe rty zzz random gibberish 12345")
    assert res["metodo"] in ("ninguno", "embeddings")
    assert isinstance(res["centros_gestores"], list)


def test_combina_requerimiento_y_observaciones():
    """Las observaciones aportan keywords aunque el requerimiento sea ambiguo."""
    res = clasificar_centros_gestores(
        requerimiento="Problema reportado por la comunidad",
        observaciones="La luminaria del poste de la esquina lleva varios días apagada",
    )
    assert res["metodo"] == "reglas"
    assert "UAESP" in res["centros_gestores"] or "EMCALI" in res["centros_gestores"]


def test_combina_transcripciones_de_audio():
    """Las transcripciones (lista de dicts con 'texto') deben aportar al matching."""
    res = clasificar_centros_gestores(
        requerimiento="Adjunto nota de voz",
        transcripciones=[{"texto": "Hay un árbol caído bloqueando la entrada"}],
    )
    assert res["metodo"] == "reglas"
    assert "DAGMA" in res["centros_gestores"]


def test_estructura_de_matches():
    """Los matches deben traer la metadata mínima para auditar."""
    res = clasificar_centros_gestores("Sumidero tapado, hay aguas estancadas")
    assert res["matches"], "Debe haber al menos un match"
    m = res["matches"][0]
    for key in ("categoria", "subcategoria", "condicion", "responsables", "score"):
        assert key in m, f"Falta clave {key} en match: {m}"


def test_reglas_devuelven_score_descendente():
    """`aplicar_reglas` debe devolver candidatos ordenados por score desc."""
    candidatos = aplicar_reglas(
        "Árbol caído bloquea la vía y además ramas grandes caídas también"
    )
    scores = [c["score"] for c in candidatos]
    assert scores == sorted(scores, reverse=True)
