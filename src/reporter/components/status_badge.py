"""
src/reporter/components/status_badge.py
=========================================
Colored status badge Paragraph for recommendation types and severity levels.
"""
from __future__ import annotations

from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

from src.reporter.styles import (
    ACCENT, DANGER, SUCCESS, WARNING_COLOR, PRIMARY,
    WHITE, NEUTRAL_700,
    REC_COLORS, SEVERITY_COLORS,
)


def _badge_style(bg_hex: str) -> ParagraphStyle:
    return ParagraphStyle(
        f"badge_{bg_hex.strip('#')}",
        fontSize=8,
        leading=10,
        fontName="Helvetica-Bold",
        textColor=WHITE,
        backColor=colors.HexColor(bg_hex),
        borderPadding=(2, 4, 2, 4),
        spaceAfter=0,
    )


_STYLES: dict[str, ParagraphStyle] = {k: _badge_style(v) for k, v in REC_COLORS.items()}
_SEVERITY_STYLES: dict[str, ParagraphStyle] = {k: _badge_style(v) for k, v in SEVERITY_COLORS.items()}


def recommendation_badge(rec_type: str) -> Paragraph:
    """Returns a colored badge Paragraph for a recommendation type string."""
    key = rec_type.upper() if rec_type else "MONITOR"
    style = _STYLES.get(key, _badge_style("#9A9A9A"))
    label = {
        "DOWNSIZE": "DOWNSIZE",
        "UPSIZE_OR_INVESTIGATE": "INVESTIGATE CAPACITY",
        "TERMINATE": "REVIEW FOR SHUTDOWN",
        "MONITOR": "MONITOR",
        "OPTIMAL": "OPTIMAL",
    }.get(key, key)
    return Paragraph(f" {label} ", style)


def severity_badge(severity: str) -> Paragraph:
    """Returns a colored badge Paragraph for an anomaly severity."""
    key = severity.lower() if severity else "info"
    style = _SEVERITY_STYLES.get(key, _badge_style("#9A9A9A"))
    return Paragraph(f" {severity.upper()} ", style)


def confidence_badge(label: str) -> Paragraph:
    """Returns a colored confidence pill."""
    color_map = {
        "high": "#2E7D32",
        "medium": "#EF6C00",
        "low": "#C62828",
    }
    key = label.lower() if label else "low"
    return Paragraph(f" {label.upper()} ", _badge_style(color_map.get(key, "#9A9A9A")))
