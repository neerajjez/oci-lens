"""
src/reporter/resource_report/data.py
=====================================
Data model and raw-JSON loader for the resource-utilization-only report.
No cost data. No business recommendations. Pure metrics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Sizing labels — plain language, no "TERMINATE" / "DOWNSIZE"
# ---------------------------------------------------------------------------
SIZING_IDLE    = "Idle"
SIZING_OVER    = "Over-provisioned"
SIZING_RIGHT   = "Right-sized"
SIZING_UNDER   = "Under-provisioned"
SIZING_NO_DATA = "No Data"
SIZING_STOPPED = "Stopped"

SIZING_COLOR = {
    SIZING_IDLE:    "#7B1FA2",
    SIZING_OVER:    "#EF6C00",
    SIZING_RIGHT:   "#2E7D32",
    SIZING_UNDER:   "#C62828",
    SIZING_NO_DATA: "#9A9A9A",
    SIZING_STOPPED: "#9A9A9A",
}

SIZING_BG = {
    SIZING_IDLE:    "#F3E5F5",
    SIZING_OVER:    "#FFF3E0",
    SIZING_RIGHT:   "#E8F5E9",
    SIZING_UNDER:   "#FFEBEE",
    SIZING_NO_DATA: "#F5F5F5",
    SIZING_STOPPED: "#F5F5F5",
}


def sizing_label(
    lifecycle_state: str,
    cpu_p95: Optional[float],
    mem_p95: Optional[float],
) -> str:
    if lifecycle_state.upper() != "RUNNING":
        return SIZING_STOPPED
    if cpu_p95 is None:
        return SIZING_NO_DATA
    if cpu_p95 < 2.0:
        return SIZING_IDLE
    if cpu_p95 < 20.0:
        if mem_p95 is not None and mem_p95 >= 40.0:
            return SIZING_RIGHT
        return SIZING_OVER
    if cpu_p95 <= 80.0:
        return SIZING_RIGHT
    return SIZING_UNDER


@dataclass
class InstanceStats:
    name: str
    shape: str
    region: str
    lifecycle_state: str
    time_created: Optional[str]

    # Provisioned capacity (from OCI shape config)
    ocpus: Optional[float] = None
    memory_in_gbs: Optional[float] = None
    vcpus: Optional[int] = None

    cpu_avg:  Optional[float] = None
    cpu_p50:  Optional[float] = None
    cpu_p95:  Optional[float] = None
    cpu_p99:  Optional[float] = None
    cpu_peak: Optional[float] = None

    mem_avg:  Optional[float] = None
    mem_p50:  Optional[float] = None
    mem_p95:  Optional[float] = None
    mem_p99:  Optional[float] = None
    mem_peak: Optional[float] = None

    net_in_avg_bytes:   Optional[float] = None
    net_out_avg_bytes:  Optional[float] = None
    net_in_peak_bytes:  Optional[float] = None
    net_out_peak_bytes: Optional[float] = None

    disk_read_ops_avg:  Optional[float] = None
    disk_write_ops_avg: Optional[float] = None
    disk_read_mb_avg:   Optional[float] = None
    disk_write_mb_avg:  Optional[float] = None

    @property
    def sizing(self) -> str:
        return sizing_label(self.lifecycle_state, self.cpu_p95, self.mem_p95)

    @property
    def net_in_avg_mb(self) -> Optional[float]:
        return (self.net_in_avg_bytes / 1_048_576) if self.net_in_avg_bytes is not None else None

    @property
    def net_out_avg_mb(self) -> Optional[float]:
        return (self.net_out_avg_bytes / 1_048_576) if self.net_out_avg_bytes is not None else None

    @property
    def net_in_peak_mb(self) -> Optional[float]:
        return (self.net_in_peak_bytes / 1_048_576) if self.net_in_peak_bytes is not None else None

    @property
    def net_out_peak_mb(self) -> Optional[float]:
        return (self.net_out_peak_bytes / 1_048_576) if self.net_out_peak_bytes is not None else None


@dataclass
class BootVolumeStats:
    name: str
    size_gb: int
    vpu_per_gb: int
    lifecycle_state: str
    attached_instance: Optional[str] = None


@dataclass
class BlockVolumeStats:
    name: str
    size_gb: int
    vpu_per_gb: int
    lifecycle_state: str
    attached_instances: list[str] = field(default_factory=list)
    read_iops_avg: Optional[float] = None
    write_iops_avg: Optional[float] = None


@dataclass
class ObjectStorageStats:
    name: str
    storage_tier: str
    approximate_count: Optional[int] = None
    approximate_size_gb: Optional[float] = None


@dataclass
class FleetStats:
    period_start: str
    period_end: str
    collection_days: int
    tenancy_name: str = ""
    compartment_name: str = ""
    instances: list[InstanceStats] = field(default_factory=list)
    boot_volumes: list[BootVolumeStats] = field(default_factory=list)
    block_volumes: list[BlockVolumeStats] = field(default_factory=list)
    object_storage: list[ObjectStorageStats] = field(default_factory=list)

    @property
    def running(self) -> list[InstanceStats]:
        return [i for i in self.instances if i.lifecycle_state.upper() == "RUNNING"]

    @property
    def stopped(self) -> list[InstanceStats]:
        return [i for i in self.instances if i.lifecycle_state.upper() != "RUNNING"]

    @property
    def sizing_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for inst in self.instances:
            counts[inst.sizing] = counts.get(inst.sizing, 0) + 1
        return counts

    def fleet_cpu_p95_avg(self) -> Optional[float]:
        vals = [i.cpu_p95 for i in self.running if i.cpu_p95 is not None]
        return sum(vals) / len(vals) if vals else None

    def fleet_mem_p95_avg(self) -> Optional[float]:
        vals = [i.mem_p95 for i in self.running if i.mem_p95 is not None]
        return sum(vals) / len(vals) if vals else None


def _f(val: object) -> Optional[float]:
    try:
        v = float(val)  # type: ignore[arg-type]
        return v if v == v else None  # drop NaN
    except (TypeError, ValueError):
        return None


def load_raw_for_resource_report(raw_path: Path) -> FleetStats:
    """Read a *_raw.json and return FleetStats — no analytics engine involved."""
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    period_start = str(raw.get("period_start", ""))[:10]
    period_end   = str(raw.get("period_end",   ""))[:10]

    try:
        from datetime import date
        d1 = date.fromisoformat(period_start)
        d2 = date.fromisoformat(period_end)
        collection_days = max(1, (d2 - d1).days)
    except Exception:
        collection_days = 1

    # Build OCID → display_name map for resolving attachment IDs to readable names
    ocid_to_name: dict[str, str] = {}
    for ri in raw.get("instances", []):
        ocid = ri.get("ocid", "")
        name = ri.get("display_name", ocid[-12:] if ocid else "unknown")
        if ocid:
            ocid_to_name[ocid] = name

    # --- Instances ---
    instances: list[InstanceStats] = []
    for ri in raw.get("instances", []):
        cpu  = ri.get("cpu")    or {}
        mem  = ri.get("memory") or {}
        net  = ri.get("network") or {}
        disk = ri.get("disk")   or {}

        read_bytes  = _f(disk.get("read_bytes_avg"))
        write_bytes = _f(disk.get("write_bytes_avg"))

        inst = InstanceStats(
            name            = ri.get("display_name", "unknown"),
            shape           = ri.get("shape", ""),
            region          = ri.get("region", ""),
            lifecycle_state = ri.get("lifecycle_state", "UNKNOWN"),
            time_created    = str(ri.get("time_created", ""))[:10] or None,

            ocpus         = _f(ri.get("ocpus")),
            memory_in_gbs = _f(ri.get("memory_in_gbs")),
            vcpus         = int(ri["vcpus"]) if ri.get("vcpus") is not None else None,

            cpu_avg  = _f(cpu.get("avg")),
            cpu_p50  = _f(cpu.get("p50")),
            cpu_p95  = _f(cpu.get("p95")),
            cpu_p99  = _f(cpu.get("p99")),
            cpu_peak = _f(cpu.get("peak")),

            mem_avg  = _f(mem.get("avg")),
            mem_p50  = _f(mem.get("p50")),
            mem_p95  = _f(mem.get("p95")),
            mem_p99  = _f(mem.get("p99")),
            mem_peak = _f(mem.get("peak")),

            net_in_avg_bytes   = _f(net.get("bytes_in_avg")),
            net_out_avg_bytes  = _f(net.get("bytes_out_avg")),
            net_in_peak_bytes  = _f(net.get("bytes_in_peak")),
            net_out_peak_bytes = _f(net.get("bytes_out_peak")),

            disk_read_ops_avg  = _f(disk.get("read_ops_avg")),
            disk_write_ops_avg = _f(disk.get("write_ops_avg")),
            disk_read_mb_avg   = (read_bytes / 1_048_576)  if read_bytes  else None,
            disk_write_mb_avg  = (write_bytes / 1_048_576) if write_bytes else None,
        )
        instances.append(inst)

    instances.sort(key=lambda i: (
        0 if i.lifecycle_state.upper() == "RUNNING" else 1,
        -(i.cpu_p95 or 0.0),
    ))

    # --- Boot volumes ---
    boot_volumes: list[BootVolumeStats] = []
    for bv in raw.get("boot_volumes", []):
        att_ocid = bv.get("attached_instance_id")
        att_name: Optional[str] = None
        if att_ocid:
            att_name = ocid_to_name.get(att_ocid, att_ocid[-12:])
        boot_volumes.append(BootVolumeStats(
            name              = bv.get("display_name", "—"),
            size_gb           = int(bv.get("size_gb") or 0),
            vpu_per_gb        = int(bv.get("vpu_per_gb") or 10),
            lifecycle_state   = bv.get("lifecycle_state", "UNKNOWN"),
            attached_instance = att_name,
        ))
    boot_volumes.sort(key=lambda b: b.name)

    # --- Block volumes — group by OCID to handle multi-attach ---
    bv_map: dict[str, BlockVolumeStats] = {}
    for vol in raw.get("volumes", []):
        ocid = vol.get("ocid", "")
        if ocid not in bv_map:
            bv_map[ocid] = BlockVolumeStats(
                name           = vol.get("display_name", "—"),
                size_gb        = int(vol.get("size_gb") or 0),
                vpu_per_gb     = int(vol.get("vpu_per_gb") or 10),
                lifecycle_state = vol.get("lifecycle_state", "UNKNOWN"),
                read_iops_avg  = _f(vol.get("read_iops_avg")),
                write_iops_avg = _f(vol.get("write_iops_avg")),
            )
        att_ocid = vol.get("attached_instance_id")
        if att_ocid:
            friendly = ocid_to_name.get(att_ocid, att_ocid[-12:])
            if friendly not in bv_map[ocid].attached_instances:
                bv_map[ocid].attached_instances.append(friendly)

    block_volumes = sorted(bv_map.values(), key=lambda v: v.name)

    # --- Object storage ---
    object_storage: list[ObjectStorageStats] = []
    for bucket in raw.get("object_storage_buckets", []):
        object_storage.append(ObjectStorageStats(
            name                = bucket.get("name", "—"),
            storage_tier        = bucket.get("storage_tier", "Standard"),
            approximate_count   = bucket.get("approximate_count"),
            approximate_size_gb = _f(bucket.get("approximate_size_gb")),
        ))
    object_storage.sort(key=lambda b: b.name)

    return FleetStats(
        period_start=period_start,
        period_end=period_end,
        collection_days=collection_days,
        tenancy_name=raw.get("tenancy_name", ""),
        compartment_name=raw.get("compartment_name", ""),
        instances=instances,
        boot_volumes=boot_volumes,
        block_volumes=block_volumes,
        object_storage=object_storage,
    )
