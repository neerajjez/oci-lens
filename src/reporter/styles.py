"""
src/reporter/styles.py
======================
Single source of truth for all visual constants used throughout the reporter.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

PRIMARY = colors.HexColor("#0F2D52")
PRIMARY_LIGHT = colors.HexColor("#3B5F8C")
ACCENT = colors.HexColor("#00838F")
SUCCESS = colors.HexColor("#2E7D32")
WARNING_COLOR = colors.HexColor("#EF6C00")
DANGER = colors.HexColor("#C62828")

NEUTRAL_900 = colors.HexColor("#1A1A1A")
NEUTRAL_700 = colors.HexColor("#4A4A4A")
NEUTRAL_500 = colors.HexColor("#9A9A9A")
NEUTRAL_200 = colors.HexColor("#E5E5E5")
NEUTRAL_50 = colors.HexColor("#F8F8F8")
WHITE = colors.white
BLACK = colors.black

# Hex strings for matplotlib
PRIMARY_HEX = "#0F2D52"
PRIMARY_LIGHT_HEX = "#3B5F8C"
ACCENT_HEX = "#00838F"
SUCCESS_HEX = "#2E7D32"
WARNING_HEX = "#EF6C00"
DANGER_HEX = "#C62828"
NEUTRAL_50_HEX = "#F8F8F8"
NEUTRAL_200_HEX = "#E5E5E5"
NEUTRAL_500_HEX = "#9A9A9A"
NEUTRAL_900_HEX = "#1A1A1A"

# Cost-tier colours (table cell fills and chart fills)
COST_TIER_LOW    = colors.HexColor("#C8E6C9")   # pale green  — < $50/mo
COST_TIER_MED    = colors.HexColor("#FFF9C4")   # pale yellow — $50–200/mo
COST_TIER_HIGH   = colors.HexColor("#FFCCBC")   # pale orange — $200–500/mo
COST_TIER_CRIT   = colors.HexColor("#FFCDD2")   # pale red    — > $500/mo
ACCENT_LIGHT     = colors.HexColor("#4DD0E1")   # light cyan  — secondary highlight
SUCCESS_LIGHT    = colors.HexColor("#66BB6A")   # light green — healthy-but-improvable

# Cost-tier hex strings for matplotlib
COST_TIER_LOW_HEX  = "#C8E6C9"
COST_TIER_MED_HEX  = "#FFF9C4"
COST_TIER_HIGH_HEX = "#FFCCBC"
COST_TIER_CRIT_HEX = "#FFCDD2"

# Score zone colors (for composite score charts)
ZONE_OVERPROV = "#C62828"   # < 0.30
ZONE_RIGHTSZ = "#FFA726"    # 0.30–0.70
ZONE_UNDERPROV = "#2E7D32"  # > 0.70
ZONE_IDLE = "#7B1FA2"       # IDLE pattern

# Recommendation type colors
REC_COLORS = {
    "DOWNSIZE": "#2E7D32",
    "UPSIZE_OR_INVESTIGATE": "#EF6C00",
    "TERMINATE": "#C62828",
    "MONITOR": "#0F2D52",
    "OPTIMAL": "#00838F",
}

# Severity colors
SEVERITY_COLORS = {
    "critical": "#C62828",
    "warning": "#EF6C00",
    "info": "#0F2D52",
}

# ---------------------------------------------------------------------------
# Typography — ParagraphStyle instances
# ---------------------------------------------------------------------------

H1 = ParagraphStyle(
    "h1",
    fontSize=22,
    leading=26,
    textColor=PRIMARY,
    fontName="Helvetica-Bold",
    spaceAfter=12,
)

H2 = ParagraphStyle(
    "h2",
    fontSize=16,
    leading=20,
    textColor=PRIMARY,
    fontName="Helvetica-Bold",
    spaceAfter=8,
)

H3 = ParagraphStyle(
    "h3",
    fontSize=12,
    leading=16,
    textColor=NEUTRAL_900,
    fontName="Helvetica-Bold",
    spaceAfter=6,
)

BODY = ParagraphStyle(
    "body",
    fontSize=10,
    leading=14,
    textColor=NEUTRAL_900,
    fontName="Helvetica",
)

BODY_SMALL = ParagraphStyle(
    "body_small",
    fontSize=8,
    leading=11,
    textColor=NEUTRAL_700,
    fontName="Helvetica",
)

CAPTION = ParagraphStyle(
    "caption",
    fontSize=8,
    leading=10,
    textColor=NEUTRAL_500,
    fontName="Helvetica-Oblique",
)

BODY_WHITE = ParagraphStyle(
    "body_white",
    fontSize=10,
    leading=14,
    textColor=WHITE,
    fontName="Helvetica",
)

H1_WHITE = ParagraphStyle(
    "h1_white",
    fontSize=22,
    leading=26,
    textColor=WHITE,
    fontName="Helvetica-Bold",
    spaceAfter=8,
)

H2_WHITE = ParagraphStyle(
    "h2_white",
    fontSize=16,
    leading=20,
    textColor=WHITE,
    fontName="Helvetica-Bold",
    spaceAfter=6,
)

HEADLINE_WHITE = ParagraphStyle(
    "headline_white",
    fontSize=36,
    leading=42,
    textColor=WHITE,
    fontName="Helvetica-Bold",
    spaceAfter=6,
)

SUBHEADLINE_WHITE = ParagraphStyle(
    "subheadline_white",
    fontSize=14,
    leading=18,
    textColor=colors.HexColor("#CCDDEE"),
    fontName="Helvetica",
    spaceAfter=4,
)

LABEL_WHITE = ParagraphStyle(
    "label_white",
    fontSize=10,
    leading=13,
    textColor=colors.HexColor("#AABBCC"),
    fontName="Helvetica",
)

CALLOUT_TITLE = ParagraphStyle(
    "callout_title",
    fontSize=10,
    leading=13,
    fontName="Helvetica-Bold",
    spaceAfter=3,
)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

PAGE_SIZE = A4
MARGIN = 0.38 * inch
GUTTER = 0.25 * inch

PAGE_WIDTH, PAGE_HEIGHT = A4
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

CHART_DPI = 200

# Table styling defaults
TABLE_HEADER_BG = PRIMARY
TABLE_HEADER_FG = WHITE
TABLE_ROW_ALT = NEUTRAL_50
TABLE_GRID = NEUTRAL_200
