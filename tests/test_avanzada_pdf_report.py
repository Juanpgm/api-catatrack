"""
Tests del generador de informe PDF de Avanzada Diagnóstica — CataTrack.

Corre totalmente offline (sin Firebase, sin red): las URLs de fotos y los
tiles de OpenStreetMap fallarán al intentar descargarse en el entorno de
test, y el generador debe tolerarlo (omite fotos/mapa, nunca revienta la
generación del PDF completo).
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.utils.avanzada_pdf_generator import (
    _descargar_fotos_concurrente,
    _extraer_drive_file_id,
    _formatear_fecha_larga,
    _parsear_coordenadas,
    _url_imagen_descargable,
    generar_reporte_avanzada,
)


_AVANZADA_COMPLETA = {
    "client_id": "avanzada-test-001",
    "nombre_avanzada": "Comuna 2 - (Parque La Flora)",
    "fecha": "2026-06-05",
    "estrategia": "Plan de Choque",
    "sector": "Parque la Flora",
    "comuna": "COMUNA 2",
    "barrio": "La Flora",
    "direccion": "Cl. 47 Nte. #4bn-85, Cali",
    "coordenadas": "3.483706, -76.522674",
    "encargados": ["Cristian Andres Toledo — Secretaría de Gobierno"],
    "asistentes": [
        {
            "nombre": "Anderson Arroyo",
            "organismo": "DAGMA",
            "celular": "3103533518",
            "correo": "anderson@example.com",
        },
    ],
    "foto_equipo_url": None,
    "numero": 1,
}

_REQUERIMIENTOS = [
    {
        "id": "req-0",
        "req_index": 0,
        "entidad": "Bienestar Social - Secretaría de Bienestar Social",
        "categoria": "Habitante de calle",
        "categoria_personalizada": None,
        "requerimiento": "Presencia de 2 habitantes de calle",
        "ubicacion": "Cl. 47 Nte. #4bn-85, Cali",
        "coordenadas": "3.483850, -76.522668",
        "fotos_urls": ["https://catatrack-photos.s3.amazonaws.com/avanzadas/x/requerimientos/0/foto.jpg"],
    },
    {
        "id": "req-1",
        "req_index": 1,
        "entidad": "UAESP - Unidad Administrativa Especial de Servicios Públicos",
        "categoria": "Barrido y limpieza",
        "categoria_personalizada": None,
        "requerimiento": "Zona con residuos",
        "ubicacion": "Cl. 47 Nte. #4bn-85, Cali",
        "coordenadas": "3.483796, -76.522663",
        "fotos_urls": [],
    },
]


def test_genera_bytes_de_pdf():
    """generar_reporte_avanzada debe devolver bytes que comiencen con la firma PDF."""
    pdf = generar_reporte_avanzada(_AVANZADA_COMPLETA, _REQUERIMIENTOS)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"


def test_pdf_sin_requerimientos():
    """Una avanzada sin requerimientos debe generar un PDF válido igualmente."""
    pdf = generar_reporte_avanzada(_AVANZADA_COMPLETA, [])
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500


def test_pdf_sin_asistentes_ni_encargados():
    """Campos opcionales vacíos no deben romper la generación."""
    avanzada_minima = dict(_AVANZADA_COMPLETA, asistentes=[], encargados=[])
    pdf = generar_reporte_avanzada(avanzada_minima, _REQUERIMIENTOS)
    assert pdf[:4] == b"%PDF"


def test_pdf_campos_ausentes():
    """El generador debe tolerar una avanzada mínima (sin sector, sin fotos)."""
    avanzada_minima = {
        "client_id": "avanzada-min",
        "nombre_avanzada": "Avanzada mínima",
        "fecha": "2026-01-01",
        "estrategia": "Plan de Choque",
        "comuna": "COMUNA 1",
        "barrio": "Centro",
        "direccion": "Calle 1",
        "coordenadas": "3.45, -76.53",
    }
    req_minimo = {
        "id": "req-min",
        "req_index": 0,
        "entidad": "EMCALI",
        "requerimiento": "Poda de árbol",
        "ubicacion": "Calle 1",
    }
    pdf = generar_reporte_avanzada(avanzada_minima, [req_minimo])
    assert pdf[:4] == b"%PDF"


def test_pdf_multiples_entidades_sin_red_omite_mapa_sin_romper():
    """Con varias entidades y coordenadas válidas, sin red disponible el mapa
    se omite pero el resto del informe se genera sin errores."""
    reqs = []
    entidades = ["Bienestar Social", "UAESP", "EMCALI", "DAGMA"]
    for i in range(8):
        reqs.append({
            "id": f"req-{i}",
            "req_index": i,
            "entidad": entidades[i % len(entidades)],
            "categoria": "Categoría genérica",
            "requerimiento": f"Requerimiento número {i}",
            "ubicacion": "Cl. 47 Nte, Cali",
            "coordenadas": f"3.4{i}, -76.5{i}",
            "fotos_urls": [],
        })
    pdf = generar_reporte_avanzada(_AVANZADA_COMPLETA, reqs)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


def test_pdf_tamano_razonable():
    pdf = generar_reporte_avanzada(_AVANZADA_COMPLETA, _REQUERIMIENTOS)
    assert 500 <= len(pdf) <= 5_000_000


# ──────────────────────────────────────────────────────────────────────────────
# Helpers puros
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,esperado", [
    ("https://drive.google.com/file/d/ABC123/view?usp=drivesdk", "ABC123"),
    ("https://drive.google.com/open?id=XYZ789", "XYZ789"),
    ("https://catatrack-photos.s3.amazonaws.com/avanzadas/x/foto.jpg", None),
    (None, None),
    ("", None),
])
def test_extraer_drive_file_id(url, esperado):
    assert _extraer_drive_file_id(url) == esperado


def test_url_imagen_descargable_s3_sin_cambios():
    url = "https://catatrack-photos.s3.amazonaws.com/avanzadas/x/foto.jpg"
    assert _url_imagen_descargable(url) == url


def test_url_imagen_descargable_drive_reescrita():
    url = "https://drive.google.com/file/d/ABC123/view?usp=drivesdk"
    assert "thumbnail?id=ABC123" in _url_imagen_descargable(url)


@pytest.mark.parametrize("valor,esperado", [
    ("3.483706, -76.522674", (3.483706, -76.522674)),
    ("91, 0", None),
    ("no-son-coordenadas", None),
    (None, None),
    ("3.4, -76.5, 1", None),
])
def test_parsear_coordenadas(valor, esperado):
    assert _parsear_coordenadas(valor) == esperado


def test_formatear_fecha_larga():
    assert _formatear_fecha_larga("2026-06-05") == "Viernes, 5 de junio de 2026"


def test_formatear_fecha_larga_invalida():
    assert _formatear_fecha_larga("no-es-fecha") == "no-es-fecha"
    assert _formatear_fecha_larga(None) == "—"


# ──────────────────────────────────────────────────────────────────────────────
# Regresión de performance — las fotos deben descargarse en paralelo, no una
# por una. Una avanzada real (25+ requerimientos con varias fotos cada uno)
# tardaba 30-40s secuencial, tiempo suficiente para expirar el proxy delante
# de la API y que el usuario viera "No se pudo generar el PDF".
# ──────────────────────────────────────────────────────────────────────────────

def test_descargar_fotos_concurrente_no_es_secuencial():
    urls = [f"https://example.com/foto-{i}.jpg" for i in range(12)]

    def _lenta(url):
        time.sleep(0.05)
        return b"fake-jpeg-bytes"

    with patch("app.utils.avanzada_pdf_generator._descargar_y_normalizar_foto", side_effect=_lenta):
        t0 = time.time()
        resultado = _descargar_fotos_concurrente(urls)
        elapsed = time.time() - t0

    assert len(resultado) == 12
    # Secuencial tomaría ~0.6s (12 * 0.05s); en paralelo debe ser una fracción de eso.
    assert elapsed < 0.35, f"la descarga tardó {elapsed:.2f}s -- ¿sigue siendo secuencial?"


def test_descargar_fotos_concurrente_deduplica_urls_repetidas():
    llamadas = []

    def _contar(url):
        llamadas.append(url)
        return b"fake-jpeg-bytes"

    urls = ["https://example.com/a.jpg", "https://example.com/a.jpg", "https://example.com/b.jpg"]
    with patch("app.utils.avanzada_pdf_generator._descargar_y_normalizar_foto", side_effect=_contar):
        resultado = _descargar_fotos_concurrente(urls)

    assert len(llamadas) == 2
    assert set(resultado.keys()) == {"https://example.com/a.jpg", "https://example.com/b.jpg"}


def test_descargar_fotos_concurrente_omite_fallidas():
    def _mixta(url):
        if "falla" in url:
            return None
        return b"fake-jpeg-bytes"

    urls = ["https://example.com/ok.jpg", "https://example.com/falla.jpg"]
    with patch("app.utils.avanzada_pdf_generator._descargar_y_normalizar_foto", side_effect=_mixta):
        resultado = _descargar_fotos_concurrente(urls)

    assert list(resultado.keys()) == ["https://example.com/ok.jpg"]


def test_pdf_25_requerimientos_con_fotos_es_razonablemente_rapido():
    """Regresión del bug: sin red disponible, un volumen realista de fotos
    (25 requerimientos x 2 fotos) debía tardar segundos, no decenas de
    segundos, incluso cuando cada descarga falla (peor caso: todas fallan
    y aun así el generador no debe demorarse esperándolas secuencialmente)."""
    reqs = []
    for i in range(25):
        reqs.append({
            "id": f"req-{i}", "req_index": i,
            "entidad": ["Bienestar Social", "UAESP", "EMCALI"][i % 3],
            "categoria": "Categoría genérica",
            "requerimiento": f"Requerimiento {i}",
            "ubicacion": "Cl. 47 Nte, Cali",
            "coordenadas": f"3.4{i % 9}, -76.52{i % 9}",
            "fotos_urls": [
                f"https://catatrack-photos.s3.amazonaws.com/avanzadas/x/req/{i}/a.jpg",
                f"https://catatrack-photos.s3.amazonaws.com/avanzadas/x/req/{i}/b.jpg",
            ],
        })

    t0 = time.time()
    pdf = generar_reporte_avanzada(_AVANZADA_COMPLETA, reqs)
    elapsed = time.time() - t0

    assert pdf[:4] == b"%PDF"
    assert elapsed < 10, f"generación tardó {elapsed:.2f}s sin red -- revisar paralelismo de descargas"
