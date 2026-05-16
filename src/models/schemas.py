from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MetricStats:
    avg: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None
    peak: Optional[float] = None


@dataclass
class NetworkMetrics:
    bytes_in_avg: Optional[float] = None
    bytes_out_avg: Optional[float] = None
    bytes_in_peak: Optional[float] = None
    bytes_out_peak: Optional[float] = None


@dataclass
class DiskMetrics:
    read_ops_avg: Optional[float] = None
    write_ops_avg: Optional[float] = None
    read_bytes_avg: Optional[float] = None
    write_bytes_avg: Optional[float] = None


@dataclass
class Instance:
    ocid: str
    display_name: str
    shape: str
    region: str
    compartment_id: str
    lifecycle_state: str
    time_created: Optional[datetime] = None
    ocpus: Optional[float] = None
    memory_in_gbs: Optional[float] = None
    vcpus: Optional[int] = None
    cpu: MetricStats = field(default_factory=MetricStats)
    memory: MetricStats = field(default_factory=MetricStats)
    network: NetworkMetrics = field(default_factory=NetworkMetrics)
    disk: DiskMetrics = field(default_factory=DiskMetrics)
    cost: Optional[CostRecord] = None
    collected_at: datetime = field(default_factory=_utcnow)


@dataclass
class CostRecord:
    resource_id: str
    service: str
    compartment_id: str
    sku_description: str
    currency: str
    total_cost: float
    period_start: datetime
    period_end: datetime


@dataclass
class BlockVolume:
    ocid: str
    display_name: str
    size_gb: int
    vpu_per_gb: int
    lifecycle_state: str
    compartment_id: str
    region: str
    attached_instance_id: Optional[str] = None
    read_throughput_avg: Optional[float] = None
    write_throughput_avg: Optional[float] = None
    read_iops_avg: Optional[float] = None
    write_iops_avg: Optional[float] = None
    collected_at: datetime = field(default_factory=_utcnow)


@dataclass
class BootVolume:
    ocid: str
    display_name: str
    size_gb: int
    vpu_per_gb: int
    lifecycle_state: str
    compartment_id: str
    region: str
    attached_instance_id: Optional[str] = None
    collected_at: datetime = field(default_factory=_utcnow)


@dataclass
class ObjectStorageBucket:
    name: str
    namespace: str
    compartment_id: str
    storage_tier: str
    approximate_count: Optional[int] = None
    approximate_size_gb: Optional[float] = None
    collected_at: datetime = field(default_factory=_utcnow)


@dataclass
class CollectionResult:
    period_start: datetime
    period_end: datetime
    regions: list[str]
    compartments: list[str]
    instances: list[Instance] = field(default_factory=list)
    volumes: list[BlockVolume] = field(default_factory=list)
    boot_volumes: list[BootVolume] = field(default_factory=list)
    object_storage_buckets: list[ObjectStorageBucket] = field(default_factory=list)
    cost_records: list[CostRecord] = field(default_factory=list)
    collected_at: datetime = field(default_factory=_utcnow)
    dry_run: bool = False
    tenancy_name: str = ""
    compartment_name: str = ""
