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
    ("Hay un poste a punto de caerse, le falta concreto en la base", {"UAESP", "EMCALI"}),
    ("El poste en mal estado frente al parque es peligroso", {"UAESP", "EMCALI"}),
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


# ---------- Tipo de requerimiento y acciones por organismo ----------

def test_tipo_y_acciones_para_poda():
    """Frase de poda debe derivar tipo 'Poda de árboles' y acciones por organismo."""
    res = clasificar_centros_gestores("Solicito poda normal del árbol del parque")
    assert res["tipo_requerimiento"] == "Poda de árboles"
    assert isinstance(res["acciones_por_organismo"], dict)
    assert len(res["acciones_por_organismo"]) >= 1
    # Cada organismo presente en centros_gestores debe estar en acciones_por_organismo
    for org in res["centros_gestores"]:
        assert org in res["acciones_por_organismo"]
        assert isinstance(res["acciones_por_organismo"][org], list)


def test_tipo_alumbrado_publico():
    """Frase de luminaria apagada debe derivar tipo 'Alumbrado público'."""
    res = clasificar_centros_gestores("Luminaria apagada hace 3 días en el poste de la esquina")
    assert res["tipo_requerimiento"] == "Alumbrado público"
    assert res["acciones_por_organismo"]  # no vacío


def test_tipo_emergencias_arboreas():
    """Árbol caído / emergencia arbórea."""
    res = clasificar_centros_gestores("Se cayó un árbol grande en la cuadra y bloquea el paso")
    assert res["tipo_requerimiento"] == "Emergencias arbóreas"


def test_tipo_recoleccion_residuos():
    """No pasa el carro de la basura → recolección de residuos sólidos."""
    res = clasificar_centros_gestores("No pasa el carro de la basura desde hace una semana")
    assert res["tipo_requerimiento"] == "Recolección de residuos sólidos"


def test_tipo_otros_cuando_no_hay_match():
    """Sin match → tipo 'Otros' y acciones vacías."""
    res = clasificar_centros_gestores("xkjsdh wqe rty zzz random gibberish 12345")
    if res["metodo"] == "ninguno":
        assert res["tipo_requerimiento"] == "Otros"
        assert res["acciones_por_organismo"] == {}


def test_matches_incluyen_accion():
    """Cada match del clasificador por reglas debe incluir la clave 'accion'."""
    res = clasificar_centros_gestores("Luminaria apagada en el parque")
    assert res["matches"]
    for m in res["matches"]:
        assert "accion" in m


def test_acciones_deduplicadas_por_organismo():
    """Las acciones por organismo no deben tener duplicados."""
    res = clasificar_centros_gestores(
        "Luminaria apagada en el poste, el poste también está apagado y la luminaria no sirve"
    )
    for org, acciones in res["acciones_por_organismo"].items():
        assert len(acciones) == len(set(acciones)), (
            f"Acciones duplicadas para {org}: {acciones}"
        )
