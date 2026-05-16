"""
src/reporter/components/callout_box.py
=========================================
Colored callout box for narrative highlights (green / amber / red).
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Table, TableStyle

from src.reporter.styles import (
    BODY, DANGER, NEUTRAL_200, SUCCESS, WARNING_COLOR, WHITE,
    CALLOUT_TITLE,
)
from reportlab.lib.styles import ParagraphStyle

_TEXT_STYLE = ParagraphStyle(
    "callout_body",
    fontSize=9,
    leading=13,
    fontName="Helvetica",
    textColor=colors.HexColor("#1A1A1A"),
)


def callout_box(
    title: str,
    body: str,
    tone: str = "neutral",   # "good", "warning", "critical", "neutral"
    width: float = 2.0 * inch,
) -> Table:
    """
    Colored callout box.
    tone: "good" (green), "warning" (amber), "critical" (red), "neutral" (grey).
    """
    bg_map = {
        "good": colors.HexColor("#E8F5E9"),
        "warning": colors.HexColor("#FFF3E0"),
        "critical": colors.HexColor("#FFEBEE"),
        "neutral": colors.HexColor("#F5F5F5"),
    }
    border_map = {
        "good": SUCCESS,
        "warning": WARNING_COLOR,
        "critical": DANGER,
        "neutral": NEUTRAL_200,
    }
    title_color_map = {
        "good": colors.HexColor("#1B5E20"),
        "warning": colors.HexColor("#E65100"),
        "critical": colors.HexColor("#B71C1C"),
        "neutral": colors.HexColor("#212121"),
    }

    bg = bg_map.get(tone, bg_map["neutral"])
    border_color = border_map.get(tone, NEUTRAL_200)
    title_color = title_color_map.get(tone, colors.HexColor("#212121"))

    title_style = ParagraphStyle(
        f"callout_title_{tone}",
        fontSize=10,
        leading=13,
        fontName="Helvetica-Bold",
        textColor=title_color,
        spaceAfter=4,
    )

    content = [Paragraph(title, title_style), Paragraph(body, _TEXT_STYLE)]

    tbl = Table([content], colWidths=[width])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 1.5, border_color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl
