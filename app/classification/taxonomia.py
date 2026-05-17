"""
Taxonomía de requerimientos → centros gestores (`organismos_encargados`).

Esta tabla es la **única fuente de verdad** para el clasificador.
Cada fila representa una condición/caso atendido por uno o más responsables
(equivalente a los `organismos_encargados` que se almacenan en Firestore).

Para añadir nuevos casos: agregar dicts a `TAXONOMIA` con
`responsables`, `categoria`, `subcategoria`, `condicion`, `accion` y
`keywords` (lista de strings o tuplas (string, peso) sin tildes y en
minúsculas para acelerar el matching léxico).
"""

from typing import Dict, List


def _split_responsables(raw: str) -> List[str]:
    """Convierte 'DAGMA / UAESP' → ['DAGMA', 'UAESP']."""
    return [p.strip() for p in raw.split("/") if p.strip()]


# Lista declarativa derivada de la plantilla operativa CataTrack.
# (responsables_raw, categoria, subcategoria, condicion, accion, keywords)
_RAW: List = [
    # ---------- Árboles ----------
    ("DAGMA", "Árboles", "Emergencia arbórea", "Árbol enfermo", "Atención prioritaria",
     ["arbol enfermo", "arbol enferma", "enfermedad arbol", "arbol con plaga", "arbol podrido", "arbol marchito"]),
    ("DAGMA", "Árboles", "Emergencia arbórea", "Árbol caído/volcado", "Atención prioritaria",
     ["arbol caido", "arbol volcado", "se cayo un arbol", "arbol tumbado", "arbol derribado", "arbol en el suelo"]),
    ("DAGMA", "Árboles", "Emergencia arbórea", "Ramas grandes caídas", "Atención prioritaria",
     ["rama caida", "ramas caidas", "rama grande", "se cayo una rama", "ramas en la via", "rama partida"]),
    ("DAGMA", "Árboles", "Emergencia arbórea", "Árbol notable", "Evaluación especializada",
     ["arbol notable", "arbol patrimonial", "arbol historico", "arbol monumental"]),
    ("DAGMA", "Árboles", "Emergencia arbórea", "Raíces con riesgo", "Evaluación y mitigación",
     ["raices arbol", "raiz levantada", "raices peligrosas", "raiz andenes", "raices andenes", "raiz daña anden"]),
    ("DAGMA", "Árboles", "Emergencia arbórea", "Árbol seco", "Reposición",
     ["arbol seco", "arbol muerto", "arbol sin hojas"]),
    ("EMCALI", "Árboles", "Poda de árboles", "Árbol energizado", "Poda especializada",
     ["arbol energizado", "arbol cables", "arbol en cables", "rama cables", "cables electricos", "redes electricas", "enredado en los cables", "enredado en cables", "arbol redes electricas"]),
    ("UAESP", "Árboles", "Poda de árboles", "Poda normal", "Poda mediante operador de aseo",
     ["poda arbol", "podar arbol", "podar un arbol", "necesita poda", "poda normal", "poda preventiva"]),
    ("DAGMA", "Árboles", "Poda de árboles", "Autorización", "Autorizar intervención",
     ["permiso de poda", "autorizacion poda", "permiso para podar", "autorizar tala", "permiso tala"]),

    # ---------- Arbustos ----------
    ("DAGMA", "Arbustos", "Poda arbustos", "Altura superior al límite", "Intervención",
     ["arbusto alto", "poda arbusto alto", "arbusto grande", "arbusto sobrepasa"]),
    ("UAESP", "Arbustos", "Poda arbustos", "Altura inferior al límite", "Intervención",
     ["poda arbusto", "podar arbusto", "arbusto bajo", "setos bajos"]),
    ("DAGMA / UAESP", "Arbustos", "Retiro", "Requiere concertación", "Concertar con comunidad",
     ["retiro arbusto", "quitar arbusto", "remover arbusto", "tala arbusto"]),

    # ---------- Siembra indiscriminada ----------
    ("DAGMA", "Siembra indiscriminada", "Control vegetación", "Especie invasora", "Retiro obligatorio",
     ["especie invasora", "planta invasora", "vegetacion invasora", "siembra indebida"]),
    ("DAGMA", "Siembra indiscriminada", "Control vegetación", "Altura genera afectación", "Traslado o retiro",
     ["vegetacion alta", "siembra afecta", "planta afecta vivienda", "vegetacion daña"]),

    # ---------- Recolección basuras ----------
    ("UAESP", "Recolección basuras", "RSD", "Residuos sólidos domiciliarios", "Recolección ordinaria",
     ["basura", "basuras", "recoleccion basura", "no pasa el carro de la basura", "no recogen basura", "residuos domiciliarios", "bolsa de basura", "no recolectan"]),
    ("UAESP", "Recolección basuras", "RCD", "Residuos construcción y demolición", "Recolección con pago",
     ["escombros", "residuos construccion", "demolicion", "rcd", "ladrillos botados", "cemento botado"]),
    ("UAESP", "Recolección basuras", "Voluminosos", "Residuos voluminosos", "Recolección con pago",
     ["voluminoso", "voluminosos", "colchon botado", "mueble botado", "nevera botada", "sofa botado", "electrodomestico botado"]),
    ("UAESP / DAGMA / EMCALI / CVC", "Recolección basuras", "Vegetales", "Residuos vegetales", "Determinar origen",
     ["residuos vegetales", "ramas botadas", "hojas acumuladas", "poda apilada", "vegetacion cortada en la calle"]),

    # ---------- Limpieza pública ----------
    ("UAESP", "Limpieza pública", "Barrido", "Vías y áreas públicas", "Barrido y limpieza",
     ["barrido", "barrer", "limpieza via", "limpieza calle", "calle sucia", "via sucia"]),
    ("UAESP", "Limpieza pública", "Desmoñe", "Pasto en andenes", "Retiro maleza",
     ["pasto anden", "maleza anden", "desmoñe", "desmonte", "monte en el anden", "hierba anden"]),
    ("DAGMA", "Limpieza pública", "Zona verde adoptada", "Empresa adoptante", "Seguimiento mantenimiento",
     ["zona verde adoptada", "empresa adoptante", "adopcion zona verde"]),
    ("UAESP", "Limpieza pública", "Zona verde no adoptada", "Corte de césped", "Mantenimiento",
     ["corte cesped", "cortar cesped", "cesped alto", "zona verde sin mantenimiento", "pasto crecido"]),
    ("DAGMA / UAESP", "Limpieza pública", "Jardines", "Coordinación jardines", "Gestión conjunta",
     ["jardin abandonado", "mantenimiento jardin", "jardin sucio", "jardines publicos"]),

    # ---------- Alumbrado público ----------
    ("UAESP / EMCALI", "Alumbrado público", "Luminaria", "Luminaria apagada", "Reparación",
     ["luminaria", "luminaria apagada", "lampara apagada", "alumbrado apagado", "no hay luz en la calle", "poste sin luz", "luz publica dañada", "bombillo poste"]),
    ("UAESP / EMCALI", "Alumbrado público", "Poste", "Poste dañado", "Reposición e iluminación",
     ["poste dañado", "poste caido", "poste roto", "poste inclinado", "poste partido"]),
    ("UAESP / EMCALI", "Alumbrado público", "Modernización", "Cambio a LED", "Actualización",
     ["cambio a led", "modernizar alumbrado", "actualizar luminaria", "led publico"]),
    ("UAESP", "Alumbrado público", "Luces ornamentales", "Daño ornamental", "Mantenimiento",
     ["luces ornamentales", "luz ornamental", "alumbrado ornamental", "luces parque dañadas"]),

    # ---------- Acueducto y alcantarillado ----------
    ("EMCALI", "Acueducto y alcantarillado", "Sumideros", "Limpieza sumideros", "Limpieza",
     ["sumidero", "sumidero tapado", "rejilla sumidero", "sumidero lleno", "alcantarilla tapada", "alcantarilla obstruida"]),
    ("EMCALI", "Acueducto y alcantarillado", "Tapas", "Reposición tapas", "Reposición",
     ["tapa alcantarilla", "falta tapa", "falta la tapa", "tapa de alcantarilla", "tapa de la alcantarilla", "sin tapa alcantarilla", "alcantarilla sin tapa", "tapa rota alcantarilla"]),
    ("EMCALI", "Acueducto y alcantarillado", "Cámaras", "Nivelación cámaras", "Nivelación",
     ["camara hundida", "nivelacion camara", "camara alcantarillado", "tapa hundida", "camara desnivelada"]),

    # ---------- Habitante de calle ----------
    ("Bienestar Social / SSJ / UAESP", "Habitante de calle", "Cambuches", "Presencia cambuche", "Abordaje + desmonte + recolección",
     ["cambuche", "cambuches", "habitante calle cambuche", "ranchada", "ranchadas"]),
    ("Bienestar Social", "Habitante de calle", "Oferta institucional", "Abordaje social", "Oferta de servicios",
     ["habitante de calle", "habitantes calle", "indigente", "persona en condicion de calle", "abordaje social"]),

    # ---------- Invasión espacio público ----------
    ("SSJ / Desarrollo Económico / Salud", "Invasión espacio público", "Ventas informales", "Ocupación informal", "Control y formalización",
     ["venta informal", "ventas ambulantes", "vendedor ambulante", "ocupacion anden", "carretilla anden", "ventas calle"]),
    ("SSJ / DAGMA / Salud", "Invasión espacio público", "Establecimientos", "Ocupación comercial", "Control e inspección",
     ["ocupacion comercial", "negocio invade", "establecimiento invade anden", "mesas en el anden", "sillas en anden"]),

    # ---------- Ruido ----------
    ("SSJ / Policía / DAGMA", "Ruido", "Establecimientos", "Ruido comercial", "Control",
     ["ruido bar", "ruido en bar", "ruido en el bar", "en el bar", "en la discoteca", "ruido discoteca", "ruido en discoteca", "ruido en la discoteca", "ruido establecimiento", "ruido en establecimiento", "ruido comercial", "musica alta bar", "musica alta en el bar", "musica alta discoteca", "musica alta en la discoteca", "fiesta en bar", "fiesta en discoteca"]),
    ("SSJ / Policía", "Ruido", "Viviendas", "Ruido residencial", "Control",
     ["ruido vecino", "ruido del vecino", "ruido vivienda", "musica alta vecino", "musica alta del vecino", "musica del vecino", "fiesta vecino", "fiesta del vecino", "ruido casa"]),
    ("SSJ / Policía", "Ruido", "Ventas informales", "Ruido informal", "Control",
     ["ruido vendedor", "perifoneo", "ruido venta ambulante", "altavoz vendedor"]),

    # ---------- Movilidad ----------
    ("Secretaría de Movilidad", "Movilidad", "Señalización", "Ausencia o daño señalización", "Instalación o reposición",
     ["señalizacion", "señal de transito", "señal vial", "señal caida", "falta señal", "señal borrada", "señalizacion dañada"]),
    ("Secretaría de Movilidad", "Movilidad", "Bolardos", "Bolardos dañados", "Mantenimiento",
     ["bolardo", "bolardos", "bolardo dañado", "bolardo roto"]),
    ("Secretaría de Movilidad", "Movilidad", "Reductores", "Reductor dañado", "Mantenimiento",
     ["reductor", "reductor de velocidad", "policia acostado", "reductor dañado"]),
    ("Secretaría de Movilidad", "Movilidad", "Semáforos", "Semáforo apagado", "Reparación",
     ["semaforo", "semaforo apagado", "semaforo dañado", "semaforo no funciona"]),

    # ---------- Otros ----------
    ("UAESP", "Otros", "Barandales", "Barandal en mal estado", "Reparación o pintura",
     ["barandal", "baranda dañada", "barandal roto", "barandal oxidado"]),
    ("Participación", "Otros", "Bordillos", "Pintura bordillos", "Pintura",
     ["pintura bordillo", "pintura del bordillo", "bordillo sin pintar", "pintar bordillo", "bordillo descolorido", "bordillo descolorida", "bordillos descoloridos"]),
]


TAXONOMIA: List[Dict] = [
    {
        "id": idx,
        "responsables": _split_responsables(responsables_raw),
        "responsables_raw": responsables_raw,
        "categoria": categoria,
        "subcategoria": subcategoria,
        "condicion": condicion,
        "accion": accion,
        "keywords": keywords,
        "descripcion_canonica": f"{categoria} - {subcategoria} - {condicion} - {accion}",
    }
    for idx, (responsables_raw, categoria, subcategoria, condicion, accion, keywords) in enumerate(_RAW)
]


RESPONSABLES_CONOCIDOS = sorted({r for fila in TAXONOMIA for r in fila["responsables"]})


def listar_descripciones_canonicas() -> List[str]:
    """Devuelve la lista de descripciones canónicas en el mismo orden que TAXONOMIA."""
    return [f["descripcion_canonica"] for f in TAXONOMIA]
