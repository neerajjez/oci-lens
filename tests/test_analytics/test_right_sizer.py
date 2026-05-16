"""Tests for src/analytics/right_sizer.py — generate_recommendations()."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.analytics.right_sizer import (
    Recommendation,
    RecommendationType,
    generate_recommendations,
)
from src.analytics.shape_catalog import ShapeCatalog

_CATALOG_PATH = Path(__file__).parents[2] / "config" / "shapes.json"


def _catalog() -> ShapeCatalog:
    return ShapeCatalog(_CATALOG_PATH)


def _inst_row(
    iid: str = "ocid1.instance.oc1.iad.i01",
    shape: str = "VM.Standard.E4.Flex",
    cpu_p95: float = 50.0,
    cpu_p99: float = 52.0,
    sufficient_data: bool = True,
    ocpu: int = 8,
    ram_gb: int = 64,
) -> dict:
    return {
        "instance_id": iid,
        "display_name": iid.split(".")[-1],
        "shape": shape,
        "shape_config": {"ocpu": ocpu, "ram_gb": ram_gb},
        "region": "us-ashburn-1",
        "compartment_id": "ocid1.compartment.oc1..aaaatest",
        "lifecycle_state": "RUNNING",
        "sufficient_data": sufficient_data,
        "data_coverage_days": 15.0 if sufficient_data else 0.5,
        "data_coverage_hours": 360.0 if sufficient_data else 12.0,
        "has_timeseries": False,
        "cpu_avg": cpu_p95 * 0.9,
        "cpu_p50": cpu_p95 * 0.95,
        "cpu_p95": cpu_p95,
        "cpu_p99": cpu_p99,
        "cpu_peak": cpu_p99 * 1.05,
        "memory_avg": 30.0,
        "memory_p50": 30.0,
        "memory_p95": 35.0,
        "memory_p99": 37.0,
        "memory_peak": 40.0,
    }


def _util_row(iid: str, cpu_p95: float = 50.0, pattern: str = "STEADY") -> dict:
    return {
        "instance_id": iid,
        "cpu_p95": cpu_p95,
        "cpu_p99": cpu_p95 * 1.04,
        "cpu_median": cpu_p95 * 0.95,
        "memory_p95": 35.0,
        "network_in_p95": 500.0,
        "network_out_p95": 300.0,
        "composite_score": 0.6,
        "pattern": pattern,
        "has_memory_data": True,
        "has_timeseries": False,
        "io_utilization_pct": 5.0,
    }


def _cost_row(iid: str, total_cost: float = 150.0) -> dict:
    return {
        "instance_id": iid,
        "total_cost": total_cost,
        "no_billing_data": False,
    }


def _build(iid: str, cpu_p95: float, pattern: str, cost: float, sufficient: bool):
    inst = pd.DataFrame([_inst_row(iid=iid, cpu_p95=cpu_p95, sufficient_data=sufficient)])
    util = pd.DataFrame([_util_row(iid=iid, cpu_p95=cpu_p95, pattern=pattern)])
    cost_df = pd.DataFrame([_cost_row(iid=iid, total_cost=cost)])
    return inst, util, cost_df


# ── basic contract ────────────────────────────────────────────────────────────

def test_returns_list():
    inst, util, cost = _build("ocid1.instance.oc1.iad.i01", 50.0, "STEADY", 150.0, True)
    assert isinstance(generate_recommendations(inst, util, cost, _catalog()), list)


def test_one_recommendation_per_instance():
    inst = pd.DataFrame([
        _inst_row("ocid1.instance.oc1.iad.i01"),
        _inst_row("ocid1.instance.oc1.iad.i02"),
    ])
    util = pd.DataFrame([
        _util_row("ocid1.instance.oc1.iad.i01"),
        _util_row("ocid1.instance.oc1.iad.i02"),
    ])
    cost = pd.DataFrame([
        _cost_row("ocid1.instance.oc1.iad.i01"),
        _cost_row("ocid1.instance.oc1.iad.i02"),
    ])
    assert len(generate_recommendations(inst, util, cost, _catalog())) == 2


def test_empty_instances_returns_empty():
    assert generate_recommendations(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), _catalog()) == []


# ── MONITOR for insufficient data ─────────────────────────────────────────────

def test_monitor_for_insufficient_data():
    inst, util, cost = _build("ocid1.instance.oc1.iad.i01", 50.0, "STEADY", 150.0, False)
    result = generate_recommendations(inst, util, cost, _catalog())
    assert result[0].recommendation_type == RecommendationType.MONITOR


# ── Recommendation fields ─────────────────────────────────────────────────────

def test_recommendation_has_required_fields():
    inst, util, cost = _build("ocid1.instance.oc1.iad.i01", 50.0, "STEADY", 150.0, True)
    rec = generate_recommendations(inst, util, cost, _catalog())[0]
    assert isinstance(rec, Recommendation)
    assert rec.instance_id == "ocid1.instance.oc1.iad.i01"
    assert rec.recommendation_type in RecommendationType.__members__.values()
    assert isinstance(rec.rationale, str) and len(rec.rationale) > 0


def test_confidence_score_in_0_1():
    inst, util, cost = _build("ocid1.instance.oc1.iad.i01", 50.0, "STEADY", 150.0, True)
    rec = generate_recommendations(inst, util, cost, _catalog())[0]
    assert 0.0 <= rec.confidence_score <= 1.0


def test_savings_pct_consistent_with_costs():
    inst, util, cost = _build("ocid1.instance.oc1.iad.i01", 5.0, "IDLE", 200.0, True)
    rec = generate_recommendations(inst, util, cost, _catalog())[0]
    if rec.current_monthly_cost > 0 and rec.estimated_monthly_savings > 0:
        expected = rec.estimated_monthly_savings / rec.current_monthly_cost * 100.0
        assert rec.savings_pct == pytest.approx(expected, abs=1.0)


def test_recommendation_type_is_valid_enum():
    inst, util, cost = _build("ocid1.instance.oc1.iad.i01", 70.0, "STEADY", 150.0, True)
    rec = generate_recommendations(inst, util, cost, _catalog())[0]
    assert rec.recommendation_type in list(RecommendationType)
