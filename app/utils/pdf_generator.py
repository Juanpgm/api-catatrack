"""
Generador de Informe PDF de Visita de Campo — CataTrack
Utiliza reportlab para crear el PDF en memoria y devolverlo como bytes.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Zona horaria Colombia (UTC-5)
_COL_TZ = timezone(timedelta(hours=-5))
_TIMESTAMP_SUFFIX = " (hora Colombia)"

# ──────────────────────────────────────────────────────────────────────────────
# Paleta de colores institucional
# ──────────────────────────────────────────────────────────────────────────────
_VERDE_CALI = colors.HexColor("#1a6b3c")   # verde oscuro institucional
_VERDE_CLARO = colors.HexColor("#e8f5e9")  # fondo de filas pares
_GRIS_TEXTO = colors.HexColor("#333333")
_GRIS_BORDE = colors.HexColor("#cccccc")
_AMARILLO = colors.HexColor("#fff8e1")
_ROJO = colors.HexColor("#ffebee")
_AZUL = colors.HexColor("#e3f2fd")

_ESTADO_COLOR: Dict[str, Any] = {
    "nuevo": _AZUL,
    "radicado": _AMARILLO,
    "en-gestion": colors.HexColor("#fff3e0"),
    "asignado": colors.HexColor("#f3e5f5"),
    "en-proceso": colors.HexColor("#e8f5e9"),
    "resuelto": _VERDE_CLARO,
    "cerrado": colors.HexColor("#f5f5f5"),
    "cancelado": _ROJO,
}

_PRIORIDAD_COLOR: Dict[str, Any] = {
    "alta": _ROJO,
    "media": _AMARILLO,
    "baja": _VERDE_CLARO,
}


def _estilos() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    estilos: Dict[str, ParagraphStyle] = {}

    estilos["titulo"] = ParagraphStyle(
        "titulo",
        parent=base["Title"],
        fontSize=16,
        textColor=_VERDE_CALI,
        spaceAfter=4,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    estilos["subtitulo"] = ParagraphStyle(
        "subtitulo",
        parent=base["Normal"],
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=2,
        alignment=TA_CENTER,
    )
    estilos["seccion"] = ParagraphStyle(
        "seccion",
        parent=base["Heading2"],
        fontSize=11,
        textColor=colors.white,
        backColor=_VERDE_CALI,
        spaceAfter=6,
        spaceBefore=10,
        leftIndent=6,
        fontName="Helvetica-Bold",
    )
    estilos["label"] = ParagraphStyle(
        "label",
        parent=base["Normal"],
        fontSize=8,
        textColor=colors.grey,
        fontName="Helvetica-Bold",
    )
    estilos["valor"] = ParagraphStyle(
        "valor",
        parent=base["Normal"],
        fontSize=9,
        textColor=_GRIS_TEXTO,
    )
    estilos["req_titulo"] = ParagraphStyle(
        "req_titulo",
        parent=base["Normal"],
        fontSize=10,
        textColor=_VERDE_CALI,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )
    estilos["pie"] = ParagraphStyle(
        "pie",
        parent=base["Normal"],
        fontSize=7,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )

    return estilos


def _fila_dato(label: str, valor: str, estilos: Dict) -> List:
    """Fila de dos celdas: etiqueta a la izquierda, valor a la derecha."""
    return [
        Paragraph(label, estilos["label"]),
        Paragraph(str(valor) if valor is not None else "—", estilos["valor"]),
    ]


def _tabla_info(filas: List[List], col_widths: Optional[List] = None) -> Table:
    """Tabla de metadatos con estilo limpio."""
    if col_widths is None:
        col_widths = [4 * cm, 12 * cm]
    t = Table(filas, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, _VERDE_CLARO]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, _GRIS_BORDE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def _badge(texto: str, bg_color: Any, estilos: Dict) -> Paragraph:
    """Simulación de badge con fondo de color usando un Paragraph."""
    style = ParagraphStyle(
        "badge",
        parent=estilos["valor"],
        backColor=bg_color,
        borderPadding=(2, 6, 2, 6),
        borderRadius=4,
        fontSize=8,
        textColor=_GRIS_TEXTO,
    )
    return Paragraph(texto.upper(), style)


def _estado_badge(estado: str, estilos: Dict) -> Paragraph:
    bg = _ESTADO_COLOR.get(estado, colors.white)
    return _badge(estado.replace("-", " "), bg, estilos)


def _prioridad_badge(prioridad: str, estilos: Dict) -> Paragraph:
    bg = _PRIORIDAD_COLOR.get(prioridad, colors.white)
    return _badge(prioridad, bg, estilos)


def generar_reporte_visita(
    visita: Dict[str, Any],
    requerimientos: List[Dict[str, Any]],
) -> bytes:
    """
    Genera el PDF del informe de visita y lo retorna como bytes.

    Parameters
    ----------
    visita:
        Documento de la visita (campos de VisitaProgramadaOut).
    requerimientos:
        Lista de requerimientos asociados a la visita.

    Returns
    -------
    bytes
        Contenido del PDF en memoria.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Informe de Visita — {visita.get('id', '')}",
        author="CataTrack — Alcaldía de Santiago de Cali",
    )

    estilos = _estilos()
    story: List[Any] = []

    # ── Encabezado ───────────────────────────────────────────────────────────
    story.append(Paragraph("ALCALDÍA DE SANTIAGO DE CALI", estilos["subtitulo"]))
    story.append(Paragraph("Informe de Visita de Campo", estilos["titulo"]))
    story.append(Paragraph("Sistema CataTrack de Seguimiento de Requerimientos", estilos["subtitulo"]))
    story.append(HRFlowable(width="100%", thickness=2, color=_VERDE_CALI, spaceAfter=8))

    # ── Datos de la visita ────────────────────────────────────────────────────
    story.append(Paragraph("📋  Información de la Visita", estilos["seccion"]))
    story.append(Spacer(1, 4))

    unidad = visita.get("unidad_proyecto") or {}
    upid = visita.get("upid") or "—"
    nombre_up = unidad.get("nombre") or unidad.get("name") or upid

    colaboradores = visita.get("colaboradores") or []
    nombres_col = ", ".join(
        c.get("nombre") or c.get("name") or str(c) for c in colaboradores
    ) or "—"

    filas_visita = [
        _fila_dato("ID Visita", visita.get("id", "—"), estilos),
        _fila_dato("Unidad / Proyecto", nombre_up, estilos),
        _fila_dato("Fecha de Visita", visita.get("fecha_visita", "—"), estilos),
        _fila_dato("Hora Inicio", visita.get("hora_inicio") or "—", estilos),
        _fila_dato("Hora Fin", visita.get("hora_fin") or "—", estilos),
        _fila_dato("Estado", visita.get("estado", "—"), estilos),
        _fila_dato("Equipo / Colaboradores", nombres_col, estilos),
        _fila_dato("Observaciones", visita.get("observaciones") or "—", estilos),
    ]

    story.append(_tabla_info(filas_visita))
    story.append(Spacer(1, 8))

    # ── Resumen de requerimientos ─────────────────────────────────────────────
    total_req = len(requerimientos)
    story.append(
        Paragraph(
            f"📌  Requerimientos Registrados ({total_req})",
            estilos["seccion"],
        )
    )

    if not requerimientos:
        story.append(Spacer(1, 6))
        story.append(
            Paragraph("No se registraron requerimientos en esta visita.", estilos["valor"])
        )
    else:
        for idx, req in enumerate(requerimientos, start=1):
            story.append(Spacer(1, 6))

            solicitante = req.get("solicitante") or {}
            nombre_sol = solicitante.get("nombre_completo") or "—"
            cedula_sol = solicitante.get("cedula") or "—"
            tel_sol = solicitante.get("telefono") or "—"
            email_sol = solicitante.get("email") or "—"
            dir_sol = solicitante.get("direccion") or "—"
            barrio_sol = solicitante.get("barrio_vereda") or "—"
            comuna_sol = solicitante.get("comuna_corregimiento") or "—"

            centros = req.get("centros_gestores") or []
            centros_str = ", ".join(centros) if centros else "—"

            estado = req.get("estado") or "nuevo"
            prioridad = req.get("prioridad") or "media"
            porcentaje = req.get("porcentaje_avance") or 0
            numero_orfeo = req.get("numero_orfeo") or "—"
            encargado = req.get("encargado") or "—"
            fecha_sol = req.get("fecha_propuesta_solucion") or "—"

            encabezado_req = [
                [
                    Paragraph(f"Requerimiento #{idx} — ID: {req.get('id', '—')}", estilos["req_titulo"]),
                    _estado_badge(estado, estilos),
                    _prioridad_badge(prioridad, estilos),
                ]
            ]
            t_enc = Table(encabezado_req, colWidths=[10 * cm, 3 * cm, 3 * cm], hAlign="LEFT")
            t_enc.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("BACKGROUND", (0, 0), (-1, -1), _VERDE_CLARO),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.5, _VERDE_CALI),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )

            filas_req = [
                _fila_dato("Descripción", req.get("descripcion") or "—", estilos),
                _fila_dato("Observaciones", req.get("observaciones") or "—", estilos),
                _fila_dato("Dirección", req.get("direccion") or "—", estilos),
                _fila_dato("Centros Gestores", centros_str, estilos),
                _fila_dato("Encargado", encargado, estilos),
                _fila_dato("Avance", f"{porcentaje}%", estilos),
                _fila_dato("Fecha Propuesta Solución", fecha_sol, estilos),
                _fila_dato("N.º Orfeo / Radicado", numero_orfeo, estilos),
            ]

            filas_sol = [
                _fila_dato("Nombre Solicitante", nombre_sol, estilos),
                _fila_dato("Cédula", cedula_sol, estilos),
                _fila_dato("Teléfono", tel_sol, estilos),
                _fila_dato("Email", email_sol, estilos),
                _fila_dato("Dirección Solicitante", dir_sol, estilos),
                _fila_dato("Barrio / Vereda", barrio_sol, estilos),
                _fila_dato("Comuna / Corregimiento", comuna_sol, estilos),
            ]

            block = KeepTogether(
                [
                    t_enc,
                    Spacer(1, 4),
                    Paragraph("Detalle del Requerimiento", estilos["label"]),
                    _tabla_info(filas_req),
                    Spacer(1, 4),
                    Paragraph("Datos del Solicitante", estilos["label"]),
                    _tabla_info(filas_sol),
                ]
            )
            story.append(block)

    # ── Pie de página ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GRIS_BORDE))
    story.append(Spacer(1, 4))
    now_str = datetime.now(_COL_TZ).strftime("%d/%m/%Y %H:%M") + _TIMESTAMP_SUFFIX
    story.append(
        Paragraph(
            f"Informe generado automáticamente por CataTrack · {now_str}",
            estilos["pie"],
        )
    )
    story.append(
        Paragraph(
            "Alcaldía de Santiago de Cali — Todos los derechos reservados",
            estilos["pie"],
        )
    )

    doc.build(story)
    return buffer.getvalue()
