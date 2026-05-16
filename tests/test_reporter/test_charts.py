"""
Tests for src/reporter/charts/*.py
Each chart function must:
- Return BytesIO with PNG header
- Handle empty data without raising
- Respect the DPI parameter (implicitly via CHART_DPI)
"""
from __future__ import annotations

from io import BytesIO

import pytest

from src.reporter.charts.distribution import chart_score_distribution
from src.reporter.charts.heatmap import chart_utilization_heatmap
from src.reporter.charts.scatter import chart_cost_utilization_scatter
from src.reporter.charts.trend import chart_daily_cost_trend
from src.reporter.charts.treemap import chart_cost_treemap
from src.reporter.charts.waterfall import chart_savings_waterfall


_PNG_HEADER = b"\x89PNG"


def _is_png(buf: BytesIO) -> bool:
    buf.seek(0)
    return buf.read(4) == _PNG_HEADER


# ── treemap ──────────────────────────────────────────────────────────────────

def test_treemap_returns_png():
    data = [
        {"name": f"inst-{i}", "total_cost": 100.0 * (i + 1), "composite_score": 0.3 + i * 0.05}
        for i in range(10)
    ]
    buf = chart_cost_treemap(data)
    assert _is_png(buf)


def test_treemap_empty_data_returns_placeholder():
    buf = chart_cost_treemap([])
    assert _is_png(buf)


def test_treemap_zero_costs_returns_placeholder():
    data = [{"name": "x", "total_cost": 0, "composite_score": 0}]
    buf = chart_cost_treemap(data)
    assert _is_png(buf)


# ── scatter ──────────────────────────────────────────────────────────────────

def test_scatter_returns_png():
    data = [
        {"name": f"inst-{i}", "composite_score": 0.2 + i * 0.1, "monthly_cost": 200.0 + i * 50, "vcpu_count": 2 + i}
        for i in range(8)
    ]
    buf = chart_cost_utilization_scatter(data)
    assert _is_png(buf)


def test_scatter_empty_returns_placeholder():
    buf = chart_cost_utilization_scatter([])
    assert _is_png(buf)


def test_scatter_single_instance():
    buf = chart_cost_utilization_scatter([
        {"name": "only-one", "composite_score": 0.5, "monthly_cost": 300.0, "vcpu_count": 4}
    ])
    assert _is_png(buf)


# ── distribution ─────────────────────────────────────────────────────────────

def test_distribution_returns_png():
    scores = [0.1, 0.2, 0.35, 0.5, 0.6, 0.75, 0.9]
    buf = chart_score_distribution(scores)
    assert _is_png(buf)


def test_distribution_empty_returns_placeholder():
    buf = chart_score_distribution([])
    assert _is_png(buf)


def test_distribution_all_same_score():
    buf = chart_score_distribution([0.5] * 20)
    assert _is_png(buf)


# ── trend ─────────────────────────────────────────────────────────────────────

def test_trend_returns_png():
    daily = [{"date": f"2026-03-{i + 1:02d}", "cost": 100.0 + i * 5} for i in range(15)]
    buf = chart_daily_cost_trend(daily)
    assert _is_png(buf)


def test_trend_with_anomaly_markers():
    daily = [{"date": f"2026-03-{i + 1:02d}", "cost": 200.0} for i in range(15)]
    buf = chart_daily_cost_trend(daily, anomaly_dates=["2026-03-05", "2026-03-10"])
    assert _is_png(buf)


def test_trend_empty_returns_placeholder():
    buf = chart_daily_cost_trend([])
    assert _is_png(buf)


def test_trend_single_day_returns_placeholder():
    buf = chart_daily_cost_trend([{"date": "2026-03-01", "cost": 100.0}])
    assert _is_png(buf)


# ── waterfall ─────────────────────────────────────────────────────────────────

def test_waterfall_returns_png():
    buf = chart_savings_waterfall(
        current_monthly_cost=5000.0,
        downsize_savings=800.0,
        terminate_savings=400.0,
        orphaned_savings=100.0,
    )
    assert _is_png(buf)


def test_waterfall_zero_current_cost_returns_placeholder():
    buf = chart_savings_waterfall(0.0, 0.0, 0.0, 0.0)
    assert _is_png(buf)


def test_waterfall_no_savings():
    buf = chart_savings_waterfall(3000.0, 0.0, 0.0, 0.0)
    assert _is_png(buf)


# ── heatmap ───────────────────────────────────────────────────────────────────

def test_heatmap_returns_png():
    metrics = [
        {"name": f"inst-{i}", "cpu_p95": 25.0 + i * 5, "memory_p95": 30.0,
         "network_in_p95": 1000.0, "disk_read_iops_p95": 50.0}
        for i in range(10)
    ]
    buf = chart_utilization_heatmap(metrics)
    assert _is_png(buf)


def test_heatmap_empty_returns_placeholder():
    buf = chart_utilization_heatmap([])
    assert _is_png(buf)


def test_heatmap_missing_memory():
    metrics = [{"name": "x", "cpu_p95": 20.0, "memory_p95": None,
                "network_in_p95": 0.0, "disk_read_iops_p95": 0.0}]
    buf = chart_utilization_heatmap(metrics)
    assert _is_png(buf)
