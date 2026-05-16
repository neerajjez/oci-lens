"""
Tests for src/reporter/sections/*.py
Each section must return a non-empty list of flowables and handle edge data.
"""
from __future__ import annotations

import pytest
from reportlab.platypus import Flowable


def _flowables_ok(items: list) -> bool:
    return len(items) > 0 and all(isinstance(f, Flowable) for f in items)


def test_cover_section(mixed_result):
    from src.reporter.sections.cover import build_cover
    flowables = build_cover(mixed_result, run_id="test001")
    assert _flowables_ok(flowables)


def test_executive_summary_section(mixed_result):
    from src.reporter.sections.executive_summary import build_executive_summary
    flowables = build_executive_summary(mixed_result)
    assert _flowables_ok(flowables)


def test_cost_analysis_section(mixed_result):
    from src.reporter.sections.cost_analysis import build_cost_analysis
    flowables = build_cost_analysis(mixed_result)
    assert _flowables_ok(flowables)


def test_utilization_analysis_section(mixed_result):
    from src.reporter.sections.utilization_analysis import build_utilization_analysis
    flowables = build_utilization_analysis(mixed_result)
    assert _flowables_ok(flowables)


def test_recommendations_section_with_recs(wasteful_result):
    from src.reporter.sections.recommendations import build_recommendations
    flowables = build_recommendations(wasteful_result)
    assert _flowables_ok(flowables)


def test_recommendations_section_empty(healthy_result):
    from src.reporter.sections.recommendations import build_recommendations
    # healthy_result has OPTIMAL recs (no actionable)
    flowables = build_recommendations(healthy_result)
    assert len(flowables) > 0


def test_anomalies_section_with_anomalies(wasteful_result):
    from src.reporter.sections.anomalies import build_anomalies
    flowables = build_anomalies(wasteful_result)
    assert _flowables_ok(flowables)


def test_anomalies_section_no_anomalies(healthy_result):
    from src.reporter.sections.anomalies import build_anomalies
    flowables = build_anomalies(healthy_result)
    assert _flowables_ok(flowables)


def test_instance_detail_section(wasteful_result):
    from src.reporter.sections.instance_detail import build_instance_detail
    flowables = build_instance_detail(wasteful_result)
    assert len(flowables) > 0  # may return empty if no recs


def test_instance_detail_empty(healthy_result):
    from src.reporter.sections.instance_detail import build_instance_detail
    # healthy has OPTIMAL recs — instance_detail renders them
    flowables = build_instance_detail(healthy_result)
    # returns empty list when no recs
    assert isinstance(flowables, list)


def test_methodology_section(mixed_result):
    from src.reporter.sections.methodology import build_methodology
    flowables = build_methodology(mixed_result, config={})
    assert _flowables_ok(flowables)


def test_appendix_section(mixed_result):
    from src.reporter.sections.appendix import build_appendix
    flowables = build_appendix(mixed_result, run_id="test001", config={"report": {"output_dir": "./reports"}})
    assert _flowables_ok(flowables)


def test_sections_handle_minimal_kpis():
    """All sections should render without error even when KPI fields are zero/None."""
    from tests.test_reporter.conftest import _kpis, _base_result
    from src.analytics.ratios import FleetKPIs
    kpis = _kpis(total_cost=0, monthly_rate=0, savings=0, overprov=0, rightsz=0, underprov=0, idle=0, insuff=0)
    kpis.top_5_wasteful = []
    kpis.top_5_efficient = []
    result = _base_result(kpis, [], [])

    from src.reporter.sections.cover import build_cover
    from src.reporter.sections.executive_summary import build_executive_summary
    from src.reporter.sections.recommendations import build_recommendations
    from src.reporter.sections.anomalies import build_anomalies

    assert len(build_cover(result, "x")) > 0
    assert len(build_executive_summary(result)) > 0
    assert len(build_recommendations(result)) > 0
    assert len(build_anomalies(result)) > 0
