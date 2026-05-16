"""Tests for src/analytics/loader.py — load_raw()."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.analytics.loader import ValidationReport, load_raw


def _write_raw(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "test_raw.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _instance(ocid: str = "ocid1.instance.oc1.iad.inst01", cpu_p95: float = 50.0) -> dict:
    return {
        "ocid": ocid,
        "display_name": ocid.split(".")[-1],
        "shape": "VM.Standard.E4.Flex",
        "region": "us-ashburn-1",
        "compartment_id": "ocid1.compartment.oc1..aaaatest",
        "lifecycle_state": "RUNNING",
        "cpu": {"avg": cpu_p95 * 0.9, "p50": cpu_p95 * 0.95, "p95": cpu_p95, "p99": cpu_p95 * 1.05, "peak": cpu_p95 * 1.1},
        "memory": {"avg": 30.0, "p50": 30.0, "p95": 35.0, "p99": 37.0, "peak": 40.0},
        "metrics_timeseries": None,
    }


def _cost(resource_id: str, total_cost: float = 100.0, currency: str = "USD") -> dict:
    return {
        "resource_id": resource_id,
        "service": "COMPUTE",
        "compartment_id": "ocid1.compartment.oc1..aaaatest",
        "sku_description": "VM.Standard.E4.Flex",
        "currency": currency,
        "total_cost": total_cost,
        "period_start": "2026-03-23T00:00:00+00:00",
        "period_end": "2026-04-07T00:00:00+00:00",
    }


# ── basic structure ───────────────────────────────────────────────────────────

def test_load_raw_returns_6_tuple(minimal_raw_path, empty_config):
    result = load_raw(minimal_raw_path, empty_config)
    assert len(result) == 6


def test_load_raw_instances_df_has_rows(minimal_raw_path, empty_config):
    instances_df, *_ = load_raw(minimal_raw_path, empty_config)
    assert not instances_df.empty
    assert "instance_id" in instances_df.columns


def test_load_raw_costs_df_has_rows(minimal_raw_path, empty_config):
    _, _, costs_df, _, _, _ = load_raw(minimal_raw_path, empty_config)
    assert not costs_df.empty


def test_load_raw_volumes_df_has_rows(minimal_raw_path, empty_config):
    _, _, _, volumes_df, _, _ = load_raw(minimal_raw_path, empty_config)
    assert not volumes_df.empty


def test_load_raw_report_is_validation_report(minimal_raw_path, empty_config):
    *_, report = load_raw(minimal_raw_path, empty_config)
    assert isinstance(report, ValidationReport)


# ── missing fields → violations, not crash ───────────────────────────────────

def test_missing_instance_fields_recorded_as_violations(tmp_path, empty_config):
    # 1 bad instance creates 3 violations; need total_records > 60 to stay below 5% threshold
    valid = [_instance(f"ocid1.instance.oc1.iad.good{i:03d}") for i in range(100)]
    data = {
        "instances": valid + [
            {"ocid": "ocid1.instance.oc1.iad.bad01", "display_name": "bad01", "lifecycle_state": "RUNNING"}
        ],
        "volumes": [],
        "cost_records": [],
    }
    p = _write_raw(tmp_path, data)
    _, _, _, _, _, report = load_raw(p, empty_config)
    assert len(report.violations) > 0
    fields_violated = {v.field for v in report.violations}
    assert "shape" in fields_violated or "region" in fields_violated


def test_missing_cost_resource_id_recorded(tmp_path, empty_config):
    # Add enough valid cost records so 1 violation stays below 5%
    valid_costs = [_cost(f"ocid1.instance.oc1.iad.inst{i:02d}") for i in range(20)]
    data = {
        "instances": [_instance()],
        "volumes": [],
        "cost_records": valid_costs + [{"service": "COMPUTE", "currency": "USD", "total_cost": 100.0}],
    }
    p = _write_raw(tmp_path, data)
    _, _, _, _, _, report = load_raw(p, empty_config)
    assert any(v.field == "resource_id" for v in report.violations)


# ── empty sections → empty DataFrames ────────────────────────────────────────

def test_empty_instances_returns_empty_df(tmp_path, empty_config):
    p = _write_raw(tmp_path, {"instances": [], "volumes": [], "cost_records": []})
    instances_df, metrics_df, costs_df, volumes_df, buckets_df, report = load_raw(p, empty_config)
    assert instances_df.empty
    assert metrics_df.empty
    assert costs_df.empty
    assert volumes_df.empty
    assert buckets_df.empty
    assert report.total_records == 0


# ── file errors ───────────────────────────────────────────────────────────────

def test_missing_file_raises(tmp_path, empty_config):
    with pytest.raises(FileNotFoundError):
        load_raw(tmp_path / "nonexistent.json", empty_config)


def test_invalid_json_raises(tmp_path, empty_config):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(Exception):
        load_raw(p, empty_config)


# ── currency normalization ────────────────────────────────────────────────────

def test_usd_cost_usd_equals_original(tmp_path, empty_config):
    data = {
        "instances": [_instance()],
        "volumes": [],
        "cost_records": [_cost("ocid1.instance.oc1.iad.inst01", 250.0, "USD")],
    }
    p = _write_raw(tmp_path, data)
    _, _, costs_df, _, _, _ = load_raw(p, empty_config)
    row = costs_df[costs_df["resource_id"] == "ocid1.instance.oc1.iad.inst01"].iloc[0]
    assert row["cost_usd"] == pytest.approx(250.0)


def test_known_currency_converted(tmp_path):
    config = {"fx_rates": {"EUR": 1.1}}
    data = {
        "instances": [_instance()],
        "volumes": [],
        "cost_records": [_cost("ocid1.instance.oc1.iad.inst01", 100.0, "EUR")],
    }
    p = _write_raw(tmp_path, data)
    _, _, costs_df, _, _, _ = load_raw(p, config)
    row = costs_df[costs_df["resource_id"] == "ocid1.instance.oc1.iad.inst01"].iloc[0]
    assert row["cost_usd"] == pytest.approx(110.0)


def test_unknown_currency_cost_usd_nan(tmp_path, empty_config):
    data = {
        "instances": [_instance()],
        "volumes": [],
        "cost_records": [_cost("ocid1.instance.oc1.iad.inst01", 100.0, "XYZ")],
    }
    p = _write_raw(tmp_path, data)
    _, _, costs_df, _, _, report = load_raw(p, empty_config)
    assert math.isnan(costs_df.iloc[0]["cost_usd"])
    assert "XYZ" in report.currencies_missing_rates


def test_validation_report_total_records(minimal_raw_path, empty_config):
    *_, report = load_raw(minimal_raw_path, empty_config)
    assert report.total_records > 0
    assert isinstance(report.passed, bool)
