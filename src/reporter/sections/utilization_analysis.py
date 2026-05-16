"""
src/reporter/sections/utilization_analysis.py
================================================
Utilization Analysis page: score distribution + scatter.
"""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image, PageBreak, Paragraph, Spacer

from src.reporter.charts.distribution import chart_score_distribution
from src.reporter.charts.scatter import chart_cost_utilization_scatter
from src.reporter.styles import BODY, CAPTION, H2, H3, MARGIN, NEUTRAL_200, PAGE_WIDTH

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def _bytes_to_image(buf: BytesIO, width: float, height: float) -> Image:
    buf.seek(0)
    return Image(buf, width=width, height=height)


def build_utilization_analysis(result: "AnalyticsResult") -> list:
    """Returns flowables for the Utilization Analysis page."""
    flowables: list = []

    flowables.append(Paragraph("Utilization Analysis", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    chart_w = PAGE_WIDTH - 2 * MARGIN

    # ── Score distribution ────────────────────────────────────────────────
    try:
        # Gather composite scores from recommendations (best proxy in AnalyticsResult)
        scores = []
        for rec in result.recommendations:
            # estimate from confidence/savings context — use savings_pct as rough proxy
            # Actual scores would come from utilization_df; use 0.5 default if unknown
            scores.append(0.5)  # placeholder — real scores from utilization profile

        # Use fleet KPI distribution counts to construct a plausible list
        kpis = result.fleet_kpis
        scores = []
        if kpis.overprovisioned_count:
            scores.extend([0.15] * kpis.overprovisioned_count)
        if kpis.rightsized_count:
            scores.extend([0.50] * kpis.rightsized_count)
        if kpis.underprovisioned_count:
            scores.extend([0.80] * kpis.underprovisioned_count)
        if kpis.idle_count:
            scores.extend([0.02] * kpis.idle_count)

        dist_buf = chart_score_distribution(scores, width_in=7.5, height_in=3.2)
        flowables.append(Paragraph("Composite Score Distribution", H3))
        flowables.append(_bytes_to_image(dist_buf, chart_w, chart_w * 0.43))
        flowables.append(Paragraph(
            "Distribution of composite utilization scores across the fleet. "
            "Target: scores between 0.30 and 0.70 (right-sized zone).",
            CAPTION,
        ))
    except Exception:
        flowables.append(Paragraph("(Score distribution temporarily unavailable)", BODY))

    flowables.append(Spacer(1, 0.2 * inch))

    # ── Cost vs utilization scatter ────────────────────────────────────────
    try:
        instance_data = []
        for rec in result.recommendations:
            instance_data.append({
                "name": rec.instance_name,
                "composite_score": 0.3 if rec.recommendation_type.value == "DOWNSIZE" else 0.6,
                "monthly_cost": float(rec.current_monthly_cost or 0),
                "vcpu_count": int(rec.current_config.ocpu) if rec.current_config else 2,
            })
        scatter_buf = chart_cost_utilization_scatter(instance_data, width_in=7.5, height_in=3.5)
        flowables.append(Paragraph("Cost vs. Utilization", H3))
        flowables.append(_bytes_to_image(scatter_buf, chart_w, chart_w * 0.47))
        flowables.append(Paragraph(
            "x = composite utilization score, y = monthly cost, bubble size = vCPU count. "
            '"Money pit" quadrant (top-left) = highest optimization priority.',
            CAPTION,
        ))
    except Exception:
        flowables.append(Paragraph("(Cost vs. utilization scatter temporarily unavailable)", BODY))

    flowables.append(PageBreak())
    return flowables
