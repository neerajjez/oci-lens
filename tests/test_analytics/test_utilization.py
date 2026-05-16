"""Tests for src/analytics/utilization.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analytics.utilization import (
    UtilizationPattern,
    profile_utilization,
    sigmoid_score,
)


# ── sigmoid_score ─────────────────────────────────────────────────────────────

def test_sigmoid_zero_value_returns_zero():
    assert sigmoid_score(0.0, 70.0) == 0.0


def test_sigmoid_at_target_returns_one():
    assert sigmoid_score(70.0, 70.0) == pytest.approx(1.0)


def test_sigmoid_above_target_decays():
    assert sigmoid_score(100.0, 70.0) < sigmoid_score(70.0, 70.0)


def test_sigmoid_below_target_less_than_one():
    assert 0.0 < sigmoid_score(35.0, 70.0) < 1.0


def test_sigmoid_bounded_in_0_1():
    for v in [0, 10, 35, 70, 85, 100, 150]:
        s = sigmoid_score(float(v), 70.0)
        assert 0.0 <= s <= 1.0, f"sigmoid({v}) = {s} out of [0,1]"


def test_sigmoid_invalid_target_returns_zero():
    assert sigmoid_score(50.0, 0.0) == 0.0


# ── instance DataFrame builder ────────────────────────────────────────────────

def _inst_df(instances: list[dict]) -> pd.DataFrame:
    rows = []
    for i in instances:
        rows.append({
            "instance_id": i["instance_id"],
            "display_name": i.get("display_name", i["instance_id"]),
            "shape": i.get("shape", "VM.Standard.E4.Flex"),
            "region": i.get("region", "us-ashburn-1"),
            "compartment_id": i.get("compartment_id", "ocid1.compartment.oc1..aaa"),
            "lifecycle_state": i.get("lifecycle_state", "RUNNING"),
            "has_timeseries": i.get("has_timeseries", False),
            "data_coverage_hours": i.get("data_coverage_hours", 360.0),
            "data_coverage_days": i.get("data_coverage_days", 15.0),
            "sufficient_data": i.get("sufficient_data", True),
            "cpu_avg": i.get("cpu_avg", 50.0),
            "cpu_p50": i.get("cpu_p50", 50.0),
            "cpu_p95": i.get("cpu_p95", 55.0),
            "cpu_p99": i.get("cpu_p99", 57.0),
            "cpu_peak": i.get("cpu_peak", 60.0),
            "memory_avg": i.get("memory_avg", 40.0),
            "memory_p50": i.get("memory_p50", 40.0),
            "memory_p95": i.get("memory_p95", 45.0),
            "memory_p99": i.get("memory_p99", 47.0),
            "memory_peak": i.get("memory_peak", 50.0),
        })
    return pd.DataFrame(rows)


def _empty_metrics() -> pd.DataFrame:
    return pd.DataFrame(columns=["instance_id", "metric_name", "timestamp", "value"])


# ── profile_utilization output contract ───────────────────────────────────────

def test_profile_returns_dataframe():
    result = profile_utilization(_inst_df([{"instance_id": "i01"}]), _empty_metrics())
    assert isinstance(result, pd.DataFrame)


def test_profile_has_composite_score_column():
    result = profile_utilization(_inst_df([{"instance_id": "i01"}]), _empty_metrics())
    assert "composite_score" in result.columns


def test_profile_one_row_per_instance():
    inst = _inst_df([{"instance_id": "i01"}, {"instance_id": "i02"}])
    result = profile_utilization(inst, _empty_metrics())
    assert len(result) == 2


def test_profile_composite_score_in_0_1():
    inst = _inst_df([
        {"instance_id": "i01", "cpu_p95": 70.0},
        {"instance_id": "i02", "cpu_p95": 2.0},
        {"instance_id": "i03", "cpu_p95": 95.0},
    ])
    for score in profile_utilization(inst, _empty_metrics())["composite_score"]:
        assert 0.0 <= score <= 1.0


def test_profile_empty_instances_returns_empty():
    assert profile_utilization(pd.DataFrame(), _empty_metrics()).empty


# ── pattern detection ─────────────────────────────────────────────────────────

def test_idle_pattern_very_low_cpu():
    inst = _inst_df([{"instance_id": "idle", "cpu_p95": 2.0, "cpu_p99": 2.5}])
    result = profile_utilization(inst, _empty_metrics())
    assert result.iloc[0]["pattern"] == UtilizationPattern.IDLE.value


def test_steady_pattern_low_spread():
    # p25 = (avg+p50)/2 = (50+50)/2 = 50; p95 = 55 → spread = 5 < 15 → STEADY
    inst = _inst_df([{
        "instance_id": "steady",
        "cpu_avg": 50.0, "cpu_p50": 50.0, "cpu_p95": 55.0, "cpu_p99": 56.0,
    }])
    result = profile_utilization(inst, _empty_metrics())
    assert result.iloc[0]["pattern"] == UtilizationPattern.STEADY.value


def test_erratic_or_bursty_high_spread():
    # p25 = (0+0)/2 = 0; p95 = 90 → spread = 90 >= 40
    inst = _inst_df([{
        "instance_id": "erratic",
        "cpu_avg": 0.0, "cpu_p50": 0.0, "cpu_p95": 90.0, "cpu_p99": 92.0,
    }])
    result = profile_utilization(inst, _empty_metrics())
    assert result.iloc[0]["pattern"] in (
        UtilizationPattern.ERRATIC.value,
        UtilizationPattern.BURSTY.value,
    )


# ── no memory data → cpu+io weights only ─────────────────────────────────────

def test_no_memory_data_memory_score_zero():
    inst = _inst_df([{
        "instance_id": "nomem",
        "cpu_p95": 70.0,
        "memory_avg": 0.0, "memory_p50": 0.0, "memory_p95": 0.0,
        "memory_p99": 0.0, "memory_peak": 0.0,
    }])
    result = profile_utilization(inst, _empty_metrics())
    row = result.iloc[0]
    assert not row["has_memory_data"]
    assert row["memory_score"] == 0.0
    assert row["composite_score"] > 0.0


def test_aggregate_path_has_memory_data_false():
    # Without timeseries data, _build_row_from_aggregates always sets has_memory_data=False
    inst = _inst_df([{"instance_id": "withmem", "cpu_p95": 70.0, "memory_p95": 60.0}])
    result = profile_utilization(inst, _empty_metrics())
    row = result.iloc[0]
    # Aggregate path: no timeseries → has_memory_data is False by design
    assert not row["has_timeseries"]
    assert row["memory_score"] == 0.0
