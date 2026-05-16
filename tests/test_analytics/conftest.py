"""Shared fixtures for analytics tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"
_SCENARIO_FILE = _FIXTURES_DIR / "scenario_mixed_raw.json"


def _minimal_raw() -> dict:
    """Minimal synthetic raw JSON that covers all sections."""
    return {
        "period_start": "2026-03-23T00:00:00+00:00",
        "period_end": "2026-04-07T00:00:00+00:00",
        "fx_rates": {"EUR": 1.09},
        "instances": [
            {
                "ocid": "ocid1.instance.oc1.iad.idle-01",
                "display_name": "idle-01",
                "shape": "VM.Standard.E4.Flex",
                "shape_config": {"ocpu": 8, "ram_gb": 64},
                "region": "us-ashburn-1",
                "compartment_id": "ocid1.compartment.oc1..aaaatest",
                "lifecycle_state": "RUNNING",
                "cpu": {"avg": 1.0, "p50": 1.0, "p95": 2.0, "p99": 2.5, "peak": 3.0},
                "memory": {"avg": 5.0, "p50": 5.0, "p95": 6.0, "p99": 6.5, "peak": 7.0},
                "metrics_timeseries": None,
            },
            {
                "ocid": "ocid1.instance.oc1.iad.steady-01",
                "display_name": "steady-01",
                "shape": "VM.Standard.E4.Flex",
                "shape_config": {"ocpu": 4, "ram_gb": 32},
                "region": "us-ashburn-1",
                "compartment_id": "ocid1.compartment.oc1..aaaatest",
                "lifecycle_state": "RUNNING",
                "cpu": {"avg": 50.0, "p50": 50.0, "p95": 55.0, "p99": 57.0, "peak": 60.0},
                "memory": {"avg": 40.0, "p50": 40.0, "p95": 45.0, "p99": 47.0, "peak": 50.0},
                "metrics_timeseries": None,
            },
        ],
        "volumes": [
            {
                "ocid": "ocid1.volume.oc1.iad.vol-01",
                "display_name": "vol-01",
                "size_gb": 100,
                "vpu_per_gb": 10,
                "lifecycle_state": "AVAILABLE",
                "compartment_id": "ocid1.compartment.oc1..aaaatest",
                "region": "us-ashburn-1",
                "attached_instance_id": "ocid1.instance.oc1.iad.steady-01",
            }
        ],
        "cost_records": [
            {
                "resource_id": "ocid1.instance.oc1.iad.idle-01",
                "service": "COMPUTE",
                "compartment_id": "ocid1.compartment.oc1..aaaatest",
                "sku_description": "VM.Standard.E4.Flex",
                "currency": "USD",
                "total_cost": 200.0,
                "period_start": "2026-03-23T00:00:00+00:00",
                "period_end": "2026-04-07T00:00:00+00:00",
            },
            {
                "resource_id": "ocid1.instance.oc1.iad.steady-01",
                "service": "COMPUTE",
                "compartment_id": "ocid1.compartment.oc1..aaaatest",
                "sku_description": "VM.Standard.E4.Flex",
                "currency": "USD",
                "total_cost": 150.0,
                "period_start": "2026-03-23T00:00:00+00:00",
                "period_end": "2026-04-07T00:00:00+00:00",
            },
        ],
    }


@pytest.fixture(scope="session")
def raw_json_path(tmp_path_factory) -> Path:
    """Write the scenario fixture (or synthetic fallback) to a temp file."""
    if _SCENARIO_FILE.exists():
        return _SCENARIO_FILE
    tmp = tmp_path_factory.mktemp("fixtures") / "synthetic_raw.json"
    tmp.write_text(json.dumps(_minimal_raw()), encoding="utf-8")
    return tmp


@pytest.fixture(scope="session")
def minimal_raw_path(tmp_path_factory) -> Path:
    """Always returns the minimal synthetic raw JSON path."""
    tmp = tmp_path_factory.mktemp("fixtures") / "minimal_raw.json"
    tmp.write_text(json.dumps(_minimal_raw()), encoding="utf-8")
    return tmp


@pytest.fixture(scope="session")
def empty_config() -> dict:
    return {}
