"""
src/reporter/sections/instance_detail.py
==========================================
Instance Detail: paginated full table, 25 rows/page, sorted by wasted_spend desc.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer

from src.reporter.components.data_table import styled_table
from src.reporter.components.status_badge import recommendation_badge
from src.reporter.styles import BODY, CAPTION, H2, H3, MARGIN, NEUTRAL_200, PAGE_WIDTH

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult

_ROWS_PER_PAGE = 25


def build_instance_detail(result: "AnalyticsResult") -> list:
    """Returns flowables for the Instance Detail section (paginated)."""
    from src.analytics.right_sizer import RecommendationType

    flowables: list = []
    recs = result.recommendations

    if not recs:
        return flowables

    # Sort by wasted_spend / savings desc
    sorted_recs = sorted(recs, key=lambda r: r.estimated_monthly_savings, reverse=True)

    total_pages = max(1, (len(sorted_recs) + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE)

    headers = ["Instance", "Shape", "Type", "Curr Cost/mo", "Savings/mo", "Confidence", "Risk"]
    col_w = PAGE_WIDTH - 2 * MARGIN
    col_widths = [1.6 * inch, 1.2 * inch, 0.65 * inch, 0.8 * inch, 0.8 * inch, 0.65 * inch, 0.5 * inch]

    for page_idx in range(total_pages):
        chunk = sorted_recs[page_idx * _ROWS_PER_PAGE: (page_idx + 1) * _ROWS_PER_PAGE]

        flowables.append(Paragraph("Instance Detail", H2))
        if total_pages > 1:
            flowables.append(Paragraph(
                f"Page {page_idx + 1} of {total_pages}  ·  sorted by estimated savings desc",
                CAPTION,
            ))
        flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
        flowables.append(Spacer(1, 0.1 * inch))

        rows = []
        for rec in chunk:
            rows.append([
                rec.instance_name[:28],
                rec.current_shape[:20],
                recommendation_badge(rec.recommendation_type.value),
                f"${rec.current_monthly_cost:,.0f}",
                f"${rec.estimated_monthly_savings:,.0f}" if rec.estimated_monthly_savings else "—",
                rec.confidence_label.value.upper(),
                rec.risk_level.value.upper(),
            ])

        tbl = styled_table(headers, rows, col_widths=col_widths, font_size=7, max_col_chars=30)
        flowables.append(tbl)
        flowables.append(PageBreak())

    return flowables
