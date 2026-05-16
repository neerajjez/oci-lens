"""
src/reporter/sections/recommendations.py
==========================================
Cost optimisation recommendations — downsize savings focus.
No anomaly, terminate, or shutdown language.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, Spacer, Table, TableStyle,
)

from src.reporter.styles import (
    BODY, BODY_SMALL, CAPTION, H2, H3,
    MARGIN, NEUTRAL_200, NEUTRAL_50, PAGE_WIDTH, PRIMARY, SUCCESS,
    WHITE,
)

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult

_LABEL_S = ParagraphStyle("rl", fontSize=7, leading=9, fontName="Helvetica",
                           textColor=colors.HexColor("#9A9A9A"))
_VALUE_S = ParagraphStyle("rv", fontSize=9, leading=12, fontName="Helvetica-Bold",
                           textColor=colors.HexColor("#1A1A1A"))
_RAT_S   = ParagraphStyle("rr", fontSize=8, leading=11, fontName="Helvetica-Oblique",
                           textColor=colors.HexColor("#4A4A4A"))
_SAVE_S  = ParagraphStyle("rs", fontSize=10, leading=13, fontName="Helvetica-Bold",
                           textColor=colors.HexColor("#2E7D32"))


def build_recommendations(result: "AnalyticsResult") -> list:
    from src.analytics.right_sizer import RecommendationType, ConfidenceLabel

    flowables: list = []
    recs = result.recommendations or []

    flowables.append(Paragraph("Cost Optimisation Recommendations", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    downsize = [r for r in recs if r.recommendation_type == RecommendationType.DOWNSIZE]
    review   = [r for r in recs if r.recommendation_type == RecommendationType.TERMINATE]

    downsize.sort(key=lambda r: r.estimated_monthly_savings, reverse=True)
    review.sort(key=lambda r: r.current_monthly_cost, reverse=True)

    total_savings = sum(r.estimated_monthly_savings for r in downsize)

    # Summary band
    summary_s = ParagraphStyle("rec_sum", fontSize=10, leading=14,
                                fontName="Helvetica-Bold", textColor=WHITE)
    n_action = len(downsize) + len(review)
    summary_msg = (
        f"Potential monthly savings: ${total_savings:,.0f}  |  "
        f"{len(downsize)} downsize opportunity(s)  |  "
        f"{len(review)} instance(s) to review for downsizing"
    ) if n_action else "No right-sizing opportunities identified — fleet appears well-sized."

    summary_tbl = Table([[Paragraph(summary_msg, summary_s)]],
                        colWidths=[PAGE_WIDTH - 2 * MARGIN])
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), PRIMARY),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))
    flowables.append(summary_tbl)
    flowables.append(Spacer(1, 0.15 * inch))

    col_w = PAGE_WIDTH - 2 * MARGIN

    def _downsize_card(rec) -> list:
        cur_cfg = getattr(rec, "current_config", None)
        rec_cfg = getattr(rec, "recommended_config", None)
        cur_ocpu = f"{cur_cfg.ocpu} OCPU / {cur_cfg.ram_gb:.0f} GB" if cur_cfg else rec.current_shape
        rec_ocpu = f"{rec_cfg.ocpu} OCPU / {rec_cfg.ram_gb:.0f} GB" if rec_cfg else (rec.recommended_shape or "—")

        col1 = [Paragraph(rec.instance_name[:35], _VALUE_S)]
        col2 = [
            Paragraph("Current",     _LABEL_S),
            Paragraph(cur_ocpu,      _VALUE_S),
            Spacer(1, 4),
            Paragraph("Recommended", _LABEL_S),
            Paragraph(rec_ocpu,      _VALUE_S),
        ]
        col3 = [
            Paragraph("Estimated saving if downsized", _LABEL_S),
            Paragraph(
                f"${rec.estimated_monthly_savings:,.0f}/mo"
                if rec.estimated_monthly_savings else "—",
                _SAVE_S,
            ),
            Spacer(1, 4),
            Paragraph(f"({rec.savings_pct:.1f}% saving)" if rec.savings_pct else "", _LABEL_S),
        ]
        col4 = [
            Paragraph("Rationale", _LABEL_S),
            Paragraph((rec.rationale or "")[:130], _RAT_S),
        ]

        w1, w2, w3 = 1.6 * inch, 1.9 * inch, 1.2 * inch
        w4 = col_w - w1 - w2 - w3
        card_tbl = Table([[col1, col2, col3, col4]], colWidths=[w1, w2, w3, w4])
        card_tbl.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 0.5, NEUTRAL_200),
            ("BACKGROUND",    (0, 0), (-1, -1), WHITE),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        return [card_tbl, Spacer(1, 0.04 * inch)]

    def _review_card(rec) -> list:
        cur_cfg = getattr(rec, "current_config", None)
        cur_ocpu = f"{cur_cfg.ocpu} OCPU / {cur_cfg.ram_gb:.0f} GB" if cur_cfg else rec.current_shape

        col1 = [Paragraph(rec.instance_name[:35], _VALUE_S)]
        col2 = [
            Paragraph("Current Shape", _LABEL_S),
            Paragraph(cur_ocpu,        _VALUE_S),
        ]
        col3 = [
            Paragraph("Recommendation", _LABEL_S),
            Paragraph("Review for downsizing", _VALUE_S),
        ]
        col4 = [
            Paragraph("Rationale", _LABEL_S),
            Paragraph((rec.rationale or "")[:130], _RAT_S),
        ]

        w1, w2, w3 = 1.6 * inch, 1.9 * inch, 1.2 * inch
        w4 = col_w - w1 - w2 - w3
        card_tbl = Table([[col1, col2, col3, col4]], colWidths=[w1, w2, w3, w4])
        card_tbl.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 0.5, NEUTRAL_200),
            ("BACKGROUND",    (0, 0), (-1, -1), WHITE),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        return [card_tbl, Spacer(1, 0.04 * inch)]

    # ── Downsize section ──────────────────────────────────────────────────
    if downsize:
        flowables.append(Paragraph(f"Downsize to Save — {len(downsize)} instance(s)", H3))
        flowables.append(Spacer(1, 0.05 * inch))
        for rec in downsize:
            flowables.extend(_downsize_card(rec))
        flowables.append(Spacer(1, 0.1 * inch))

    # ── Review for downsizing ─────────────────────────────────────────────
    if review:
        flowables.append(Paragraph(
            f"Review for Downsizing — {len(review)} instance(s)", H3))
        flowables.append(Paragraph(
            "These instances show very low utilisation. "
            "Review with the business owner and consider downsizing or consolidating to reduce cost.",
            BODY_SMALL,
        ))
        flowables.append(Spacer(1, 0.05 * inch))
        for rec in review:
            flowables.extend(_review_card(rec))
        flowables.append(Spacer(1, 0.1 * inch))

    if not downsize and not review:
        flowables.append(Paragraph(
            "All instances appear appropriately sized for current workloads. "
            "No immediate cost optimisation actions are required.",
            BODY,
        ))

    flowables.append(PageBreak())
    return flowables
