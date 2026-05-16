"""Tests for src/analytics/ratios.py — compute_fleet_kpis()."""
from __future__ import annotations

import pandas as pd
import pytest

from src.analytics.ratios import FleetKPIs, compute_fleet_kpis
from src.analytics.right_sizer import (
    Recommendation,
    RecommendationType,
    RiskLevel,
    ShapeConfig,
)
from src.analytics.confidence import ConfidenceLabel


def _rec(
    iid: str,
    rec_type: RecommendationType,
    current_cost: float = 200.0,
    savings: float = 50.0,
) -> Recommendation:
    return Recommendation(
        instance_id=iid,
        instance_name=iid,
        recommendation_type=rec_type,
        current_shape="VM.Standard.E4.Flex",
        current_config=ShapeConfig(ocpu=4, ram_gb=32),
        recommended_shape="VM.Standard.E4.Flex",
        recommended_config=ShapeConfig(ocpu=2, ram_gb=16),
        current_monthly_cost=current_cost,
        estimated_monthly_cost=current_cost - savings,
        estimated_monthly_savings=savings,
        savings_pct=savings / current_cost * 100.0,
        confidence_score=0.8,
        confidence_label=ConfidenceLabel.HIGH,
        rationale="test",
    )


def _inst_df(ids: list[str], sufficient: bool = True) -> pd.DataFrame:
    return pd.DataFrame([{
        "instance_id": i,
        "cpu_p95": 50.0,
        "cpu_p99": 55.0,
        "sufficient_data": sufficient,
    } for i in ids])


def _util_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "instance_id": r["instance_id"],
        "composite_score": r.get("composite_score", 0.6),
        "cpu_p95": r.get("cpu_p95", 50.0),
        "cpu_p99": r.get("cpu_p99", 55.0),
        "memory_p95": r.get("memory_p95", 35.0),
        "pattern": r.get("pattern", "STEADY"),
        "has_memory_data": r.get("has_memory_data", True),
        "sufficient_data": r.get("sufficient_data", True),
    } for r in rows])


def _cost_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "instance_id": r["instance_id"],
        "total_cost": r.get("cost", 100.0),
    } for r in rows])


# ── return type ───────────────────────────────────────────────────────────────

def test_returns_fleet_kpis():
    kpis = compute_fleet_kpis(
        _inst_df(["i01", "i02"]),
        _util_df([{"instance_id": "i01"}, {"instance_id": "i02"}]),
        _cost_df([{"instance_id": "i01", "cost": 100.0}, {"instance_id": "i02", "cost": 150.0}]),
        [], 15, 0.0, None,
    )
    assert isinstance(kpis, FleetKPIs)


# ── cost aggregation ──────────────────────────────────────────────────────────

def test_total_fleet_cost_sums_correctly():
    kpis = compute_fleet_kpis(
        _inst_df(["i01", "i02"]),
        _util_df([{"instance_id": "i01"}, {"instance_id": "i02"}]),
        _cost_df([{"instance_id": "i01", "cost": 100.0}, {"instance_id": "i02", "cost": 200.0}]),
        [], 15, 0.0, None,
    )
    assert kpis.total_fleet_cost_period == pytest.approx(300.0)


def test_orphaned_cost_included():
    kpis = compute_fleet_kpis(
        _inst_df(["i01"]),
        _util_df([{"instance_id": "i01"}]),
        _cost_df([{"instance_id": "i01", "cost": 100.0}]),
        [], 15, 50.0, None,
    )
    assert kpis.orphaned_resource_cost == pytest.approx(50.0)


def test_potential_savings_non_negative():
    recs = [_rec("i01", RecommendationType.DOWNSIZE, savings=60.0)]
    kpis = compute_fleet_kpis(
        _inst_df(["i01"]),
        _util_df([{"instance_id": "i01"}]),
        _cost_df([{"instance_id": "i01", "cost": 200.0}]),
        recs, 15, 0.0, None,
    )
    assert kpis.total_potential_monthly_savings >= 0.0


# ── weighted composite score ──────────────────────────────────────────────────

def test_weighted_composite_score_bounded():
    kpis = compute_fleet_kpis(
        _inst_df(["i01", "i02", "i03"]),
        _util_df([
            {"instance_id": "i01", "composite_score": 0.3},
            {"instance_id": "i02", "composite_score": 0.7},
            {"instance_id": "i03", "composite_score": 0.5},
        ]),
        _cost_df([{"instance_id": i, "cost": 100.0} for i in ["i01", "i02", "i03"]]),
        [], 15, 0.0, None,
    )
    assert 0.0 <= kpis.weighted_composite_score <= 1.0


# ── distribution counts ───────────────────────────────────────────────────────

def test_idle_count_from_idle_pattern():
    kpis = compute_fleet_kpis(
        _inst_df(["i01", "i02"]),
        _util_df([
            {"instance_id": "i01", "pattern": "IDLE"},
            {"instance_id": "i02", "pattern": "STEADY"},
        ]),
        _cost_df([{"instance_id": i, "cost": 100.0} for i in ["i01", "i02"]]),
        [], 15, 0.0, None,
    )
    assert kpis.idle_count >= 1


def test_overprovisioned_count_non_negative():
    kpis = compute_fleet_kpis(
        _inst_df(["i01", "i02", "i03"]),
        _util_df([{"instance_id": i, "composite_score": 0.1, "sufficient_data": True} for i in ["i01", "i02", "i03"]]),
        _cost_df([{"instance_id": i, "cost": 100.0} for i in ["i01", "i02", "i03"]]),
        [], 15, 0.0, None,
    )
    assert kpis.overprovisioned_count >= 0


def test_distribution_counts_sum_to_at_most_fleet_size():
    ids = ["i01", "i02", "i03", "i04"]
    kpis = compute_fleet_kpis(
        _inst_df(ids),
        _util_df([{"instance_id": i} for i in ids]),
        _cost_df([{"instance_id": i, "cost": 100.0} for i in ids]),
        [], 15, 0.0, None,
    )
    total = (kpis.overprovisioned_count + kpis.rightsized_count +
             kpis.underprovisioned_count + kpis.insufficient_data_count)
    assert total <= len(ids)
