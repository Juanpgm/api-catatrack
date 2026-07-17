"""
Generador de Informe PDF de Avanzada Diagnóstica — CataTrack.

Reproduce, con reportlab + Pillow, la estructura del informe de referencia
usado por el equipo de campo (encabezado + datos de la jornada, asistentes,
requerimientos agrupados por entidad con sus fotos, resumen por entidad y un
mapa general de recorrido). El mapa se genera en el momento a partir de
mosaicos (tiles) públicos de OpenStreetMap — sin API key ni costo — con
marcadores coloreados por entidad dibujados encima con Pillow.

Todo el módulo tolera fallas de red (fotos que no descargan, tiles que no
responden): en vez de fallar la generación completa, cada pieza que no se
puede resolver se omite (nunca se fabrica un marcador o una foto falsa), sea
un placeholder discreto para fotos, sea la página de mapa completa.
"""
from __future__ import annotations

import io
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import httpx
import reportlab
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Zona horaria Colombia (UTC-5) — mismo criterio que pdf_generator.py.
_COL_TZ = timezone(timedelta(hours=-5))

# ──────────────────────────────────────────────────────────────────────────────
# Paleta de colores institucional
# ──────────────────────────────────────────────────────────────────────────────
_VERDE_CALI = colors.HexColor("#1a6b3c")
_VERDE_CLARO = colors.HexColor("#e8f5e9")
_GRIS_TEXTO = colors.HexColor("#333333")
_GRIS_BORDE = colors.HexColor("#cccccc")

# Colores cíclicos asignados a cada entidad (orden de primera aparición) para
# los badges de sección y los marcadores del mapa.
_PALETA_ENTIDADES = [
    "#e53e3e", "#38a169", "#805ad5", "#dd6b20",
    "#d69e2e", "#319795", "#3182ce", "#d53f8c",
]

# reportlab empaqueta Bitstream Vera (TTF real) — la reutilizamos para
# dibujar los números de los marcadores con Pillow sin depender de fuentes
# del sistema operativo (no garantizadas en el servidor de despliegue).
_FONT_PATH = os.path.join(os.path.dirname(reportlab.__file__), "fonts", "VeraBd.ttf")

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_DRIVE_HOSTS = {"drive.google.com", "docs.google.com"}

# Timeouts cortos: una avanzada puede tener decenas de fotos + mosaicos de
# mapa, y una sola URL colgada no debe demorar la generación del PDF entero.
_HTTP_TIMEOUT = httpx.Timeout(connect=3.0, read=6.0, write=6.0, pool=3.0)

# User-Agent identificable, requerido por la política de uso de tiles de
# OpenStreetMap (https://operations.osmfoundation.org/policies/tiles/).
_OSM_USER_AGENT = "CataTrack-Alcaldia-Cali-PDF/1.0 (informe de avanzada diagnostica)"

_MAX_FOTOS_POR_REQUERIMIENTO_PDF = 4
_MAX_FOTO_ANCHO_PX = 900

# Las fotos se descargan en paralelo (I/O-bound: el GIL no es cuello de
# botella acá). Una avanzada real puede traer 25+ requerimientos con 2-4
# fotos cada uno -- secuencial, eso significaba 30-40s de bloqueo sincrónico
# por request, tiempo suficiente para expirar el proxy/gateway delante de la
# API y que el frontend viera un error genérico de red.
_MAX_DESCARGAS_CONCURRENTES = 20

_MAPA_ANCHO_PX = 900
_MAPA_ALTO_PX = 620
_TILE_SIZE = 256


def now_colombia():
    from datetime import datetime
    return datetime.now(_COL_TZ)


# ──────────────────────────────────────────────────────────────────────────────
# Estilos
# ──────────────────────────────────────────────────────────────────────────────

def _estilos() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    estilos: Dict[str, ParagraphStyle] = {}

    estilos["titulo"] = ParagraphStyle(
        "titulo", parent=base["Title"], fontSize=17, textColor=_GRIS_TEXTO,
        spaceAfter=2, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    estilos["subtitulo"] = ParagraphStyle(
        "subtitulo", parent=base["Normal"], fontSize=12, textColor=_GRIS_TEXTO,
        spaceAfter=6, alignment=TA_CENTER, fontName="Helvetica-Bold",
    )
    estilos["seccion"] = ParagraphStyle(
        "seccion", parent=base["Heading2"], fontSize=12, textColor=_GRIS_TEXTO,
        spaceAfter=6, spaceBefore=10, fontName="Helvetica-Bold",
    )
    estilos["entidad_titulo"] = ParagraphStyle(
        "entidad_titulo", parent=base["Normal"], fontSize=10.5,
        textColor=_GRIS_TEXTO, fontName="Helvetica-Bold",
    )
    estilos["label"] = ParagraphStyle(
        "label", parent=base["Normal"], fontSize=8.5, textColor=_VERDE_CALI,
        fontName="Helvetica-Bold",
    )
    estilos["valor"] = ParagraphStyle(
        "valor", parent=base["Normal"], fontSize=9, textColor=_GRIS_TEXTO,
    )
    estilos["req_titulo"] = ParagraphStyle(
        "req_titulo", parent=base["Normal"], fontSize=10, textColor=_VERDE_CALI,
        fontName="Helvetica-Bold", spaceAfter=3,
    )
    estilos["campo"] = ParagraphStyle(
        "campo", parent=base["Normal"], fontSize=9, textColor=_GRIS_TEXTO, leading=12,
    )
    estilos["pie"] = ParagraphStyle(
        "pie", parent=base["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER,
    )
    estilos["leyenda"] = ParagraphStyle(
        "leyenda", parent=base["Normal"], fontSize=8.5, textColor=_GRIS_TEXTO,
    )

    return estilos


def _formatear_fecha_larga(fecha_iso: Optional[str]) -> str:
    """Formatea 'YYYY-MM-DD' como 'Viernes, 5 de junio de 2026'. Ante
    cualquier valor no parseable, retorna el string original (o "—")."""
    if not fecha_iso or not isinstance(fecha_iso, str):
        return "—"
    try:
        anio, mes, dia = fecha_iso[:10].split("-")
        d = date(int(anio), int(mes), int(dia))
    except (ValueError, IndexError):
        return fecha_iso

    nombre_dia = _DIAS[d.weekday()].capitalize()
    nombre_mes = _MESES[d.month - 1]
    return f"{nombre_dia}, {d.day} de {nombre_mes} de {d.year}"


def _fila_dato(label: str, valor: Any, estilos: Dict) -> List:
    return [
        Paragraph(label, estilos["label"]),
        Paragraph(str(valor) if valor not in (None, "") else "—", estilos["valor"]),
    ]


def _tabla_info(filas: List[List], col_widths: Optional[List] = None) -> Table:
    if col_widths is None:
        col_widths = [3.2 * cm, 5.3 * cm, 3.2 * cm, 5.3 * cm]
    t = Table(filas, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.75, _GRIS_BORDE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, _GRIS_BORDE),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    return t


# ──────────────────────────────────────────────────────────────────────────────
# Fotos: descarga + normalización (S3 directo o thumbnail de Drive)
# ──────────────────────────────────────────────────────────────────────────────

def _extraer_drive_file_id(url: str) -> Optional[str]:
    """Extrae el file id de un link de Google Drive compartido, en
    cualquiera de sus formas usuales. Espejo de extractDriveFileId() en
    src/lib/media-urls.ts — mismo contrato, distinto lenguaje."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    if parsed.hostname not in _DRIVE_HOSTS:
        return None

    m = re.search(r"/file/d/([^/]+)", parsed.path)
    if m:
        return m.group(1)

    qs = parse_qs(parsed.query)
    if qs.get("id"):
        return qs["id"][0]

    return None


def _url_imagen_descargable(url: str) -> str:
    """Reescribe un link de Drive al endpoint 'thumbnail' (sirve bytes de
    imagen real); todo lo demás (S3, http) se retorna sin cambios."""
    file_id = _extraer_drive_file_id(url)
    if not file_id:
        return url
    return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1000"


def _descargar_y_normalizar_foto(url: str) -> Optional[bytes]:
    """Descarga una foto y la normaliza a JPEG acotado en ancho, para que el
    PDF no herede el peso original de fotos de celular. Retorna None ante
    cualquier falla (red, URL rota, contenido no-imagen) — el llamador debe
    tolerar la ausencia en vez de romper el reporte completo.
    """
    if not url:
        return None
    try:
        destino = _url_imagen_descargable(url)
        resp = httpx.get(
            destino, timeout=_HTTP_TIMEOUT, follow_redirects=True,
            headers={"User-Agent": _OSM_USER_AGENT},
        )
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        img = img.convert("RGB")
        if img.width > _MAX_FOTO_ANCHO_PX:
            ratio = _MAX_FOTO_ANCHO_PX / img.width
            img = img.resize((_MAX_FOTO_ANCHO_PX, max(1, int(img.height * ratio))))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return buf.getvalue()
    except Exception:
        return None


def _descargar_fotos_concurrente(urls: List[str]) -> Dict[str, bytes]:
    """Descarga y normaliza una lista de URLs de fotos en paralelo, deduplicando
    por URL. Retorna solo las que se pudieron resolver — el llamador ya
    tolera ausencias (ver ``_descargar_y_normalizar_foto``)."""
    urls_unicas = list(dict.fromkeys(u for u in urls if u))
    if not urls_unicas:
        return {}

    resultado: Dict[str, bytes] = {}
    with ThreadPoolExecutor(max_workers=_MAX_DESCARGAS_CONCURRENTES) as executor:
        for url, foto_bytes in zip(urls_unicas, executor.map(_descargar_y_normalizar_foto, urls_unicas)):
            if foto_bytes:
                resultado[url] = foto_bytes
    return resultado


def _foto_flowable(foto_bytes: bytes, max_w_cm: float, max_h_cm: float) -> Optional[RLImage]:
    try:
        img = Image.open(io.BytesIO(foto_bytes))
        w_px, h_px = img.size
        if not w_px or not h_px:
            return None
        ratio = min((max_w_cm * cm) / w_px, (max_h_cm * cm) / h_px)
        return RLImage(io.BytesIO(foto_bytes), width=w_px * ratio, height=h_px * ratio)
    except Exception:
        return None


def _fotos_grid(fotos_bytes: List[bytes], max_w_cm: float, max_h_cm: float) -> Optional[Table]:
    """Arma una grilla de hasta 2 fotos por fila (espejo del layout lado a
    lado del informe de referencia)."""
    flowables = [f for f in (_foto_flowable(b, max_w_cm, max_h_cm) for b in fotos_bytes) if f]
    if not flowables:
        return None

    filas = []
    for i in range(0, len(flowables), 2):
        par = flowables[i:i + 2]
        while len(par) < 2:
            par.append(Paragraph("", getSampleStyleSheet()["Normal"]))
        filas.append(par)

    t = Table(filas, colWidths=[max_w_cm * cm + 0.2 * cm] * 2, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# ──────────────────────────────────────────────────────────────────────────────
# Mapa general de recorrido (mosaicos OpenStreetMap + marcadores Pillow)
# ──────────────────────────────────────────────────────────────────────────────

def _parsear_coordenadas(valor: Any) -> Optional[Tuple[float, float]]:
    """Mismo contrato que ``_parsear_coordenadas`` en avanzadas_routes.py,
    duplicado a propósito: este módulo de utilidades no debe importar desde
    la capa de rutas (evita una dependencia invertida / ciclo de imports)."""
    if not isinstance(valor, str):
        return None
    partes = [p.strip() for p in valor.split(",")]
    if len(partes) != 2 or not partes[0] or not partes[1]:
        return None
    try:
        lat = float(partes[0])
        lng = float(partes[1])
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None
    return (lat, lng)


def _lonlat_a_pixel_global(lng: float, lat: float, zoom: int) -> Tuple[float, float]:
    """Proyección Web Mercator estándar (misma que usan los tiles slippy-map
    de OSM/Leaflet/Google): (lon, lat) -> coordenada de píxel en el plano
    global de ese nivel de zoom."""
    tam_mundo = _TILE_SIZE * (2 ** zoom)
    x = (lng + 180.0) / 360.0 * tam_mundo
    lat_rad = math.radians(max(min(lat, 85.05), -85.05))
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * tam_mundo
    return x, y


def _elegir_zoom(min_lat: float, max_lat: float, min_lng: float, max_lng: float) -> int:
    """El mayor zoom (más detalle) en el que el bbox completo todavía cabe
    dentro del lienzo objetivo."""
    for zoom in range(18, 1, -1):
        x0, y0 = _lonlat_a_pixel_global(min_lng, max_lat, zoom)
        x1, y1 = _lonlat_a_pixel_global(max_lng, min_lat, zoom)
        if (x1 - x0) <= _MAPA_ANCHO_PX and (y1 - y0) <= _MAPA_ALTO_PX:
            return zoom
    return 2


def _descargar_mosaico(crop_left: float, crop_top: float, zoom: int) -> Optional[Image.Image]:
    """Descarga los tiles de OSM que cubren el rectángulo objetivo y los
    pega en un lienzo. Retorna None si NINGÚN tile pudo descargarse (sin
    red, por ejemplo) para que el llamador omita la página de mapa en vez
    de mostrar un lienzo en blanco."""
    n_tiles = 2 ** zoom
    tile_min_x = int(crop_left // _TILE_SIZE)
    tile_min_y = int(crop_top // _TILE_SIZE)
    tile_max_x = int((crop_left + _MAPA_ANCHO_PX) // _TILE_SIZE)
    tile_max_y = int((crop_top + _MAPA_ALTO_PX) // _TILE_SIZE)

    lienzo = Image.new(
        "RGB",
        ((tile_max_x - tile_min_x + 1) * _TILE_SIZE, (tile_max_y - tile_min_y + 1) * _TILE_SIZE),
        "#e8e8e8",
    )

    coords_tiles = [
        (tx, ty)
        for tx in range(tile_min_x, tile_max_x + 1) if 0 <= tx < n_tiles
        for ty in range(tile_min_y, tile_max_y + 1) if 0 <= ty < n_tiles
    ]

    def _descargar_tile(coords: Tuple[int, int]) -> Optional[Tuple[int, int, Image.Image]]:
        tx, ty = coords
        try:
            resp = httpx.get(
                f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
                timeout=_HTTP_TIMEOUT, headers={"User-Agent": _OSM_USER_AGENT},
            )
            resp.raise_for_status()
            return tx, ty, Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception:
            return None

    algun_tile_ok = False
    try:
        with ThreadPoolExecutor(max_workers=_MAX_DESCARGAS_CONCURRENTES) as executor:
            for resultado in executor.map(_descargar_tile, coords_tiles):
                if resultado is None:
                    continue
                tx, ty, tile_img = resultado
                lienzo.paste(tile_img, ((tx - tile_min_x) * _TILE_SIZE, (ty - tile_min_y) * _TILE_SIZE))
                algun_tile_ok = True
    except Exception:
        return None

    if not algun_tile_ok:
        return None

    offset_x = int(crop_left) - tile_min_x * _TILE_SIZE
    offset_y = int(crop_top) - tile_min_y * _TILE_SIZE
    return lienzo.crop((offset_x, offset_y, offset_x + _MAPA_ANCHO_PX, offset_y + _MAPA_ALTO_PX))


def _dibujar_marcador(draw: ImageDraw.ImageDraw, x: float, y: float, texto: str, color_hex: str, fuente) -> None:
    radio = 13
    draw.ellipse([x - radio, y - radio, x + radio, y + radio], fill=color_hex, outline="white", width=2)
    bbox = draw.textbbox((0, 0), texto, font=fuente)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((x - tw / 2 - bbox[0], y - th / 2 - bbox[1]), texto, fill="white", font=fuente)


def _generar_mapa_recorrido(puntos: List[Dict[str, Any]]) -> Optional[bytes]:
    """``puntos``: [{"lat", "lng", "numero", "color"}]. Retorna bytes PNG del
    mapa anotado, o None si no hay puntos válidos o si los tiles no se
    pudieron descargar (sin conectividad) — el llamador omite la página."""
    if not puntos:
        return None

    lats = [p["lat"] for p in puntos]
    lngs = [p["lng"] for p in puntos]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    # Relleno proporcional al tramo cubierto; con un solo punto (o puntos
    # coincidentes) el bbox colapsaría a área cero, así que se usa un piso
    # mínimo de relleno (~150m) para dejar el marcador con aire alrededor.
    lat_pad = max((max_lat - min_lat) * 0.15, 0.0015)
    lng_pad = max((max_lng - min_lng) * 0.15, 0.0015)
    min_lat -= lat_pad
    max_lat += lat_pad
    min_lng -= lng_pad
    max_lng += lng_pad

    zoom = _elegir_zoom(min_lat, max_lat, min_lng, max_lng)

    x0, y0 = _lonlat_a_pixel_global(min_lng, max_lat, zoom)
    x1, y1 = _lonlat_a_pixel_global(max_lng, min_lat, zoom)
    centro_x, centro_y = (x0 + x1) / 2, (y0 + y1) / 2
    crop_left = centro_x - _MAPA_ANCHO_PX / 2
    crop_top = centro_y - _MAPA_ALTO_PX / 2

    lienzo = _descargar_mosaico(crop_left, crop_top, zoom)
    if lienzo is None:
        return None

    draw = ImageDraw.Draw(lienzo)
    try:
        fuente_marcador = ImageFont.truetype(_FONT_PATH, 14)
        fuente_atribucion = ImageFont.truetype(_FONT_PATH, 11)
    except Exception:
        fuente_marcador = ImageFont.load_default()
        fuente_atribucion = fuente_marcador

    for p in puntos:
        px, py = _lonlat_a_pixel_global(p["lng"], p["lat"], zoom)
        _dibujar_marcador(draw, px - crop_left, py - crop_top, str(p["numero"]), p["color"], fuente_marcador)

    # Atribución obligatoria por la licencia de datos de OpenStreetMap.
    ancho, alto = lienzo.size
    texto_attr = "© OpenStreetMap contributors"
    bbox = draw.textbbox((0, 0), texto_attr, font=fuente_atribucion)
    tw = bbox[2] - bbox[0]
    draw.rectangle([ancho - tw - 14, alto - 20, ancho, alto], fill="white")
    draw.text((ancho - tw - 8, alto - 17), texto_attr, fill="#333333", font=fuente_atribucion)

    buf = io.BytesIO()
    lienzo.save(buf, format="PNG")
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Reporte principal
# ──────────────────────────────────────────────────────────────────────────────

def generar_reporte_avanzada(
    avanzada: Dict[str, Any],
    requerimientos: List[Dict[str, Any]],
) -> bytes:
    """Genera el PDF del informe de avanzada diagnóstica y lo retorna como
    bytes.

    Parameters
    ----------
    avanzada:
        Documento de la avanzada (campos de AvanzadaOut, sin
        ``requerimientos``).
    requerimientos:
        Lista de requerimientos asociados, ya ordenados por ``req_index``.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.4 * cm, leftMargin=1.4 * cm, topMargin=1.3 * cm, bottomMargin=1.3 * cm,
        title=f"Informe de Avanzada — {avanzada.get('nombre_avanzada', '')}",
        author="CataTrack — Alcaldía de Santiago de Cali",
    )

    estilos = _estilos()
    story: List[Any] = []

    # Todas las fotos (equipo + requerimientos) se descargan en UNA sola
    # tanda concurrente antes de armar el story -- descargarlas una por una
    # a medida que se arma cada sección convertía la generación en decenas
    # de segundos de I/O sincrónico para una avanzada real (ver
    # _MAX_DESCARGAS_CONCURRENTES).
    foto_equipo_url = avanzada.get("foto_equipo_url")
    urls_fotos_requerimientos = [
        u
        for req in requerimientos
        for u in (req.get("fotos_urls") or [])[:_MAX_FOTOS_POR_REQUERIMIENTO_PDF]
    ]
    todas_urls_fotos = ([foto_equipo_url] if foto_equipo_url else []) + urls_fotos_requerimientos
    fotos_cache = _descargar_fotos_concurrente(todas_urls_fotos)

    # ── Encabezado ───────────────────────────────────────────────────────────
    story.append(Paragraph("INFORME DE AVANZADA", estilos["titulo"]))
    story.append(Paragraph(avanzada.get("nombre_avanzada") or "—", estilos["subtitulo"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_VERDE_CALI, spaceAfter=8))

    filas_info = [
        _fila_dato("Fecha", _formatear_fecha_larga(avanzada.get("fecha")), estilos)
        + _fila_dato("Estrategia", avanzada.get("estrategia"), estilos),
        _fila_dato("Sector", avanzada.get("sector"), estilos)
        + _fila_dato("Comuna / Correg.", avanzada.get("comuna"), estilos),
        _fila_dato("Barrio / Vereda", avanzada.get("barrio"), estilos)
        + _fila_dato("Dirección", avanzada.get("direccion"), estilos),
        _fila_dato("Coordenadas inicio", avanzada.get("coordenadas"), estilos)
        + ["", ""],
    ]
    story.append(_tabla_info(filas_info))
    story.append(Spacer(1, 8))

    # ── Foto de equipo + encargados ───────────────────────────────────────────
    encargados = avanzada.get("encargados") or []
    encargados_html = "<br/>".join(f"•&nbsp;&nbsp;{e}" for e in encargados) or "—"
    bloque_encargados = [
        Paragraph("Encargados de la visita:", estilos["label"]),
        Spacer(1, 3),
        Paragraph(encargados_html, estilos["valor"]),
    ]

    foto_equipo_bytes = fotos_cache.get(foto_equipo_url) if foto_equipo_url else None
    foto_equipo_flowable = _foto_flowable(foto_equipo_bytes, 6.2, 4.2) if foto_equipo_bytes else None

    if foto_equipo_flowable:
        fila = Table(
            [[foto_equipo_flowable, bloque_encargados]],
            colWidths=[6.6 * cm, 8.4 * cm],
        )
        fila.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(fila)
    else:
        story.append(bloque_encargados[0])
        story.append(bloque_encargados[2])
    story.append(Spacer(1, 10))

    # ── Asistentes ────────────────────────────────────────────────────────────
    story.append(Paragraph("ASISTENTES A LA AVANZADA", estilos["seccion"]))
    asistentes = avanzada.get("asistentes") or []
    if not asistentes:
        story.append(Paragraph("Sin asistentes registrados.", estilos["valor"]))
    else:
        cabecera = [
            Paragraph("#", estilos["label"]), Paragraph("Nombre", estilos["label"]),
            Paragraph("Organismo", estilos["label"]), Paragraph("Celular", estilos["label"]),
            Paragraph("Correo", estilos["label"]),
        ]
        filas = [cabecera]
        for i, a in enumerate(asistentes, start=1):
            filas.append([
                Paragraph(str(i), estilos["valor"]),
                Paragraph(a.get("nombre") or "—", estilos["valor"]),
                Paragraph(a.get("organismo") or "—", estilos["valor"]),
                Paragraph(a.get("celular") or "—", estilos["valor"]),
                Paragraph(a.get("correo") or "—", estilos["valor"]),
            ])
        t = Table(filas, colWidths=[0.8 * cm, 3.2 * cm, 5.6 * cm, 2.6 * cm, 5.2 * cm], hAlign="LEFT")
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.75, _GRIS_BORDE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, _GRIS_BORDE),
            ("BACKGROUND", (0, 0), (-1, 0), _VERDE_CLARO),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
    story.append(Spacer(1, 10))

    # ── Requerimientos por entidad ────────────────────────────────────────────
    # Se agrupa preservando el orden de primera aparición (por req_index),
    # que es el mismo criterio con el que se asignan los colores del mapa —
    # así la leyenda del mapa y el orden de las secciones coinciden.
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for req in requerimientos:
        entidad = req.get("entidad") or "Sin entidad"
        grupos.setdefault(entidad, []).append(req)

    entidad_color: Dict[str, str] = {
        entidad: _PALETA_ENTIDADES[i % len(_PALETA_ENTIDADES)]
        for i, entidad in enumerate(grupos.keys())
    }

    story.append(Paragraph(f"REQUERIMIENTOS POR ENTIDAD ({len(requerimientos)})", estilos["seccion"]))

    puntos_mapa: List[Dict[str, Any]] = []
    equivalencia_filas: List[Tuple[int, str, str, str]] = []

    if not requerimientos:
        story.append(Paragraph("Esta avanzada no tiene requerimientos registrados.", estilos["valor"]))

    for entidad, reqs in grupos.items():
        color_entidad = entidad_color[entidad]
        cabecera_entidad = Table(
            [[Paragraph(entidad, estilos["entidad_titulo"]), Paragraph(f"{len(reqs)} req.", estilos["valor"])]],
            colWidths=[13 * cm, 3.4 * cm],
        )
        cabecera_entidad.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 1, _VERDE_CALI),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(Spacer(1, 6))
        story.append(cabecera_entidad)

        for req in reqs:
            numero = (req.get("req_index", 0) or 0) + 1
            categoria = req.get("categoria_personalizada") or req.get("categoria") or "—"
            descripcion = req.get("requerimiento") or "—"
            ubicacion = req.get("ubicacion") or "—"
            coordenadas = req.get("coordenadas")

            fotos_urls = (req.get("fotos_urls") or [])[:_MAX_FOTOS_POR_REQUERIMIENTO_PDF]
            fotos_bytes = [b for b in (fotos_cache.get(u) for u in fotos_urls) if b]
            grid_fotos = _fotos_grid(fotos_bytes, 3.9, 3.3) if fotos_bytes else None

            texto_req = [
                Paragraph(f"Requerimiento {numero}", estilos["req_titulo"]),
                Paragraph(f"<b>Categoría:</b> {categoria}", estilos["campo"]),
                Paragraph(f"<b>Descripción:</b> {descripcion}", estilos["campo"]),
                Paragraph(f"<b>Ubicación:</b> {ubicacion}", estilos["campo"]),
                Paragraph(f"<b>Coordenadas:</b> {coordenadas or '—'}", estilos["campo"]),
            ]

            if grid_fotos:
                fila_req = Table(
                    [[texto_req, grid_fotos]],
                    colWidths=[8.6 * cm, 8.0 * cm],
                )
                fila_req.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, _GRIS_BORDE),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]))
                bloque = KeepTogether([fila_req])
            else:
                envoltorio = Table([[texto_req]], colWidths=[16.6 * cm])
                envoltorio.setStyle(TableStyle([
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, _GRIS_BORDE),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]))
                bloque = KeepTogether([envoltorio])
            story.append(bloque)

            coords_parseadas = _parsear_coordenadas(coordenadas)
            if coords_parseadas:
                lat, lng = coords_parseadas
                puntos_mapa.append({"lat": lat, "lng": lng, "numero": numero, "color": color_entidad})
                equivalencia_filas.append((numero, entidad, descripcion))

    # ── Resumen ───────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("RESUMEN", estilos["seccion"]))
    filas_resumen = [[Paragraph("Entidad", estilos["label"]), Paragraph("Cantidad", estilos["label"])]]
    for entidad, reqs in grupos.items():
        filas_resumen.append([Paragraph(entidad, estilos["valor"]), Paragraph(str(len(reqs)), estilos["valor"])])
    filas_resumen.append([
        Paragraph("Total", estilos["req_titulo"]),
        Paragraph(str(len(requerimientos)), estilos["req_titulo"]),
    ])
    t_resumen = Table(filas_resumen, colWidths=[13 * cm, 3.6 * cm], hAlign="LEFT")
    t_resumen.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, _GRIS_BORDE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, _GRIS_BORDE),
        ("BACKGROUND", (0, 0), (-1, 0), _VERDE_CLARO),
        ("BACKGROUND", (0, -1), (-1, -1), _VERDE_CLARO),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t_resumen)

    # ── Mapa general de recorrido ─────────────────────────────────────────────
    mapa_png = _generar_mapa_recorrido(puntos_mapa)
    if mapa_png:
        story.append(PageBreak())
        story.append(Paragraph("MAPA GENERAL DE RECORRIDO", estilos["seccion"]))
        img = Image.open(io.BytesIO(mapa_png))
        ancho_pt = 17 * cm
        alto_pt = ancho_pt * img.height / img.width
        story.append(RLImage(io.BytesIO(mapa_png), width=ancho_pt, height=alto_pt))
        story.append(Spacer(1, 6))

        filas_leyenda = []
        for i in range(0, len(entidad_color), 2):
            par = list(entidad_color.items())[i:i + 2]
            fila = []
            for entidad, color_hex in par:
                swatch = Table([[""]], colWidths=[0.35 * cm], rowHeights=[0.35 * cm])
                swatch.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color_hex))]))
                fila.append(swatch)
                fila.append(Paragraph(entidad, estilos["leyenda"]))
            if len(par) == 1:
                fila.extend(["", ""])
            filas_leyenda.append(fila)
        t_leyenda = Table(filas_leyenda, colWidths=[0.5 * cm, 7.5 * cm, 0.5 * cm, 7.5 * cm])
        t_leyenda.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t_leyenda)
        story.append(Spacer(1, 8))

        story.append(Paragraph("Equivalencia de marcadores", estilos["label"]))
        story.append(Spacer(1, 3))
        filas_equiv = [[
            Paragraph("Marcador", estilos["label"]), Paragraph("Entidad", estilos["label"]),
            Paragraph("Descripción", estilos["label"]),
        ]]
        for numero, entidad, descripcion in equivalencia_filas:
            filas_equiv.append([
                Paragraph(str(numero), estilos["valor"]),
                Paragraph(entidad, estilos["valor"]),
                Paragraph(descripcion, estilos["valor"]),
            ])
        t_equiv = Table(filas_equiv, colWidths=[2 * cm, 6.5 * cm, 8.1 * cm], hAlign="LEFT")
        t_equiv.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.75, _GRIS_BORDE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, _GRIS_BORDE),
            ("BACKGROUND", (0, 0), (-1, 0), _VERDE_CLARO),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t_equiv)

    # ── Pie de página ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GRIS_BORDE))
    story.append(Spacer(1, 4))
    now_str = now_colombia().strftime("%d/%m/%Y %H:%M") + " (hora Colombia)"
    story.append(Paragraph(f"Informe generado automáticamente por CataTrack · {now_str}", estilos["pie"]))
    story.append(Paragraph("Alcaldía de Santiago de Cali — Todos los derechos reservados", estilos["pie"]))

    doc.build(story)
    return buffer.getvalue()
