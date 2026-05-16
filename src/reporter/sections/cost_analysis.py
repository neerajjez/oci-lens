"""
src/reporter/sections/cost_analysis.py
=========================================
Cost Analysis page: cost distribution treemap.
"""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image, PageBreak, Paragraph, Spacer

from src.reporter.charts.treemap import chart_cost_treemap
from src.reporter.styles import BODY, CAPTION, H2, H3, MARGIN, NEUTRAL_200, PAGE_WIDTH

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def _bytes_to_image(buf: BytesIO, width: float, height: float) -> Image:
    buf.seek(0)
    return Image(buf, width=width, height=height)


def build_cost_analysis(result: "AnalyticsResult") -> list:
    flowables: list = []

    flowables.append(Paragraph("Cost Analysis", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    chart_w = PAGE_WIDTH - 2 * MARGIN

    instance_costs = []
    for w in (result.fleet_kpis.top_5_wasteful or []):
        instance_costs.append({
            "name": w.get("display_name", ""),
            "total_cost": float(w.get("total_cost") or 0),
            "composite_score": float(w.get("composite_score") or 0),
        })
    for e in (result.fleet_kpis.top_5_efficient or []):
        instance_costs.append({
            "name": e.get("display_name", ""),
            "total_cost": float(e.get("total_cost") or 0),
            "composite_score": float(e.get("composite_score") or 0),
        })
    for rec in result.recommendations:
        if not any(d["name"] == rec.instance_name for d in instance_costs):
            instance_costs.append({
                "name": rec.instance_name,
                "total_cost": float(rec.current_monthly_cost or 0),
                "composite_score": 0.0,
            })

    try:
        treemap_buf = chart_cost_treemap(instance_costs, width_in=7.5, height_in=4.8)
        flowables.append(Paragraph("Cost Distribution by Instance", H3))
        flowables.append(_bytes_to_image(treemap_buf, chart_w, chart_w * 0.64))
        flowables.append(Paragraph(
            "Each rectangle represents one instance. Area = monthly cost. "
            "Color: red = under-utilized, green = well-utilized.",
            CAPTION,
        ))
    except Exception:
        flowables.append(Paragraph("(Cost distribution chart temporarily unavailable)", BODY))

    flowables.append(PageBreak())
    return flowables
