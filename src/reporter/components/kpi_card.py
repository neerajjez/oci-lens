"""
src/reporter/components/kpi_card.py
=====================================
KPI card flowable: large number, label, optional trend arrow.
"""
from __future__ import annotations

from typing import Optional

from reportlab.lib.units import inch
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors

from src.reporter.styles import (
    ACCENT, NEUTRAL_200, NEUTRAL_500, NEUTRAL_900, PRIMARY, WHITE,
    BODY, BODY_SMALL, CAPTION, H1, H2, H3,
)
import reportlab.lib.styles as rls
from reportlab.lib.styles import ParagraphStyle


_KPI_VALUE_STYLE = ParagraphStyle(
    "kpi_value",
    fontSize=28,
    leading=32,
    fontName="Helvetica-Bold",
    textColor=PRIMARY,
    spaceAfter=2,
)

_KPI_LABEL_STYLE = ParagraphStyle(
    "kpi_label",
    fontSize=9,
    leading=12,
    fontName="Helvetica",
    textColor=NEUTRAL_500,
)

_KPI_TREND_GOOD = ParagraphStyle(
    "kpi_trend_good",
    fontSize=9,
    leading=12,
    fontName="Helvetica-Bold",
    textColor=colors.HexColor("#2E7D32"),
)

_KPI_TREND_BAD = ParagraphStyle(
    "kpi_trend_bad",
    fontSize=9,
    leading=12,
    fontName="Helvetica-Bold",
    textColor=colors.HexColor("#C62828"),
)

_KPI_TREND_NEUTRAL = ParagraphStyle(
    "kpi_trend_neutral",
    fontSize=9,
    leading=12,
    fontName="Helvetica",
    textColor=NEUTRAL_500,
)


def kpi_card(
    value: str,
    label: str,
    trend_text: Optional[str] = None,
    trend_direction: Optional[str] = None,  # "up_good", "up_bad", "down_good", "down_bad", "neutral"
    width: float = 1.5 * inch,
    accent_color: Optional[object] = None,
) -> Table:
    """
    Returns a ReportLab Table acting as a KPI card.
    trend_direction: "up_good" (green ↑), "up_bad" (red ↑), "down_good" (green ↓),
                     "down_bad" (red ↓), "neutral" (grey)
    """
    value_style = ParagraphStyle(
        "kpi_value_dyn",
        parent=_KPI_VALUE_STYLE,
        textColor=accent_color or PRIMARY,
    )

    val_para = Paragraph(value, value_style)
    label_para = Paragraph(label, _KPI_LABEL_STYLE)

    trend_para = None
    if trend_text:
        if trend_direction in ("up_good", "down_good"):
            ts = _KPI_TREND_GOOD
        elif trend_direction in ("up_bad", "down_bad"):
            ts = _KPI_TREND_BAD
        else:
            ts = _KPI_TREND_NEUTRAL
        trend_para = Paragraph(trend_text, ts)

    cell_content = [val_para, label_para]
    if trend_para:
        cell_content.append(trend_para)

    tbl = Table([[cell_content]], colWidths=[width])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, NEUTRAL_200),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl
