"""
Tests del generador de informe PDF de visita — CataTrack.

Valida la función ``generar_reporte_visita`` de forma totalmente offline
(sin Firebase ni red), comprobando que el PDF resultante sea un archivo
PDF válido con el contenido esperado.
"""
from __future__ import annotations

import pytest

from app.utils.pdf_generator import generar_reporte_visita


# ──────────────────────────────────────────────────────────────────────────────
# Datos de muestra reutilizables
# ──────────────────────────────────────────────────────────────────────────────

_VISITA_COMPLETA = {
    "id": "visita-test-001",
    "upid": "UP-PILOTO-01",
    "unidad_proyecto": {"nombre": "Comunidad El Piloto"},
    "fecha_visita": "05/06/2026",
    "hora_inicio": "08:00",
    "hora_fin": "12:00",
    "estado": "finalizada",
    "colaboradores": [
        {"nombre": "Ana García"},
        {"nombre": "Juan Pérez"},
    ],
    "observaciones": "Visita de seguimiento ambiental.",
    "created_at": "2026-06-05T08:00:00-05:00",
    "updated_at": "2026-06-05T12:00:00-05:00",
}

_REQUERIMIENTO_COMPLETO = {
    "id": "req-001",
    "visita_id": "visita-test-001",
    "solicitante": {
        "nombre_completo": "María López",
        "cedula": "1234567890",
        "telefono": "3001234567",
        "email": "maria@example.com",
        "direccion": "Calle 10 # 5-23",
        "barrio_vereda": "El Piloto",
        "comuna_corregimiento": "Comuna 15",
    },
    "centros_gestores": ["DAGMA", "EMCALI"],
    "descripcion": "Árbol caído en vía pública obstruye el paso.",
    "observaciones": "Requiere atención urgente.",
    "direccion": "Calle 10 # 5-23",
    "latitud": "3.4516",
    "longitud": "-76.5320",
    "estado": "nuevo",
    "prioridad": "alta",
    "porcentaje_avance": 0,
    "numero_orfeo": None,
    "encargado": None,
    "fecha_propuesta_solucion": None,
    "created_at": "2026-06-05T08:30:00-05:00",
}


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — El resultado es un PDF válido
# ──────────────────────────────────────────────────────────────────────────────

def test_genera_bytes_de_pdf():
    """generar_reporte_visita debe devolver bytes que comiencen con la firma PDF."""
    pdf = generar_reporte_visita(_VISITA_COMPLETA, [_REQUERIMIENTO_COMPLETO])
    assert isinstance(pdf, bytes), "Debe retornar bytes"
    assert pdf[:4] == b"%PDF", "Los bytes deben comenzar con la firma PDF (%PDF)"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — PDF sin requerimientos (visita vacía)
# ──────────────────────────────────────────────────────────────────────────────

def test_pdf_sin_requerimientos():
    """Visita sin requerimientos debe generar un PDF válido igualmente."""
    pdf = generar_reporte_visita(_VISITA_COMPLETA, [])
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500, "El PDF debe tener un tamaño razonable"


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — PDF con múltiples requerimientos
# ──────────────────────────────────────────────────────────────────────────────

def test_pdf_multiples_requerimientos():
    """El PDF debe generarse sin errores con varios requerimientos."""
    reqs = []
    for i in range(5):
        r = dict(_REQUERIMIENTO_COMPLETO)
        r["id"] = f"req-{i:03d}"
        r["estado"] = ["nuevo", "radicado", "en-gestion", "resuelto", "cancelado"][i]
        r["prioridad"] = ["alta", "media", "baja", "alta", "media"][i]
        reqs.append(r)

    pdf = generar_reporte_visita(_VISITA_COMPLETA, reqs)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — Campos opcionales ausentes (visita mínima)
# ──────────────────────────────────────────────────────────────────────────────

def test_pdf_visita_minima():
    """El generador debe tolerar campos opcionales ausentes sin lanzar excepciones."""
    visita_minima = {
        "id": "visita-minima",
        "upid": "UP-X",
        "fecha_visita": "01/01/2026",
        "estado": "programada",
    }
    req_minimo = {
        "id": "req-min",
        "visita_id": "visita-minima",
        "descripcion": "Problema menor",
        "estado": "nuevo",
    }
    pdf = generar_reporte_visita(visita_minima, [req_minimo])
    assert pdf[:4] == b"%PDF"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5 — PDF tiene tamaño razonable (no vacío ni excesivamente grande)
# ──────────────────────────────────────────────────────────────────────────────

def test_pdf_tamano_razonable():
    """El PDF de una visita típica debe tener entre 2 KB y 5 MB."""
    pdf = generar_reporte_visita(_VISITA_COMPLETA, [_REQUERIMIENTO_COMPLETO])
    assert 2_000 <= len(pdf) <= 5_000_000, (
        f"Tamaño inesperado del PDF: {len(pdf)} bytes"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 6 — Todos los estados de requerimiento se procesan sin error
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("estado", [
    "nuevo", "radicado", "en-gestion", "asignado",
    "en-proceso", "resuelto", "cerrado", "cancelado",
])
def test_pdf_todos_estados_requerimiento(estado):
    """Cada estado válido de requerimiento debe generar un PDF sin errores."""
    req = dict(_REQUERIMIENTO_COMPLETO)
    req["estado"] = estado
    pdf = generar_reporte_visita(_VISITA_COMPLETA, [req])
    assert pdf[:4] == b"%PDF"


# ──────────────────────────────────────────────────────────────────────────────
# Test 7 — Todos los estados de prioridad se procesan sin error
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("prioridad", ["alta", "media", "baja"])
def test_pdf_todas_prioridades(prioridad):
    """Cada prioridad válida debe generar un PDF sin errores."""
    req = dict(_REQUERIMIENTO_COMPLETO)
    req["prioridad"] = prioridad
    pdf = generar_reporte_visita(_VISITA_COMPLETA, [req])
    assert pdf[:4] == b"%PDF"
