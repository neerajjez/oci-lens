"""
Tests for src/reporter/components/*.py
"""
from __future__ import annotations

import pytest

from reportlab.platypus import Paragraph, Table


# ── kpi_card ─────────────────────────────────────────────────────────────────

def test_kpi_card_returns_table():
    from src.reporter.components.kpi_card import kpi_card
    from reportlab.lib.units import inch
    card = kpi_card("$5,000", "Monthly Cost", width=2.0 * inch)
    assert isinstance(card, Table)


def test_kpi_card_with_trend():
    from src.reporter.components.kpi_card import kpi_card
    from reportlab.lib.units import inch
    card = kpi_card("$5,000", "Cost", trend_text="↑ 10%", trend_direction="up_bad", width=2.0 * inch)
    assert isinstance(card, Table)


def test_kpi_card_all_trend_directions():
    from src.reporter.components.kpi_card import kpi_card
    from reportlab.lib.units import inch
    for direction in ("up_good", "up_bad", "down_good", "down_bad", "neutral"):
        card = kpi_card("42", "Count", trend_text="test", trend_direction=direction, width=1.5 * inch)
        assert isinstance(card, Table)


# ── status_badge ─────────────────────────────────────────────────────────────

def test_recommendation_badge_all_types():
    from src.reporter.components.status_badge import recommendation_badge
    for rtype in ("DOWNSIZE", "UPSIZE_OR_INVESTIGATE", "TERMINATE", "MONITOR", "OPTIMAL"):
        badge = recommendation_badge(rtype)
        assert isinstance(badge, Paragraph)


def test_recommendation_badge_unknown_type():
    from src.reporter.components.status_badge import recommendation_badge
    badge = recommendation_badge("UNKNOWN_TYPE")
    assert isinstance(badge, Paragraph)


def test_severity_badge():
    from src.reporter.components.status_badge import severity_badge
    for sev in ("critical", "warning", "info"):
        badge = severity_badge(sev)
        assert isinstance(badge, Paragraph)


def test_confidence_badge():
    from src.reporter.components.status_badge import confidence_badge
    for label in ("high", "medium", "low"):
        badge = confidence_badge(label)
        assert isinstance(badge, Paragraph)


# ── callout_box ───────────────────────────────────────────────────────────────

def test_callout_box_all_tones():
    from src.reporter.components.callout_box import callout_box
    from reportlab.lib.units import inch
    for tone in ("good", "warning", "critical", "neutral"):
        box = callout_box("Title", "Body text here.", tone=tone, width=2.0 * inch)
        assert isinstance(box, Table)


def test_callout_box_long_content():
    from src.reporter.components.callout_box import callout_box
    from reportlab.lib.units import inch
    long_body = "A" * 500
    box = callout_box("Long Title " * 5, long_body, tone="good", width=2.0 * inch)
    assert isinstance(box, Table)


# ── data_table ────────────────────────────────────────────────────────────────

def test_data_table_basic():
    from src.reporter.components.data_table import styled_table
    from reportlab.lib.units import inch
    headers = ["Name", "Cost", "Savings"]
    rows = [["inst-1", "$500", "$100"], ["inst-2", "$300", "$0"]]
    tbl = styled_table(headers, rows, col_widths=[1.5 * inch, 1.0 * inch, 1.0 * inch])
    assert isinstance(tbl, Table)


def test_data_table_empty_rows():
    from src.reporter.components.data_table import styled_table
    from reportlab.lib.units import inch
    tbl = styled_table(["H1", "H2"], [], col_widths=[2 * inch, 2 * inch])
    assert isinstance(tbl, Table)


def test_data_table_truncates_long_strings():
    from src.reporter.components.data_table import styled_table
    from reportlab.lib.units import inch
    long = "A" * 200
    tbl = styled_table(["Name"], [[long]], max_col_chars=40)
    assert isinstance(tbl, Table)
