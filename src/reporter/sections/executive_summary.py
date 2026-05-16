"""
src/reporter/sections/executive_summary.py
============================================
Executive Summary: 2x2 KPI cards + narrative + 3 callout boxes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, Spacer, Table, TableStyle,
)

from src.reporter.components.callout_box import callout_box
from src.reporter.components.kpi_card import kpi_card
from src.reporter.narrative import (
    anomaly_summary_paragraph,
    executive_paragraph,
    top_recommendations_paragraph,
    trend_summary_paragraph,
)
from src.reporter.styles import (
    BODY, H2, MARGIN, NEUTRAL_200, PAGE_WIDTH, PRIMARY,
)

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def build_executive_summary(result: "AnalyticsResult") -> list:
    """Returns flowables for the Executive Summary page."""
    kpis = result.fleet_kpis
    flowables: list = []

    flowables.append(Paragraph("Executive Summary", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.15 * inch))

    # ── 2x2 KPI cards ──────────────────────────────────────────────────────
    card_w = (PAGE_WIDTH - 2 * MARGIN - 0.3 * inch) / 2

    monthly_rate = float(kpis.total_fleet_cost_monthly_run_rate or 0)
    savings = float(kpis.total_potential_monthly_savings or 0)
    score = float(kpis.weighted_composite_score or 0)
    n_anomalies = len(result.anomalies)

    # Trend arrows
    cost_trend = kpis.fleet_cost_trend_pct
    util_trend = kpis.utilization_trend_pct

    cost_trend_txt = None
    cost_trend_dir = "neutral"
    if cost_trend is not None:
        arrow = "↑" if cost_trend > 0 else "↓"
        cost_trend_txt = f"{arrow} {abs(cost_trend):.1f}% vs prior period"
        cost_trend_dir = "up_bad" if cost_trend > 0 else "down_good"

    util_trend_txt = None
    util_trend_dir = "neutral"
    if util_trend is not None:
        arrow = "↑" if util_trend > 0 else "↓"
        util_trend_txt = f"{arrow} {abs(util_trend):.1f}pts vs prior period"
        util_trend_dir = "up_good" if util_trend > 0 else "down_bad"

    from src.reporter.styles import ACCENT, DANGER, SUCCESS, WARNING_COLOR

    row1 = [
        kpi_card(
            f"${monthly_rate:,.0f}",
            "Monthly Run Rate (USD)",
            trend_text=cost_trend_txt,
            trend_direction=cost_trend_dir,
            width=card_w,
        ),
        kpi_card(
            f"${savings:,.0f}",
            "Potential Monthly Savings",
            width=card_w,
            accent_color=SUCCESS,
        ),
    ]
    row2 = [
        kpi_card(
            f"{score:.2f}",
            "Weighted Composite Score (0–1)",
            trend_text=util_trend_txt,
            trend_direction=util_trend_dir,
            width=card_w,
            accent_color=ACCENT,
        ),
        kpi_card(
            str(n_anomalies),
            "Anomalies Detected",
            width=card_w,
            accent_color=DANGER if n_anomalies > 0 else SUCCESS,
        ),
    ]

    kpi_grid = Table(
        [row1, row2],
        colWidths=[card_w, card_w],
    )
    kpi_grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flowables.append(kpi_grid)
    flowables.append(Spacer(1, 0.1 * inch))

    # ── Cost split row: compute / storage / unattributed ────────────────────
    from src.reporter.styles import WARNING_COLOR
    instance_costs = getattr(result, "instance_costs", None) or []
    compute_spend = sum(c.compute_cost for c in instance_costs)
    storage_spend = sum(c.storage_cost for c in instance_costs)
    unattributed = float(getattr(kpis, "orphaned_cost_total", 0.0) or 0.0)

    card_w3 = (PAGE_WIDTH - 2 * MARGIN - 0.4 * inch) / 3
    cost_row = [
        kpi_card(f"${compute_spend:,.2f}", "Compute Spend (attributed)", width=card_w3),
        kpi_card(f"${storage_spend:,.2f}", "Storage Spend (attributed)", width=card_w3, accent_color=ACCENT),
        kpi_card(f"${unattributed:,.2f}", "Unattributed Fleet Cost", width=card_w3, accent_color=WARNING_COLOR),
    ]
    cost_split_grid = Table([cost_row], colWidths=[card_w3, card_w3, card_w3])
    cost_split_grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flowables.append(cost_split_grid)
    flowables.append(Spacer(1, 0.15 * inch))

    # ── Narrative paragraph ─────────────────────────────────────────────────
    narrative = executive_paragraph(result)
    trend_note = trend_summary_paragraph(result)
    combined = narrative + (" " + trend_note if trend_note else "")
    flowables.append(Paragraph(combined, BODY))
    flowables.append(Spacer(1, 0.2 * inch))

    # ── 3 callout boxes ─────────────────────────────────────────────────────
    from src.analytics.right_sizer import RecommendationType
    from src.analytics.anomaly import AnomalySeverity

    box_w = (PAGE_WIDTH - 2 * MARGIN - 0.4 * inch) / 3

    # What's working
    efficient = (kpis.top_5_efficient or [])[:2]
    working_body = (
        "; ".join(e.get("display_name", "?")[:20] for e in efficient)
        if efficient
        else "No instances at optimal utilization yet."
    )
    good_box = callout_box("✓ What's Working", working_body, tone="good", width=box_w)

    # What needs attention
    needs_attn_recs = [
        r for r in result.recommendations
        if r.recommendation_type == RecommendationType.DOWNSIZE
    ]
    needs_attn_recs.sort(key=lambda r: r.estimated_monthly_savings, reverse=True)
    if needs_attn_recs:
        top_rec = needs_attn_recs[0]
        attn_body = (
            f"Top win: resize {top_rec.instance_name[:20]} "
            f"→ save ${top_rec.estimated_monthly_savings:,.0f}/month."
        )
    else:
        attn_body = "No immediate right-sizing actions required."
    attn_box = callout_box("⚡ Needs Attention", attn_body, tone="warning", width=box_w)

    # Urgent
    critical_anomalies = [a for a in result.anomalies if a.severity == AnomalySeverity.CRITICAL]
    if critical_anomalies:
        urg_body = (
            f"{len(critical_anomalies)} critical "
            f"{'issue' if len(critical_anomalies) == 1 else 'issues'}: "
            + "; ".join(a.resource_name[:20] for a in critical_anomalies[:2])
        )
    elif kpis.idle_count and kpis.idle_count > 0:
        urg_body = f"{kpis.idle_count} idle instance(s) — verify before terminating."
    else:
        urg_body = "No critical issues detected this period."
    urg_box = callout_box("🔴 Urgent", urg_body, tone="critical", width=box_w)

    boxes_row = Table(
        [[good_box, attn_box, urg_box]],
        colWidths=[box_w, box_w, box_w],
    )
    boxes_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flowables.append(boxes_row)
    flowables.append(PageBreak())
    return flowables
