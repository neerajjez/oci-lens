from __future__ import annotations

import statistics
import time
from datetime import datetime
from typing import Optional

import oci

from src.collector.oci_client import OciClientFactory, with_retry
from src.models.schemas import DiskMetrics, Instance, MetricStats, NetworkMetrics
from src.utils.date_utils import to_rfc3339
from src.utils.logger import get_logger

log = get_logger(__name__)


def _percentiles(values: list[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if not values:
        return None, None, None
    sorted_v = sorted(values)
    n = len(sorted_v)

    def pct(p: float) -> float:
        idx = int(p / 100 * n)
        return sorted_v[min(idx, n - 1)]

    return pct(50), pct(95), pct(99)


def _extract_aggregated_values(aggregations: list) -> list[float]:
    values: list[float] = []
    for agg in aggregations:
        for dp in (agg.aggregated_datapoints or []):
            if dp.value is not None:
                values.append(dp.value)
    return values


@with_retry
def _list_instances_page(client: oci.core.ComputeClient, compartment_id: str, page: Optional[str]) -> oci.response.Response:
    kwargs: dict = {"compartment_id": compartment_id, "limit": 100}
    if page:
        kwargs["page"] = page
    return client.list_instances(**kwargs)


def list_all_instances(client: oci.core.ComputeClient, compartment_id: str) -> list[oci.core.models.Instance]:
    instances: list = []
    page: Optional[str] = None
    while True:
        resp = _list_instances_page(client, compartment_id, page)
        instances.extend(resp.data)
        page = resp.next_page
        if not page:
            break
    log.info("instances_listed", compartment=compartment_id, count=len(instances))
    return instances


@with_retry
def _query_metric(
    mon_client: oci.monitoring.MonitoringClient,
    compartment_id: str,
    namespace: str,
    query: str,
    start: datetime,
    end: datetime,
    resolution: str,
) -> list:
    t0 = time.monotonic()
    details = oci.monitoring.models.SummarizeMetricsDataDetails(
        namespace=namespace,
        query=query,
        start_time=to_rfc3339(start),
        end_time=to_rfc3339(end),
        resolution=resolution,
    )
    resp = mon_client.summarize_metrics_data(
        compartment_id=compartment_id,
        summarize_metrics_data_details=details,
    )
    data = resp.data or []
    log.debug("metric_query_done", query=query[:60], points=sum(len(a.aggregated_datapoints or []) for a in data), elapsed_s=round(time.monotonic() - t0, 2))
    return data


def _collect_cpu(
    mon_client: oci.monitoring.MonitoringClient,
    compartment_id: str,
    instance_id: str,
    start: datetime,
    end: datetime,
    resolution: str,
) -> MetricStats:
    t0 = time.monotonic()
    log.info("metric_start", metric="cpu", instance=instance_id[-12:])
    query = f'CpuUtilization[{resolution}]{{resourceId="{instance_id}"}}.mean()'
    try:
        aggs = _query_metric(mon_client, compartment_id, "oci_computeagent", query, start, end, resolution)
        values = _extract_aggregated_values(aggs)
        if not values:
            log.info("metric_done", metric="cpu", instance=instance_id[-12:], points=0, elapsed_s=round(time.monotonic()-t0,2))
            return MetricStats()
        p50, p95, p99 = _percentiles(values)
        log.info("metric_done", metric="cpu", instance=instance_id[-12:], points=len(values), avg=round(statistics.mean(values),1), elapsed_s=round(time.monotonic()-t0,2))
        return MetricStats(avg=statistics.mean(values), p50=p50, p95=p95, p99=p99, peak=max(values))
    except Exception as exc:
        log.warning("metric_failed", metric="cpu", instance=instance_id[-12:], error=str(exc), elapsed_s=round(time.monotonic()-t0,2))
        return MetricStats()


def _collect_memory(
    mon_client: oci.monitoring.MonitoringClient,
    compartment_id: str,
    instance_id: str,
    start: datetime,
    end: datetime,
    resolution: str,
) -> MetricStats:
    t0 = time.monotonic()
    log.info("metric_start", metric="memory", instance=instance_id[-12:])
    query = f'MemoryUtilization[{resolution}]{{resourceId="{instance_id}"}}.mean()'
    try:
        aggs = _query_metric(mon_client, compartment_id, "oci_computeagent", query, start, end, resolution)
        values = _extract_aggregated_values(aggs)
        if not values:
            log.info("metric_done", metric="memory", instance=instance_id[-12:], points=0, elapsed_s=round(time.monotonic()-t0,2))
            return MetricStats()
        p50, p95, p99 = _percentiles(values)
        log.info("metric_done", metric="memory", instance=instance_id[-12:], points=len(values), avg=round(statistics.mean(values),1), elapsed_s=round(time.monotonic()-t0,2))
        return MetricStats(avg=statistics.mean(values), p50=p50, p95=p95, p99=p99, peak=max(values))
    except Exception as exc:
        log.warning("metric_failed", metric="memory", instance=instance_id[-12:], error=str(exc), elapsed_s=round(time.monotonic()-t0,2))
        return MetricStats()


def _collect_network(
    mon_client: oci.monitoring.MonitoringClient,
    compartment_id: str,
    instance_id: str,
    start: datetime,
    end: datetime,
    resolution: str,
) -> NetworkMetrics:
    t0 = time.monotonic()
    log.info("metric_start", metric="network(in+out)", instance=instance_id[-12:])

    def _query_values(direction: str) -> list[float]:
        q = f'NetworksBytesIn[{resolution}]{{resourceId="{instance_id}"}}.mean()' if direction == "in" \
            else f'NetworksBytesOut[{resolution}]{{resourceId="{instance_id}"}}.mean()'
        try:
            aggs = _query_metric(mon_client, compartment_id, "oci_computeagent", q, start, end, resolution)
            return _extract_aggregated_values(aggs)
        except Exception as exc:
            log.warning("metric_failed", metric=f"network_{direction}", instance=instance_id[-12:], error=str(exc))
            return []

    in_vals = _query_values("in")
    out_vals = _query_values("out")
    log.info("metric_done", metric="network(in+out)", instance=instance_id[-12:], in_pts=len(in_vals), out_pts=len(out_vals), elapsed_s=round(time.monotonic()-t0,2))
    return NetworkMetrics(
        bytes_in_avg=statistics.mean(in_vals) if in_vals else None,
        bytes_out_avg=statistics.mean(out_vals) if out_vals else None,
        bytes_in_peak=max(in_vals) if in_vals else None,
        bytes_out_peak=max(out_vals) if out_vals else None,
    )


def _collect_disk(
    mon_client: oci.monitoring.MonitoringClient,
    compartment_id: str,
    instance_id: str,
    start: datetime,
    end: datetime,
    resolution: str,
) -> DiskMetrics:
    t0 = time.monotonic()
    log.info("metric_start", metric="disk(4 queries)", instance=instance_id[-12:])

    def _query_values(metric_name: str) -> list[float]:
        q = f'{metric_name}[{resolution}]{{resourceId="{instance_id}"}}.mean()'
        try:
            aggs = _query_metric(mon_client, compartment_id, "oci_blockstore", q, start, end, resolution)
            return _extract_aggregated_values(aggs)
        except Exception as exc:
            log.warning("metric_failed", metric=metric_name, instance=instance_id[-12:], error=str(exc))
            return []

    rd_ops = _query_values("DiskReadOps")
    wr_ops = _query_values("DiskWriteOps")
    rd_bytes = _query_values("DiskReadBytes")
    wr_bytes = _query_values("DiskWriteBytes")
    log.info("metric_done", metric="disk(4 queries)", instance=instance_id[-12:], elapsed_s=round(time.monotonic()-t0,2))
    return DiskMetrics(
        read_ops_avg=statistics.mean(rd_ops) if rd_ops else None,
        write_ops_avg=statistics.mean(wr_ops) if wr_ops else None,
        read_bytes_avg=statistics.mean(rd_bytes) if rd_bytes else None,
        write_bytes_avg=statistics.mean(wr_bytes) if wr_bytes else None,
    )


def collect_instances(
    factory: OciClientFactory,
    compartment_id: str,
    region: str,
    start: datetime,
    end: datetime,
    metrics_interval_minutes: int,
    dry_run: bool = False,
) -> list[Instance]:
    resolution = f"{metrics_interval_minutes}m"
    compute_client = factory.compute(region)
    mon_client = factory.monitoring(region)

    raw_instances = list_all_instances(compute_client, compartment_id)
    total = len(raw_instances)
    results: list[Instance] = []
    phase_t0 = time.monotonic()

    for idx, raw in enumerate(raw_instances, start=1):
        inst_t0 = time.monotonic()
        log.info("instance_start", progress=f"{idx}/{total}", name=raw.display_name,
                 shape=raw.shape, state=raw.lifecycle_state, id_suffix=raw.id[-12:])

        sc = raw.shape_config
        _ocpus         = getattr(sc, "ocpus", None)         if sc else None
        _memory_in_gbs = getattr(sc, "memory_in_gbs", None) if sc else None
        _vcpus         = getattr(sc, "vcpus", None)          if sc else None

        if dry_run:
            inst = Instance(
                ocid=raw.id,
                display_name=raw.display_name,
                shape=raw.shape,
                region=region,
                compartment_id=compartment_id,
                lifecycle_state=raw.lifecycle_state,
                time_created=raw.time_created,
                ocpus=_ocpus,
                memory_in_gbs=_memory_in_gbs,
                vcpus=_vcpus,
            )
        else:
            inst = Instance(
                ocid=raw.id,
                display_name=raw.display_name,
                shape=raw.shape,
                region=region,
                compartment_id=compartment_id,
                lifecycle_state=raw.lifecycle_state,
                time_created=raw.time_created,
                ocpus=_ocpus,
                memory_in_gbs=_memory_in_gbs,
                vcpus=_vcpus,
                cpu=_collect_cpu(mon_client, compartment_id, raw.id, start, end, resolution),
                memory=_collect_memory(mon_client, compartment_id, raw.id, start, end, resolution),
                network=_collect_network(mon_client, compartment_id, raw.id, start, end, resolution),
                disk=_collect_disk(mon_client, compartment_id, raw.id, start, end, resolution),
            )
        results.append(inst)
        log.info("instance_done", progress=f"{idx}/{total}", name=raw.display_name,
                 elapsed_s=round(time.monotonic()-inst_t0, 2))

    total_elapsed = round(time.monotonic() - phase_t0, 1)
    log.info("instances_collected", region=region, compartment=compartment_id,
             count=len(results), total_elapsed_s=total_elapsed,
             avg_per_instance_s=round(total_elapsed/total, 1) if total else 0)
    return results
