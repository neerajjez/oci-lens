"""Tests for src/collector/storage.py."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.collector.storage import (
    _build_attachment_map,
    _collect_volume_metrics,
    collect_volumes,
)
from src.models.schemas import BlockVolume


_NOW = datetime(2024, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_COMPARTMENT = "ocid1.compartment.oc1..aaa"
_REGION = "us-ashburn-1"


def _vol(vol_id: str = "ocid1.volume.oc1..v1", name: str = "vol-1",
         size_gb: int = 50, vpu: int = 10, state: str = "AVAILABLE") -> MagicMock:
    v = MagicMock()
    v.id = vol_id
    v.display_name = name
    v.size_in_gbs = size_gb
    v.vpus_per_gb = vpu
    v.lifecycle_state = state
    return v


def _resp(data_list, next_page=None):
    r = MagicMock()
    r.data = data_list
    r.next_page = next_page
    return r


def _factory(bs_client=None, compute_client=None, mon_client=None):
    f = MagicMock()
    f.blockstorage.return_value = bs_client or MagicMock()
    f.compute.return_value = compute_client or MagicMock()
    f.monitoring.return_value = mon_client or MagicMock()
    return f


# ── _build_attachment_map ─────────────────────────────────────────────────────

def test_build_attachment_map_single_page():
    att = MagicMock()
    att.lifecycle_state = "ATTACHED"
    att.volume_id = "ocid1.volume.oc1..v1"
    att.instance_id = "ocid1.instance.oc1..i1"
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([att])
    result = _build_attachment_map(compute_client, _COMPARTMENT)
    assert result["ocid1.volume.oc1..v1"] == "ocid1.instance.oc1..i1"


def test_build_attachment_map_skips_detached():
    att = MagicMock()
    att.lifecycle_state = "DETACHED"
    att.volume_id = "ocid1.volume.oc1..v2"
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([att])
    result = _build_attachment_map(compute_client, _COMPARTMENT)
    assert "ocid1.volume.oc1..v2" not in result


def test_build_attachment_map_multi_page():
    att1, att2 = MagicMock(), MagicMock()
    att1.lifecycle_state = "ATTACHED"
    att1.volume_id = "ocid1.volume.oc1..v1"
    att1.instance_id = "ocid1.instance.oc1..i1"
    att2.lifecycle_state = "ATTACHED"
    att2.volume_id = "ocid1.volume.oc1..v2"
    att2.instance_id = "ocid1.instance.oc1..i2"
    compute_client = MagicMock()
    compute_client.list_volume_attachments.side_effect = [
        _resp([att1], next_page="page2"),
        _resp([att2]),
    ]
    result = _build_attachment_map(compute_client, _COMPARTMENT)
    assert len(result) == 2


def test_build_attachment_map_empty():
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([])
    result = _build_attachment_map(compute_client, _COMPARTMENT)
    assert result == {}


# ── _collect_volume_metrics ───────────────────────────────────────────────────

def test_collect_volume_metrics_returns_four_values():
    mon_client = MagicMock()
    with patch("src.collector.storage._query_metric", return_value=[]), \
         patch("src.collector.storage._extract_aggregated_values", return_value=[]):
        result = _collect_volume_metrics(
            mon_client, _COMPARTMENT, "ocid1.volume.oc1..v1", _NOW, _NOW, "5m",
        )
    assert len(result) == 4


def test_collect_volume_metrics_returns_none_on_exception():
    mon_client = MagicMock()
    with patch("src.collector.storage._query_metric", side_effect=Exception("API error")):
        r_tp, w_tp, r_iops, w_iops = _collect_volume_metrics(
            mon_client, _COMPARTMENT, "ocid1.volume.oc1..v1", _NOW, _NOW, "5m",
        )
    assert r_tp is None
    assert w_tp is None
    assert r_iops is None
    assert w_iops is None


def test_collect_volume_metrics_computes_mean():
    mon_client = MagicMock()
    with patch("src.collector.storage._query_metric", return_value=[MagicMock()]), \
         patch("src.collector.storage._extract_aggregated_values", return_value=[10.0, 20.0]):
        r_tp, w_tp, r_iops, w_iops = _collect_volume_metrics(
            mon_client, _COMPARTMENT, "ocid1.volume.oc1..v1", _NOW, _NOW, "5m",
        )
    assert r_tp == pytest.approx(15.0)


def test_collect_volume_metrics_none_when_empty_vals():
    mon_client = MagicMock()
    with patch("src.collector.storage._query_metric", return_value=[MagicMock()]), \
         patch("src.collector.storage._extract_aggregated_values", return_value=[]):
        r_tp, w_tp, r_iops, w_iops = _collect_volume_metrics(
            mon_client, _COMPARTMENT, "ocid1.volume.oc1..v1", _NOW, _NOW, "5m",
        )
    assert r_tp is None


# ── collect_volumes ───────────────────────────────────────────────────────────

def test_collect_volumes_dry_run_returns_block_volume():
    vol = _vol()
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([])
    bs_client = MagicMock()
    bs_client.list_volumes.return_value = _resp([vol])
    factory = _factory(bs_client=bs_client, compute_client=compute_client)
    results = collect_volumes(
        factory, _COMPARTMENT, _REGION, _NOW, _NOW,
        metrics_interval_minutes=5, dry_run=True,
    )
    assert len(results) == 1
    assert isinstance(results[0], BlockVolume)
    assert results[0].read_throughput_avg is None


def test_collect_volumes_dry_run_no_monitoring():
    vol = _vol()
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([])
    bs_client = MagicMock()
    bs_client.list_volumes.return_value = _resp([vol])
    mon_client = MagicMock()
    factory = _factory(bs_client=bs_client, compute_client=compute_client, mon_client=mon_client)
    collect_volumes(
        factory, _COMPARTMENT, _REGION, _NOW, _NOW,
        metrics_interval_minutes=5, dry_run=True,
    )
    mon_client.summarize_metrics_data.assert_not_called()


def test_collect_volumes_full_run_sets_metrics():
    vol = _vol()
    att = MagicMock()
    att.lifecycle_state = "ATTACHED"
    att.volume_id = vol.id
    att.instance_id = "ocid1.instance.oc1..i1"
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([att])
    bs_client = MagicMock()
    bs_client.list_volumes.return_value = _resp([vol])
    with patch("src.collector.storage._collect_volume_metrics", return_value=(1.0, 2.0, 3.0, 4.0)):
        factory = _factory(bs_client=bs_client, compute_client=compute_client)
        results = collect_volumes(
            factory, _COMPARTMENT, _REGION, _NOW, _NOW,
            metrics_interval_minutes=5, dry_run=False,
        )
    assert len(results) == 1
    bv = results[0]
    assert bv.read_throughput_avg == 1.0
    assert bv.write_throughput_avg == 2.0
    assert bv.attached_instance_id == "ocid1.instance.oc1..i1"


def test_collect_volumes_vpu_defaults_to_10():
    vol = _vol()
    vol.vpus_per_gb = None
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([])
    bs_client = MagicMock()
    bs_client.list_volumes.return_value = _resp([vol])
    factory = _factory(bs_client=bs_client, compute_client=compute_client)
    results = collect_volumes(
        factory, _COMPARTMENT, _REGION, _NOW, _NOW,
        metrics_interval_minutes=5, dry_run=True,
    )
    assert results[0].vpu_per_gb == 10


def test_collect_volumes_multi_page():
    vol1 = _vol("ocid1.volume.oc1..v1", "vol-1")
    vol2 = _vol("ocid1.volume.oc1..v2", "vol-2")
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([])
    bs_client = MagicMock()
    bs_client.list_volumes.side_effect = [
        _resp([vol1], next_page="p2"),
        _resp([vol2]),
    ]
    factory = _factory(bs_client=bs_client, compute_client=compute_client)
    results = collect_volumes(
        factory, _COMPARTMENT, _REGION, _NOW, _NOW,
        metrics_interval_minutes=5, dry_run=True,
    )
    assert len(results) == 2


def test_collect_volumes_empty_compartment():
    compute_client = MagicMock()
    compute_client.list_volume_attachments.return_value = _resp([])
    bs_client = MagicMock()
    bs_client.list_volumes.return_value = _resp([])
    factory = _factory(bs_client=bs_client, compute_client=compute_client)
    results = collect_volumes(
        factory, _COMPARTMENT, _REGION, _NOW, _NOW,
        metrics_interval_minutes=5, dry_run=True,
    )
    assert results == []
