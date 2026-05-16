"""
src/reporter/components/data_table.py
========================================
Zebra-striped ReportLab table builder.
"""
from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Table, TableStyle

from src.reporter.styles import (
    BODY, BODY_SMALL, CAPTION,
    NEUTRAL_200, NEUTRAL_50, PRIMARY, TABLE_GRID, TABLE_HEADER_BG, TABLE_HEADER_FG,
    TABLE_ROW_ALT, WHITE,
)
from reportlab.lib.styles import ParagraphStyle

_HEADER_STYLE = ParagraphStyle(
    "tbl_header",
    fontSize=8,
    leading=10,
    fontName="Helvetica-Bold",
    textColor=WHITE,
)

_CELL_STYLE = ParagraphStyle(
    "tbl_cell",
    fontSize=8,
    leading=10,
    fontName="Helvetica",
    textColor=colors.HexColor("#1A1A1A"),
)


def _wrap(text: str, style: ParagraphStyle, max_chars: int = 40) -> Paragraph:
    """Truncate long strings and return a Paragraph."""
    s = str(text) if text is not None else "—"
    if len(s) > max_chars:
        s = s[: max_chars - 1] + "…"
    return Paragraph(s, style)


def styled_table(
    headers: list[str],
    rows: list[list[Any]],
    col_widths: list[float] | None = None,
    font_size: int = 8,
    max_col_chars: int = 40,
) -> Table:
    """
    Build a zebra-striped ReportLab table.
    headers: column header strings
    rows: list of rows, each row a list of strings or Paragraphs
    """
    header_row = [Paragraph(h, _HEADER_STYLE) for h in headers]

    body_style = ParagraphStyle(
        "tbl_body_dyn",
        fontSize=font_size,
        leading=font_size + 2,
        fontName="Helvetica",
        textColor=colors.HexColor("#1A1A1A"),
    )

    table_data = [header_row]
    for row in rows:
        table_row = []
        for cell in row:
            if isinstance(cell, Paragraph):
                table_row.append(cell)
            else:
                table_row.append(_wrap(cell, body_style, max_col_chars))
        table_data.append(table_row)

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TABLE_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), font_size),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        # Body
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), font_size),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, TABLE_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, TABLE_ROW_ALT]),
    ]

    tbl.setStyle(TableStyle(style_cmds))
    return tbl
