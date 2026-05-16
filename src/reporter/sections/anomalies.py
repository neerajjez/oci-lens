"""
src/reporter/sections/anomalies.py
=====================================
Anomalies & Alerts page.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer

from src.reporter.components.callout_box import callout_box
from src.reporter.components.data_table import styled_table
from src.reporter.components.status_badge import severity_badge
from src.reporter.styles import (
    BODY, CAPTION, H2, MARGIN, NEUTRAL_200, PAGE_WIDTH,
)

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def build_anomalies(result: "AnalyticsResult") -> list:
    """Returns flowables for the Anomalies & Alerts page."""
    flowables: list = []

    flowables.append(Paragraph("Anomalies & Alerts", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    if not result.anomalies:
        flowables.append(callout_box(
            "✓ No Anomalies Detected",
            "The fleet passed all anomaly detection checks this period. "
            "No cost outliers, idle instances, or stranded volumes were identified.",
            tone="good",
            width=PAGE_WIDTH - 2 * MARGIN,
        ))
        flowables.append(PageBreak())
        return flowables

    headers = ["Severity", "Instance", "Anomaly Type", "Description", "Suggested Action", "Recoverable"]

    col_w = PAGE_WIDTH - 2 * MARGIN
    col_widths = [0.65 * inch, 1.2 * inch, 1.0 * inch, 1.8 * inch, 1.6 * inch, 0.75 * inch]

    rows = []
    for anom in sorted(result.anomalies, key=lambda a: {"critical": 0, "warning": 1, "info": 2}.get(a.severity.value, 3)):
        rows.append([
            severity_badge(anom.severity.value),
            anom.resource_name[:22],
            anom.signal.replace("_", " ").title(),
            anom.description[:70],
            anom.suggested_action[:60],
            f"${anom.estimated_recoverable_amount:,.0f}",
        ])

    tbl = styled_table(headers, rows, col_widths=col_widths, font_size=7, max_col_chars=70)
    flowables.append(tbl)
    flowables.append(Spacer(1, 0.1 * inch))

    total_recoverable = sum(a.estimated_recoverable_amount for a in result.anomalies)
    flowables.append(Paragraph(
        f"Total estimated recoverable from anomalies: ${total_recoverable:,.0f}/month",
        CAPTION,
    ))

    flowables.append(PageBreak())
    return flowables
