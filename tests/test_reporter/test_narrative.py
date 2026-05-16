"""
Tests for src/reporter/narrative.py
"""
from __future__ import annotations

import re

import pytest

from src.reporter.narrative import (
    anomaly_summary_paragraph,
    executive_paragraph,
    top_recommendations_paragraph,
    trend_summary_paragraph,
)


def _has_unfilled_template(text: str) -> bool:
    return bool(re.search(r"\{[^}]+\}", text))


# ── executive_paragraph ──────────────────────────────────────────────────────

def test_executive_paragraph_with_savings(wasteful_result):
    para = executive_paragraph(wasteful_result)
    assert "$" in para
    assert "instance" in para.lower()
    assert not _has_unfilled_template(para)


def test_executive_paragraph_zero_savings(healthy_result):
    para = executive_paragraph(healthy_result)
    assert "well-optimized" in para.lower()
    assert not _has_unfilled_template(para)


def test_executive_paragraph_mentions_anomalies(wasteful_result):
    para = executive_paragraph(wasteful_result)
    assert "anomal" in para.lower()


def test_executive_paragraph_no_anomalies_omits_sentence(healthy_result):
    para = executive_paragraph(healthy_result)
    assert "anomal" not in para.lower()


def test_executive_paragraph_no_instances():
    from tests.test_reporter.conftest import _kpis, _base_result
    kpis = _kpis(overprov=0, rightsz=0, underprov=0, idle=0, insuff=0)
    result = _base_result(kpis, [], [])
    para = executive_paragraph(result)
    assert "no instances" in para.lower() or "not found" in para.lower()


# ── top_recommendations_paragraph ────────────────────────────────────────────

def test_top_recs_paragraph_with_recs(wasteful_result):
    para = top_recommendations_paragraph(wasteful_result)
    assert "$" in para
    assert not _has_unfilled_template(para)


def test_top_recs_paragraph_no_actionable(healthy_result):
    para = top_recommendations_paragraph(healthy_result)
    assert "no actionable" in para.lower()


def test_top_recs_paragraph_max_3(wasteful_result):
    para = top_recommendations_paragraph(wasteful_result)
    # Should mention at most 3 numbered items
    count = len(re.findall(r"^\d+\.", para, re.MULTILINE))
    assert count <= 3


# ── anomaly_summary_paragraph ─────────────────────────────────────────────────

def test_anomaly_paragraph_with_anomalies(wasteful_result):
    para = anomaly_summary_paragraph(wasteful_result)
    assert "anomal" in para.lower()
    assert not _has_unfilled_template(para)


def test_anomaly_paragraph_empty_returns_empty(healthy_result):
    para = anomaly_summary_paragraph(healthy_result)
    assert para == ""


def test_anomaly_paragraph_mentions_recoverable(wasteful_result):
    para = anomaly_summary_paragraph(wasteful_result)
    assert "$" in para


# ── trend_summary_paragraph ────────────────────────────────────────────────────

def test_trend_paragraph_first_run(mixed_result):
    para = trend_summary_paragraph(mixed_result)
    # First run — should indicate trend data unavailable
    assert "first" in para.lower() or "unavailable" in para.lower() or "trend" in para.lower()


def test_trend_paragraph_with_trend(wasteful_result):
    from tests.test_reporter.conftest import _kpis, _base_result
    from datetime import datetime, timezone
    kpis = _kpis()
    kpis.fleet_cost_trend_pct = 12.5
    kpis.utilization_trend_pct = -3.0
    kpis.trend_unavailable_reason = None
    result = _base_result(kpis, [], [])
    para = trend_summary_paragraph(result)
    assert "12.5" in para
    assert "3.0" in para
    assert not _has_unfilled_template(para)
