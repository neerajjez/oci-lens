"""
Fixture generator for OCI Resource Report tests.

Generates: tests/fixtures/scenario_mixed_raw.json

Run from project root:
    python tests/fixtures/generate_fixture.py
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
np.random.seed(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PERIOD_START = "2026-03-23T00:00:00+00:00"
PERIOD_END = "2026-04-07T00:00:00+00:00"
COLLECTED_AT = "2026-04-07T01:00:00+00:00"
COMPARTMENT_ID = "ocid1.compartment.oc1..aaaafixturecompartment"
REGIONS = ["us-ashburn-1", "eu-frankfurt-1"]
FX_RATES = {"EUR": 1.09, "GBP": 1.27}

# 360 hourly timestamps: 2026-03-23T00:00:00Z … 2026-04-06T23:00:00Z
N_FULL = 360
# 48 hourly timestamps for insufficient-data group
N_INSUFF = 48

# Base timestamps (ISO strings) for full series
_BASE_FULL = [
    f"2026-03-{23 + (h // 24):02d}T{h % 24:02d}:00:00+00:00"
    if (23 + h // 24) <= 31
    else f"2026-04-{(23 + h // 24) - 31:02d}T{h % 24:02d}:00:00+00:00"
    for h in range(N_FULL)
]

# Corrected timestamp generation using datetime arithmetic
from datetime import datetime, timedelta, timezone

_DT_START = datetime(2026, 3, 23, 0, 0, 0, tzinfo=timezone.utc)
_TIMESTAMPS_FULL = [
    (_DT_START + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    for h in range(N_FULL)
]

_DT_INSUFF_START = datetime(2026, 4, 5, 0, 0, 0, tzinfo=timezone.utc)
_TIMESTAMPS_INSUFF = [
    (_DT_INSUFF_START + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    for h in range(N_INSUFF)
]


# ---------------------------------------------------------------------------
# Helper: compute aggregated stats from a 1-D array of values
# ---------------------------------------------------------------------------
def _stats(vals: np.ndarray) -> dict:
    return {
        "avg": round(float(np.mean(vals)), 4),
        "p50": round(float(np.percentile(vals, 50)), 4),
        "p95": round(float(np.percentile(vals, 95)), 4),
        "p99": round(float(np.percentile(vals, 99)), 4),
        "peak": round(float(np.max(vals)), 4),
    }


def _ts_list(timestamps: list[str], vals: np.ndarray) -> list[dict]:
    return [{"ts": ts, "v": round(float(v), 4)} for ts, v in zip(timestamps, vals)]


# ---------------------------------------------------------------------------
# Helper: Normal with clip
# ---------------------------------------------------------------------------
def _normal(mean: float, std: float, size: int, lo: float, hi: float) -> np.ndarray:
    return np.clip(np.random.normal(mean, std, size), lo, hi)


# ---------------------------------------------------------------------------
# Instance builder
# ---------------------------------------------------------------------------
def _make_instance(
    name: str,
    shape: str,
    ocpu: int,
    ram_gb: int,
    region: str,
    metrics_timeseries: dict,
    timestamps: list[str],
) -> dict:
    ocid = f"ocid1.instance.oc1.iad.{name}"
    cpu_vals = np.array([p["v"] for p in metrics_timeseries["cpu_utilization"]])
    mem_vals = np.array([p["v"] for p in metrics_timeseries["memory_utilization"]])

    cpu_stats = _stats(cpu_vals)
    mem_stats = _stats(mem_vals)

    # Network and disk fields — derive from timeseries if present, else null
    net_in_vals = np.array([p["v"] for p in metrics_timeseries.get("network_in_kbps", [])])
    net_out_vals = np.array([p["v"] for p in metrics_timeseries.get("network_out_kbps", [])])
    disk_read_vals = np.array([p["v"] for p in metrics_timeseries.get("disk_read_iops", [])])
    disk_write_vals = np.array([p["v"] for p in metrics_timeseries.get("disk_write_iops", [])])

    network = {
        "bytes_in_avg": round(float(np.mean(net_in_vals)), 4) if len(net_in_vals) > 0 else None,
        "bytes_out_avg": round(float(np.mean(net_out_vals)), 4) if len(net_out_vals) > 0 else None,
        "bytes_in_peak": round(float(np.max(net_in_vals)), 4) if len(net_in_vals) > 0 else None,
        "bytes_out_peak": round(float(np.max(net_out_vals)), 4) if len(net_out_vals) > 0 else None,
    }
    disk = {
        "read_ops_avg": round(float(np.mean(disk_read_vals)), 4) if len(disk_read_vals) > 0 else None,
        "write_ops_avg": round(float(np.mean(disk_write_vals)), 4) if len(disk_write_vals) > 0 else None,
        "read_bytes_avg": None,
        "write_bytes_avg": None,
    }

    return {
        "ocid": ocid,
        "display_name": name,
        "shape": shape,
        "shape_config": {"ocpu": ocpu, "ram_gb": ram_gb},
        "region": region,
        "compartment_id": COMPARTMENT_ID,
        "lifecycle_state": "RUNNING",
        "time_created": "2025-01-15T10:00:00+00:00",
        "collected_at": COLLECTED_AT,
        "cpu": cpu_stats,
        "memory": mem_stats,
        "network": network,
        "disk": disk,
        "cost": None,
        "metrics_timeseries": metrics_timeseries,
    }


# ---------------------------------------------------------------------------
# Standard network/disk generators (shared across groups)
# ---------------------------------------------------------------------------
def _std_network(n: int) -> tuple[np.ndarray, np.ndarray]:
    net_in = _normal(500, 50, n, 100, 900)
    net_out = _normal(300, 30, n, 50, 600)
    return net_in, net_out


def _std_disk(n: int) -> tuple[np.ndarray, np.ndarray]:
    disk_r = _normal(100, 15, n, 10, 200)
    disk_w = _normal(80, 12, n, 5, 150)
    return disk_r, disk_w


def _build_timeseries(
    timestamps: list[str],
    cpu: np.ndarray,
    mem: np.ndarray,
    net_in: np.ndarray | None = None,
    net_out: np.ndarray | None = None,
    disk_r: np.ndarray | None = None,
    disk_w: np.ndarray | None = None,
) -> dict:
    ts: dict = {
        "cpu_utilization": _ts_list(timestamps, cpu),
        "memory_utilization": _ts_list(timestamps, mem),
    }
    if net_in is not None:
        ts["network_in_kbps"] = _ts_list(timestamps, net_in)
    if net_out is not None:
        ts["network_out_kbps"] = _ts_list(timestamps, net_out)
    if disk_r is not None:
        ts["disk_read_iops"] = _ts_list(timestamps, disk_r)
    if disk_w is not None:
        ts["disk_write_iops"] = _ts_list(timestamps, disk_w)
    return ts


# ---------------------------------------------------------------------------
# Cost record builder
# ---------------------------------------------------------------------------
def _cost_record(
    resource_id: str,
    service: str,
    monthly_cost_usd: float,
    currency: str = "USD",
    fx_eur: float = 1.09,
) -> dict:
    total_usd = monthly_cost_usd / 30 * 15  # 15 days
    if currency == "EUR":
        total_cost = round(total_usd / fx_eur, 4)
    else:
        total_cost = round(total_usd, 4)

    return {
        "resource_id": resource_id,
        "service": service,
        "compartment_id": COMPARTMENT_ID,
        "sku_description": f"Compute - {service}",
        "currency": currency,
        "total_cost": total_cost,
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
    }


# ===========================================================================
# BUILD ALL INSTANCES
# ===========================================================================
instances: list[dict] = []
cost_records: list[dict] = []

TWO_PI = 2 * math.pi


# ---------------------------------------------------------------------------
# GROUP 1: STEADY (5 instances)
# ---------------------------------------------------------------------------
for i in range(1, 6):
    name = f"inst-steady-{i:02d}"
    n = N_FULL
    cpu = _normal(50, 3, n, 30, 70)
    mem = _normal(45, 4, n, 25, 65)
    net_in, net_out = _std_network(n)
    disk_r, disk_w = _std_disk(n)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem, net_in, net_out, disk_r, disk_w)
    inst = _make_instance(name, "VM.Standard.E4.Flex", 8, 64, "us-ashburn-1", ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 370.0))


# ---------------------------------------------------------------------------
# GROUP 2: BURSTY (5 instances)
# ---------------------------------------------------------------------------
for i in range(1, 6):
    name = f"inst-bursty-{i:02d}"
    n = N_FULL
    # 92% low, 8% spike
    mask = np.random.random(n) < 0.08
    cpu_low = _normal(12, 3, n, 2, 25)
    cpu_spike = _normal(88, 5, n, 75, 98)
    cpu = np.where(mask, cpu_spike, cpu_low)
    cpu = np.clip(cpu, 0.1, 99.9)
    mem = _normal(35, 5, n, 15, 60)
    net_in, net_out = _std_network(n)
    disk_r, disk_w = _std_disk(n)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem, net_in, net_out, disk_r, disk_w)
    inst = _make_instance(name, "VM.Standard.E4.Flex", 4, 32, "eu-frankfurt-1", ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 185.0))


# ---------------------------------------------------------------------------
# GROUP 3: CYCLICAL (3 instances)
# ---------------------------------------------------------------------------
h_arr = np.arange(N_FULL, dtype=float)
for i in range(1, 4):
    name = f"inst-cyclical-{i:02d}"
    cpu = np.clip(25 + 22 * np.sin(TWO_PI * h_arr / 24) + np.random.normal(0, 2, N_FULL), 1, 99)
    mem = np.clip(40 + 15 * np.sin(TWO_PI * h_arr / 24 + 0.3) + np.random.normal(0, 2, N_FULL), 1, 99)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem)
    # inst-cyclical-02 uses EUR currency
    currency = "EUR" if i == 2 else "USD"
    region = "eu-frankfurt-1" if i == 2 else "us-ashburn-1"
    inst = _make_instance(name, "VM.Standard3.Flex", 4, 32, region, ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 220.0, currency=currency))


# ---------------------------------------------------------------------------
# GROUP 4: WEEKLY (3 instances)
# ---------------------------------------------------------------------------
# Determine day-of-week and hour for each timestamp
# 2026-03-23 is a Monday (weekday 0)
_DT_START_WK = datetime(2026, 3, 23, 0, 0, 0, tzinfo=timezone.utc)
for i in range(1, 4):
    name = f"inst-weekly-{i:02d}"
    cpu = np.zeros(N_FULL)
    mem = np.zeros(N_FULL)
    for h in range(N_FULL):
        dt = _DT_START_WK + timedelta(hours=h)
        is_workday = dt.weekday() < 5  # Mon-Fri
        is_workhour = 9 <= dt.hour < 17
        if is_workday and is_workhour:
            cpu[h] = np.clip(np.random.normal(65, 8), 1, 95)
            mem[h] = np.clip(np.random.normal(55, 8), 1, 95)
        else:
            cpu[h] = np.clip(np.random.normal(15, 5), 1, 95)
            mem[h] = np.clip(np.random.normal(20, 5), 1, 95)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem)
    # inst-weekly-02 uses EUR currency
    currency = "EUR" if i == 2 else "USD"
    region = "eu-frankfurt-1" if i == 2 else "us-ashburn-1"
    inst = _make_instance(name, "VM.Standard.E4.Flex", 4, 32, region, ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 185.0, currency=currency))


# ---------------------------------------------------------------------------
# GROUP 5: TRENDING_UP (2 instances)
# ---------------------------------------------------------------------------
i_arr = np.arange(N_FULL, dtype=float)
for i in range(1, 3):
    name = f"inst-trending-{i:02d}"
    cpu = np.clip(20 + (i_arr / 359) * 35 + np.random.normal(0, 3, N_FULL), 0.1, 99.9)
    mem = np.clip(15 + (i_arr / 359) * 25 + np.random.normal(0, 3, N_FULL), 0.1, 99.9)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem)
    inst = _make_instance(name, "VM.Standard.E4.Flex", 4, 32, "us-ashburn-1", ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 185.0))


# ---------------------------------------------------------------------------
# GROUP 6: IDLE/ZOMBIE (3 instances)
# ---------------------------------------------------------------------------
for i in range(1, 4):
    name = f"inst-idle-{i:02d}"
    n = N_FULL
    cpu = _normal(1.5, 0.5, n, 0.1, 4.0)
    mem = _normal(5, 1, n, 2, 10)
    net_in = _normal(30, 10, n, 1, 80)
    net_out = _normal(15, 5, n, 1, 40)
    disk_r = _normal(2, 1, n, 0.1, 8)
    disk_w = _normal(1, 0.5, n, 0.1, 5)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem, net_in, net_out, disk_r, disk_w)
    inst = _make_instance(name, "VM.Standard.E4.Flex", 2, 16, "us-ashburn-1", ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 93.0))


# ---------------------------------------------------------------------------
# GROUP 7: INSUFFICIENT DATA (2 instances — only 48 hours)
# ---------------------------------------------------------------------------
for i in range(1, 3):
    name = f"inst-insuff-{i:02d}"
    n = N_INSUFF
    cpu = _normal(40, 5, n, 0.1, 99.9)
    mem = _normal(35, 5, n, 0.1, 99.9)
    ts = _build_timeseries(_TIMESTAMPS_INSUFF, cpu, mem)
    inst = _make_instance(name, "VM.Standard.E4.Flex", 4, 32, "us-ashburn-1", ts, _TIMESTAMPS_INSUFF)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 185.0))


# ---------------------------------------------------------------------------
# GROUP 8: GPU INSTANCES (2 instances)
# ---------------------------------------------------------------------------
gpu_configs = [
    ("inst-gpu-01", "VM.GPU.A10.1", 15, 240, 1836.68),
    ("inst-gpu-02", "VM.GPU.A10.2", 30, 480, 3673.36),
]
for name, shape, ocpu, ram_gb, monthly_cost in gpu_configs:
    n = N_FULL
    cpu = _normal(75, 8, n, 0.1, 99.9)
    mem = _normal(80, 5, n, 0.1, 99.9)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem)
    inst = _make_instance(name, shape, ocpu, ram_gb, "us-ashburn-1", ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", monthly_cost))


# ---------------------------------------------------------------------------
# GROUP 9: BARE METAL (1 instance)
# ---------------------------------------------------------------------------
name = "inst-bm-01"
n = N_FULL
cpu = _normal(60, 10, n, 0.1, 99.9)
mem = _normal(55, 8, n, 0.1, 99.9)
ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem)
inst = _make_instance(name, "BM.Standard.E4.128", 128, 2048, "us-ashburn-1", ts, _TIMESTAMPS_FULL)
instances.append(inst)
cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 2336.00))


# ---------------------------------------------------------------------------
# GROUP 10: NORMAL/WELL-PROVISIONED (6 instances)
# ---------------------------------------------------------------------------
for i in range(1, 7):
    name = f"inst-normal-{i:02d}"
    n = N_FULL
    cpu = _normal(55, 8, n, 0.1, 99.9)
    mem = _normal(60, 7, n, 0.1, 99.9)
    ts = _build_timeseries(_TIMESTAMPS_FULL, cpu, mem)
    inst = _make_instance(name, "VM.Standard.E4.Flex", 4, 32, "us-ashburn-1", ts, _TIMESTAMPS_FULL)
    instances.append(inst)
    cost_records.append(_cost_record(inst["ocid"], "COMPUTE", 185.0))


# ---------------------------------------------------------------------------
# ORPHANED COST RECORDS (2 records — no matching instance)
# ---------------------------------------------------------------------------
cost_records.append({
    "resource_id": "ocid1.instance.oc1.iad.orphaned-server-01",
    "service": "COMPUTE",
    "compartment_id": COMPARTMENT_ID,
    "sku_description": "Compute - COMPUTE",
    "currency": "USD",
    "total_cost": 45.20,
    "period_start": PERIOD_START,
    "period_end": PERIOD_END,
})
cost_records.append({
    "resource_id": "ocid1.volume.oc1.iad.orphaned-vol-99",
    "service": "BLOCK_STORAGE",
    "compartment_id": COMPARTMENT_ID,
    "sku_description": "Compute - BLOCK_STORAGE",
    "currency": "USD",
    "total_cost": 18.30,
    "period_start": PERIOD_START,
    "period_end": PERIOD_END,
})


# ===========================================================================
# BUILD VOLUMES
# ===========================================================================
volumes: list[dict] = []

# Helper: find instance ocid by name
def _ocid(name: str) -> str:
    for inst in instances:
        if inst["display_name"] == name:
            return inst["ocid"]
    raise KeyError(f"Instance not found: {name}")


# 4 attached volumes (for steady-01, bursty-01, cyclical-01, weekly-01)
attached_pairs = [
    ("inst-steady-01", "vol-steady-01-data"),
    ("inst-bursty-01", "vol-bursty-01-data"),
    ("inst-cyclical-01", "vol-cyclical-01-data"),
    ("inst-weekly-01", "vol-weekly-01-data"),
]
for inst_name, vol_suffix in attached_pairs:
    parent_ocid = _ocid(inst_name)
    vol_ocid = f"ocid1.volume.oc1.iad.{vol_suffix}"
    volumes.append({
        "ocid": vol_ocid,
        "display_name": vol_suffix,
        "size_gb": 500,
        "vpu_per_gb": 10,
        "lifecycle_state": "AVAILABLE",
        "compartment_id": COMPARTMENT_ID,
        "region": "us-ashburn-1",
        "attached_instance_id": parent_ocid,
        "read_throughput_avg": None,
        "write_throughput_avg": None,
        "read_iops_avg": None,
        "write_iops_avg": None,
        "collected_at": COLLECTED_AT,
    })
    cost_records.append({
        "resource_id": vol_ocid,
        "service": "BLOCK_STORAGE",
        "compartment_id": COMPARTMENT_ID,
        "sku_description": "Block Volume Storage",
        "currency": "USD",
        "total_cost": round(7.50 / 30 * 15, 4),
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
    })


# 1 stranded volume (no attachment, created > 7 days ago)
volumes.append({
    "ocid": "ocid1.volume.oc1.iad.stranded-vol-01",
    "display_name": "stranded-data-vol",
    "size_gb": 1000,
    "vpu_per_gb": 10,
    "lifecycle_state": "AVAILABLE",
    "compartment_id": COMPARTMENT_ID,
    "region": "us-ashburn-1",
    "attached_instance_id": None,
    "read_throughput_avg": None,
    "write_throughput_avg": None,
    "read_iops_avg": None,
    "write_iops_avg": None,
    "collected_at": COLLECTED_AT,
})
cost_records.append({
    "resource_id": "ocid1.volume.oc1.iad.stranded-vol-01",
    "service": "BLOCK_STORAGE",
    "compartment_id": COMPARTMENT_ID,
    "sku_description": "Block Volume Storage",
    "currency": "USD",
    "total_cost": 15.00,
    "period_start": PERIOD_START,
    "period_end": PERIOD_END,
})


# 3 more attached volumes for inst-bm-01, inst-gpu-01, inst-normal-01
extra_attached = [
    ("inst-bm-01", "vol-bm-01-data"),
    ("inst-gpu-01", "vol-gpu-01-data"),
    ("inst-normal-01", "vol-normal-01-data"),
]
for inst_name, vol_suffix in extra_attached:
    parent_ocid = _ocid(inst_name)
    vol_ocid = f"ocid1.volume.oc1.iad.{vol_suffix}"
    volumes.append({
        "ocid": vol_ocid,
        "display_name": vol_suffix,
        "size_gb": 1000,
        "vpu_per_gb": 20,
        "lifecycle_state": "AVAILABLE",
        "compartment_id": COMPARTMENT_ID,
        "region": "us-ashburn-1",
        "attached_instance_id": parent_ocid,
        "read_throughput_avg": None,
        "write_throughput_avg": None,
        "read_iops_avg": None,
        "write_iops_avg": None,
        "collected_at": COLLECTED_AT,
    })


# ===========================================================================
# ASSEMBLE FIXTURE
# ===========================================================================
fixture = {
    "period_start": PERIOD_START,
    "period_end": PERIOD_END,
    "regions": REGIONS,
    "compartments": [COMPARTMENT_ID],
    "dry_run": False,
    "collected_at": COLLECTED_AT,
    "fx_rates": FX_RATES,
    "instances": instances,
    "cost_records": cost_records,
    "volumes": volumes,
}

# Validate JSON round-trip
_json_str = json.dumps(fixture, indent=2)
json.loads(_json_str)  # will raise if invalid

# Write output
_out_dir = Path(__file__).parent
_out_path = _out_dir / "scenario_mixed_raw.json"
_out_path.write_text(_json_str, encoding="utf-8")

print(
    f"Fixture written: {_out_path} "
    f"({len(instances)} instances, {len(cost_records)} cost records, {len(volumes)} volumes)"
)
