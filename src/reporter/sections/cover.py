"""
src/reporter/sections/cover.py
================================
Cover page for the OCI Cost Report — navy header panel, metadata row.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from src.reporter.styles import CONTENT_WIDTH, MARGIN, PAGE_HEIGHT, PAGE_WIDTH, WHITE

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult

_NAVY = colors.HexColor("#0F2D52")
_LIGHT_BLUE = colors.HexColor("#90CAF9")
_MUTED = colors.HexColor("#B0BEC5")

_TITLE_S = ParagraphStyle("cost_title", fontSize=24, leading=30,
                           textColor=WHITE, fontName="Helvetica-Bold")
_SUB_S   = ParagraphStyle("cost_sub",   fontSize=12, leading=17,
                           textColor=_LIGHT_BLUE, fontName="Helvetica")
_NOTE_S  = ParagraphStyle("cost_note",  fontSize=9,  leading=13,
                           textColor=_MUTED, fontName="Helvetica")


def build_cover(result: "AnalyticsResult", run_id: str) -> list:
    kpis = result.fleet_kpis

    tenancy    = result.tenancy_name    or "OCI"
    compartment = result.compartment_name or "All"

    period_start = result.period_start.strftime("%d %b %Y") if result.period_start else ""
    period_end   = result.period_end.strftime("%d %b %Y")   if result.period_end   else ""
    days = (
        max(1, (result.period_end - result.period_start).days)
        if result.period_start and result.period_end else 30
    )

    n_instances = (
        (kpis.overprovisioned_count or 0)
        + (kpis.rightsized_count or 0)
        + (kpis.underprovisioned_count or 0)
        + (kpis.idle_count or 0)
        + (kpis.insufficient_data_count or 0)
    )

    volumes = result.volumes or []
    boot_count  = sum(1 for v in volumes if "bootvolume" in str(v.get("volume_id") or v.get("id") or "").lower())
    block_count = len(volumes) - boot_count
    bucket_count = len(result.buckets or [])

    rows = [
        [Paragraph("OCI Cost Report", _TITLE_S)],
        [Spacer(1, 0.12 * inch)],
        [Paragraph(
            f"Tenancy: {tenancy}"
            + (f" &nbsp;|&nbsp; Compartment: {compartment}" if compartment else ""),
            _SUB_S,
        )],
        [Spacer(1, 0.08 * inch)],
        [Paragraph(
            f"Period: {period_start} \u2192 {period_end}"
            f" &nbsp;|&nbsp; {days}-day window"
            f" &nbsp;|&nbsp; {n_instances} instance(s)",
            _SUB_S,
        )],
        [Spacer(1, 0.12 * inch)],
        [Paragraph(
            f"Boot volumes: {boot_count}"
            f" &nbsp;|&nbsp; Block volumes: {block_count}"
            f" &nbsp;|&nbsp; Object storage buckets: {bucket_count}",
            _SUB_S,
        )],
        [Spacer(1, 0.2 * inch)],
        [Paragraph(f"Run ID: {run_id}", _NOTE_S)],
    ]

    tbl = Table(rows, colWidths=[CONTENT_WIDTH], style=TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 22),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 22),
    ]))

    return [tbl, Spacer(1, 0.28 * inch), PageBreak()]
