"""
src/reporter/sections/methodology.py
=======================================
Methodology page: formulas, thresholds, limitations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer, Table, TableStyle

from src.reporter.styles import (
    BODY, BODY_SMALL, CAPTION, H2, H3, MARGIN, NEUTRAL_200, NEUTRAL_50,
    PAGE_WIDTH, PRIMARY, WHITE,
)

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


_MONO = ParagraphStyle(
    "mono",
    fontSize=8,
    leading=12,
    fontName="Courier",
    textColor=PRIMARY,
    backColor=NEUTRAL_50,
    leftIndent=12,
    spaceAfter=4,
)


def _section(title: str, body: str) -> list:
    return [Paragraph(title, H3), Paragraph(body, BODY), Spacer(1, 0.1 * inch)]


def build_methodology(result: "AnalyticsResult", config: dict | None = None) -> list:
    """Returns flowables for the Methodology & Decision Framework page."""
    flowables: list = []

    flowables.append(Paragraph("Methodology &amp; Decision Framework", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    cfg = config or {}
    period_days = max(1, (result.period_end - result.period_start).days) if result.period_end and result.period_start else 15
    period_str = f"{result.period_start.date()} to {result.period_end.date()}" if result.period_start else "—"

    # ── Corporate Decision Framework ─────────────────────────────────────────
    flowables.append(Paragraph("Corporate Decision Criteria", H3))
    flowables.append(Paragraph(
        "All recommendations follow a standardised decision framework. "
        "Each action requires human authorisation before execution. "
        "The table below defines trigger conditions, savings thresholds, and the required approval path.",
        BODY,
    ))
    flowables.append(Spacer(1, 0.1 * inch))

    decision_data = [
        ["Action", "Trigger Condition", "Savings Threshold", "Confidence Required", "Approval Path"],
        ["Downsize — Save $/mo",
         "Composite score < 0.40 AND estimated monthly savings > $20",
         "> $20/mo or > 5 %",
         "MEDIUM or HIGH",
         "Line manager + Cloud team"],
        ["Investigate Capacity",
         "CPU p99 > 85% or erratic spikes sustained > 7 days",
         "N/A",
         "MEDIUM or HIGH",
         "Application owner review"],
        ["Review for Shutdown",
         "CPU p95 < 5% AND network p95 < 1 MB/s for full period",
         "Full instance cost",
         "HIGH only",
         "Business owner sign-off required"],
        ["Monitor",
         "Score 0.40–0.55 or insufficient data (< 14 days)",
         "—",
         "Any",
         "No action — observe next cycle"],
        ["Optimal",
         "Composite score 0.55–0.85, no anomalies",
         "—",
         "Any",
         "No action required"],
    ]
    dec_tbl = Table(
        decision_data,
        colWidths=[1.4 * inch, 1.9 * inch, 1.0 * inch, 1.0 * inch, 1.5 * inch],
    )
    dec_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("GRID",          (0, 0), (-1, -1), 0.25, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    flowables.append(dec_tbl)
    flowables.append(Spacer(1, 0.2 * inch))

    # ── Scoring Formula ──────────────────────────────────────────────────────
    flowables.append(Paragraph("Composite Utilisation Score Formula", H3))
    flowables.append(Paragraph(
        "Each instance is scored 0–1. "
        "A score near 1.0 means the instance is running at its optimal utilisation target; "
        "near 0 means idle or severely over-provisioned.",
        BODY,
    ))
    flowables.append(Spacer(1, 0.05 * inch))
    flowables.append(Paragraph("composite = 0.45 x cpu_score + 0.35 x memory_score + 0.20 x io_score", _MONO))
    flowables.append(Paragraph("sigmoid_score(x, target) = (x/target)^0.7   if x <= target", _MONO))
    flowables.append(Paragraph("sigmoid_score(x, target) = exp(-2.0 x (x/target - 1))   if x > target", _MONO))
    flowables.append(Paragraph(
        "Targets: CPU 70%, Memory 70%, I/O 60%. "
        "Memory score defaults to CPU score when OCI Compute Agent is not installed.",
        BODY_SMALL,
    ))
    flowables.append(Spacer(1, 0.15 * inch))

    # ── Confidence Scoring ───────────────────────────────────────────────────
    flowables.append(Paragraph("Recommendation Confidence", H3))
    conf_data = [
        ["Factor", "Adjustment", "Rationale"],
        ["< 14 days monitoring data",     "-0.20", "Insufficient history for reliable pattern detection"],
        ["Erratic utilisation pattern",   "-0.15", "High variance makes prediction unreliable"],
        ["Missing memory metrics",        "-0.10", "Score based on CPU/I/O only — partial picture"],
        ["Cost data gap > 7 days",        "-0.10", "Savings estimate less reliable"],
        ["Steady usage pattern (bonus)",  "+0.10", "Stable load — change risk is lower"],
        ["Score >= 0.80 → HIGH",           "—",    "Proceed with standard change management"],
        ["Score 0.55–0.80 → MEDIUM",      "—",    "Review carefully; consider extended monitoring"],
        ["Score < 0.55 → LOW",            "—",    "Manual investigation recommended before acting"],
    ]
    conf_tbl = Table(conf_data, colWidths=[2.2 * inch, 0.9 * inch, 3.7 * inch])
    conf_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.25, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
        ("ALIGN",         (1, 0), (1, -1), "CENTER"),
    ]))
    flowables.append(conf_tbl)
    flowables.append(Spacer(1, 0.2 * inch))

    # ── Data Sources ─────────────────────────────────────────────────────────
    flowables.extend(_section(
        "Data Sources & Collection Period",
        f"Data collected from OCI APIs for the period {period_str} ({period_days} days). "
        "Sources: OCI Compute API (instance metadata, shape), "
        "OCI Monitoring (CPU, memory, network, disk at 60-min intervals), "
        "OCI Block Volumes API (size, VPU, IOPS), "
        "OCI Object Storage API (bucket inventory), "
        "OCI Usage API — DAILY granularity grouped by resourceId, service, compartmentId, skuName.",
    ))

    # ── Limitations ──────────────────────────────────────────────────────────
    flowables.extend(_section(
        "Limitations & Governance Notes",
        "1. Memory metrics require OCI Compute Agent — instances without it are scored on CPU/I/O only. "
        "2. Pricing is based on OCI list prices; contracted UCM/Flex rates may reduce actual savings. "
        "3. Storage costs are attributed at instance level — OCI Usage API does not itemise per volume. "
        "4. Object storage cost attribution matches billing records to bucket names; "
        "cross-tenancy buckets may not be captured. "
        "5. This report provides analytical evidence only. "
        "No automated changes are made. All actions require explicit human authorisation "
        "through the organisation's change management process.",
    ))

    flowables.append(PageBreak())
    return flowables
