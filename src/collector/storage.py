from __future__ import annotations

import statistics
from datetime import datetime
from typing import Optional

import oci

from src.collector.oci_client import OciClientFactory, with_retry
from src.collector.compute import _query_metric, _extract_aggregated_values
from src.models.schemas import BlockVolume, BootVolume, ObjectStorageBucket
from src.utils.logger import get_logger

log = get_logger(__name__)


@with_retry
def _list_volumes_page(
    client: oci.core.BlockstorageClient,
    compartment_id: str,
    page: Optional[str],
) -> oci.response.Response:
    kwargs: dict = {"compartment_id": compartment_id, "limit": 100}
    if page:
        kwargs["page"] = page
    return client.list_volumes(**kwargs)


@with_retry
def _list_attachments_page(
    client: oci.core.ComputeClient,
    compartment_id: str,
    page: Optional[str],
) -> oci.response.Response:
    kwargs: dict = {"compartment_id": compartment_id, "limit": 100}
    if page:
        kwargs["page"] = page
    return client.list_volume_attachments(**kwargs)


def _build_attachment_map(
    compute_client: oci.core.ComputeClient,
    compartment_id: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    page: Optional[str] = None
    while True:
        resp = _list_attachments_page(compute_client, compartment_id, page)
        for att in resp.data:
            if att.lifecycle_state == "ATTACHED":
                mapping[att.volume_id] = att.instance_id
        page = resp.next_page
        if not page:
            break
    return mapping


def _collect_volume_metrics(
    mon_client: oci.monitoring.MonitoringClient,
    compartment_id: str,
    volume_id: str,
    start: datetime,
    end: datetime,
    resolution: str,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    def _avg(metric_name: str) -> Optional[float]:
        q = f'{metric_name}[{resolution}]{{resourceId="{volume_id}"}}.mean()'
        try:
            aggs = _query_metric(mon_client, compartment_id, "oci_blockstore", q, start, end, resolution)
            vals = _extract_aggregated_values(aggs)
            return statistics.mean(vals) if vals else None
        except Exception as exc:
            log.warning("volume_metric_failed", metric=metric_name, volume=volume_id, error=str(exc))
            return None

    return (
        _avg("VolumeReadThroughput"),
        _avg("VolumeWriteThroughput"),
        _avg("VolumeReadOps"),
        _avg("VolumeWriteOps"),
    )


def collect_volumes(
    factory: OciClientFactory,
    compartment_id: str,
    region: str,
    start: datetime,
    end: datetime,
    metrics_interval_minutes: int,
    dry_run: bool = False,
) -> list[BlockVolume]:
    resolution = f"{metrics_interval_minutes}m"
    bs_client = factory.blockstorage(region)
    compute_client = factory.compute(region)
    mon_client = factory.monitoring(region)

    attachment_map = _build_attachment_map(compute_client, compartment_id)

    raw_volumes: list = []
    page: Optional[str] = None
    while True:
        resp = _list_volumes_page(bs_client, compartment_id, page)
        raw_volumes.extend(resp.data)
        page = resp.next_page
        if not page:
            break

    log.info("volumes_listed", compartment=compartment_id, count=len(raw_volumes))

    results: list[BlockVolume] = []
    for vol in raw_volumes:
        if dry_run:
            bv = BlockVolume(
                ocid=vol.id,
                display_name=vol.display_name,
                size_gb=vol.size_in_gbs,
                vpu_per_gb=vol.vpus_per_gb or 10,
                lifecycle_state=vol.lifecycle_state,
                compartment_id=compartment_id,
                region=region,
                attached_instance_id=attachment_map.get(vol.id),
            )
        else:
            r_tp, w_tp, r_iops, w_iops = _collect_volume_metrics(
                mon_client, compartment_id, vol.id, start, end, resolution
            )
            bv = BlockVolume(
                ocid=vol.id,
                display_name=vol.display_name,
                size_gb=vol.size_in_gbs,
                vpu_per_gb=vol.vpus_per_gb or 10,
                lifecycle_state=vol.lifecycle_state,
                compartment_id=compartment_id,
                region=region,
                attached_instance_id=attachment_map.get(vol.id),
                read_throughput_avg=r_tp,
                write_throughput_avg=w_tp,
                read_iops_avg=r_iops,
                write_iops_avg=w_iops,
            )
        results.append(bv)

    log.info("volumes_collected", region=region, compartment=compartment_id, count=len(results))
    return results


# ---------------------------------------------------------------------------
# Boot volumes
# ---------------------------------------------------------------------------

@with_retry
def _list_boot_volumes_page(
    client: oci.core.BlockstorageClient,
    compartment_id: str,
    availability_domain: str,
    page: Optional[str],
) -> oci.response.Response:
    kwargs: dict = {"compartment_id": compartment_id,
                    "availability_domain": availability_domain, "limit": 100}
    if page:
        kwargs["page"] = page
    return client.list_boot_volumes(**kwargs)


@with_retry
def _list_boot_attachments_page(
    client: oci.core.ComputeClient,
    compartment_id: str,
    availability_domain: str,
    page: Optional[str],
) -> oci.response.Response:
    kwargs: dict = {"compartment_id": compartment_id,
                    "availability_domain": availability_domain, "limit": 100}
    if page:
        kwargs["page"] = page
    return client.list_boot_volume_attachments(**kwargs)


def _build_boot_attachment_map(
    compute_client: oci.core.ComputeClient,
    compartment_id: str,
    availability_domain: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    page: Optional[str] = None
    while True:
        resp = _list_boot_attachments_page(compute_client, compartment_id, availability_domain, page)
        for att in resp.data:
            if att.lifecycle_state == "ATTACHED":
                mapping[att.boot_volume_id] = att.instance_id
        page = resp.next_page
        if not page:
            break
    return mapping


def collect_boot_volumes(
    factory: OciClientFactory,
    compartment_id: str,
    region: str,
    dry_run: bool = False,
) -> list[BootVolume]:
    bs_client      = factory.blockstorage(region)
    compute_client = factory.compute(region)

    # Boot volumes require an availability domain — list ADs first
    identity_client = oci.identity.IdentityClient(factory._config)
    tenancy_id = factory._config.get("tenancy")
    try:
        ads = identity_client.list_availability_domains(compartment_id=tenancy_id).data
    except Exception:
        ads = identity_client.list_availability_domains(compartment_id=compartment_id).data

    results: list[BootVolume] = []
    for ad in ads:
        try:
            boot_attachment_map = _build_boot_attachment_map(compute_client, compartment_id, ad.name)
        except Exception as exc:
            log.warning("boot_attachment_map_error", ad=ad.name, error=str(exc))
            boot_attachment_map = {}

        raw_vols: list = []
        page: Optional[str] = None
        while True:
            try:
                resp = _list_boot_volumes_page(bs_client, compartment_id, ad.name, page)
            except Exception as exc:
                log.warning("boot_volumes_list_error", ad=ad.name, error=str(exc))
                break
            raw_vols.extend(resp.data)
            page = resp.next_page
            if not page:
                break

        for vol in raw_vols:
            results.append(BootVolume(
                ocid=vol.id,
                display_name=vol.display_name,
                size_gb=vol.size_in_gbs,
                vpu_per_gb=getattr(vol, "vpus_per_gb", 10) or 10,
                lifecycle_state=vol.lifecycle_state,
                compartment_id=compartment_id,
                region=region,
                attached_instance_id=boot_attachment_map.get(vol.id),
            ))

    log.info("boot_volumes_collected", region=region, compartment=compartment_id,
             count=len(results))
    return results


# ---------------------------------------------------------------------------
# Object Storage (OCI equivalent of S3)
# ---------------------------------------------------------------------------

def collect_object_storage(
    factory: OciClientFactory,
    compartment_id: str,
    region: str,
    dry_run: bool = False,
) -> list[ObjectStorageBucket]:
    os_client = factory.object_storage(region)

    try:
        namespace = os_client.get_namespace().data
    except Exception as exc:
        log.error("object_storage_namespace_failed", error=str(exc))
        return []

    # List all buckets in this compartment
    raw_buckets: list = []
    page: Optional[str] = None
    while True:
        try:
            resp = os_client.list_buckets(
                namespace_name=namespace,
                compartment_id=compartment_id,
                limit=100,
                page=page if page else None,
            )
        except Exception as exc:
            log.error("object_storage_list_failed", error=str(exc))
            break
        raw_buckets.extend(resp.data)
        page = resp.next_page
        if not page:
            break

    results: list[ObjectStorageBucket] = []
    for b in raw_buckets:
        # BucketSummary from list_buckets() never carries size/count — fetch detail per bucket
        approx_size_gb = None
        approx_count = None
        try:
            detail = os_client.get_bucket(
                namespace_name=namespace,
                bucket_name=b.name,
                fields=["approximateCount", "approximateSize"],
            ).data
            approx_size_bytes = getattr(detail, "approximate_size", None)
            approx_size_gb = (approx_size_bytes / 1_073_741_824) if approx_size_bytes else None
            approx_count = getattr(detail, "approximate_count", None)
        except Exception as exc:
            log.warning("bucket_detail_failed", bucket=b.name, error=str(exc))

        results.append(ObjectStorageBucket(
            name=b.name,
            namespace=namespace,
            compartment_id=compartment_id,
            storage_tier=getattr(b, "storage_tier", "Standard") or "Standard",
            approximate_count=approx_count,
            approximate_size_gb=approx_size_gb,
        ))

    log.info("object_storage_collected", region=region, compartment=compartment_id,
             count=len(results))
    return results
