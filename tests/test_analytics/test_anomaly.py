"""Tests for src/analytics/anomaly.py — detect_anomalies()."""
from __future__ import annotations

import pandas as pd
import pytest

from src.analytics.anomaly import Anomaly, AnomalySeverity, detect_anomalies


def _empty() -> pd.DataFrame:
    return pd.DataFrame()


def _inst_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "instance_id": r["instance_id"],
        "display_name": r.get("display_name", r["instance_id"]),
        "shape": r.get("shape", "VM.Standard.E4.Flex"),
        "region": "us-ashburn-1",
        "compartment_id": "ocid1.compartment.oc1..aaaatest",
        "lifecycle_state": "RUNNING",
    } for r in rows])


def _util_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "instance_id": r["instance_id"],
        "cpu_p95": r.get("cpu_p95", 50.0),
        "network_in_p95": r.get("net_in", 500.0),
        "disk_read_iops_p95": r.get("disk", 100.0),
        "composite_score": r.get("score", 0.6),
        "pattern": r.get("pattern", "STEADY"),
        "has_memory_data": True,
    } for r in rows])


def _cost_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "instance_id": r["instance_id"],
        "total_cost": r.get("cost", 100.0),
        "composite_score": r.get("score", 0.6),
        "daily_cost_avg": r.get("cost", 100.0) / 15.0,
        "daily_cost_stddev": 0.0,
        "no_billing_data": False,
    } for r in rows])


# ── returns list ──────────────────────────────────────────────────────────────

def test_detect_anomalies_returns_list():
    assert isinstance(detect_anomalies(_empty(), _empty(), _empty(), _empty(), _empty()), list)


def test_empty_inputs_returns_empty():
    assert detect_anomalies(_empty(), _empty(), _empty(), _empty(), _empty()) == []


# ── zombie detection ──────────────────────────────────────────────────────────

def test_zombie_detected_near_zero_cpu():
    iid = "ocid1.instance.oc1.iad.zombie01"
    inst = _inst_df([{"instance_id": iid}])
    util = _util_df([{"instance_id": iid, "cpu_p95": 0.5, "net_in": 10.0, "disk": 0.5}])
    cost = _cost_df([{"instance_id": iid, "cost": 200.0}])
    anomalies = detect_anomalies(inst, util, cost, _empty(), _empty())
    assert any(a.signal == "zombie" for a in anomalies)


def test_zombie_severity_is_critical():
    iid = "ocid1.instance.oc1.iad.zombie02"
    inst = _inst_df([{"instance_id": iid}])
    util = _util_df([{"instance_id": iid, "cpu_p95": 0.5, "net_in": 10.0, "disk": 0.5}])
    cost = _cost_df([{"instance_id": iid, "cost": 200.0}])
    anomalies = detect_anomalies(inst, util, cost, _empty(), _empty())
    zombies = [a for a in anomalies if a.signal == "zombie"]
    assert zombies[0].severity == AnomalySeverity.CRITICAL


def test_zombie_recoverable_positive():
    iid = "ocid1.instance.oc1.iad.zombie03"
    inst = _inst_df([{"instance_id": iid}])
    util = _util_df([{"instance_id": iid, "cpu_p95": 0.5, "net_in": 5.0, "disk": 0.5}])
    cost = _cost_df([{"instance_id": iid, "cost": 150.0}])
    anomalies = detect_anomalies(inst, util, cost, _empty(), _empty())
    zombies = [a for a in anomalies if a.signal == "zombie"]
    assert zombies[0].estimated_recoverable_amount > 0.0


def test_active_instance_not_a_zombie():
    iid = "ocid1.instance.oc1.iad.active01"
    inst = _inst_df([{"instance_id": iid}])
    util = _util_df([{"instance_id": iid, "cpu_p95": 60.0, "net_in": 5000.0, "disk": 500.0}])
    cost = _cost_df([{"instance_id": iid, "cost": 200.0}])
    anomalies = detect_anomalies(inst, util, cost, _empty(), _empty())
    assert not any(a.signal == "zombie" and a.resource_id == iid for a in anomalies)


# ── Anomaly dataclass ─────────────────────────────────────────────────────────

def test_anomaly_fields_populated():
    iid = "ocid1.instance.oc1.iad.zombie04"
    inst = _inst_df([{"instance_id": iid}])
    util = _util_df([{"instance_id": iid, "cpu_p95": 0.5, "net_in": 5.0, "disk": 0.5}])
    cost = _cost_df([{"instance_id": iid, "cost": 100.0}])
    anomalies = detect_anomalies(inst, util, cost, _empty(), _empty())
    a = next(x for x in anomalies if x.signal == "zombie")
    assert isinstance(a, Anomaly)
    assert a.resource_id == iid
    assert a.severity in list(AnomalySeverity)
    assert a.description
    assert a.suggested_action
    assert isinstance(a.estimated_recoverable_amount, float)


# ── AnomalySeverity enum ──────────────────────────────────────────────────────

def test_severity_enum_values():
    assert AnomalySeverity.CRITICAL.value == "critical"
    assert AnomalySeverity.WARNING.value == "warning"
    assert AnomalySeverity.INFO.value == "info"


# ── stranded volumes ──────────────────────────────────────────────────────────

def test_stranded_volume_detected():
    vol_df = pd.DataFrame([{
        "volume_id": "ocid1.volume.oc1.iad.vol01",
        "display_name": "orphan-vol",
        "size_gb": 500,
        "lifecycle_state": "AVAILABLE",
        "compartment_id": "ocid1.compartment.oc1..aaaatest",
        "region": "us-ashburn-1",
        "attached_instance_id": "",
    }])
    anomalies = detect_anomalies(_empty(), _empty(), _empty(), vol_df, _empty())
    assert any(a.signal == "stranded_volume" for a in anomalies)
