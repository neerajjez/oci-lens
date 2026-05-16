"""Tests for src/collector/cost.py."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.collector.cost import _dim, collect_costs


_NOW = datetime(2024, 5, 1, tzinfo=timezone.utc)
_COMPARTMENT = "ocid1.compartment.oc1..aaa"
_TENANT = "ocid1.tenancy.oc1..ttt"


def _factory(usage_client=None):
    f = MagicMock()
    f.usage_api.return_value = usage_client or MagicMock()
    return f


def _resp(items=None, next_page=None):
    r = MagicMock()
    r.data.items = items or []
    r.next_page = next_page
    return r


def _item(resource_id="ocid1.instance.oc1..r1", service="compute",
          sku="B91961", currency="USD", amount=10.0):
    item = MagicMock()
    item.computed_amount = amount
    item.currency = currency
    item.service = service
    tag_resource = MagicMock()
    tag_resource.namespace = "resourceId"
    tag_resource.key = "resourceId"
    tag_resource.value = resource_id
    tag_service = MagicMock()
    tag_service.namespace = "service"
    tag_service.key = "service"
    tag_service.value = service
    tag_sku = MagicMock()
    tag_sku.namespace = "skuName"
    tag_sku.key = "skuName"
    tag_sku.value = sku
    item.tags = [tag_resource, tag_service, tag_sku]
    return item


# ── dry_run ───────────────────────────────────────────────────────────────────

def test_collect_costs_dry_run_returns_empty():
    factory = _factory()
    result = collect_costs(factory, _TENANT, [_COMPARTMENT], _NOW, _NOW, dry_run=True)
    assert result == []
    factory.usage_api.assert_not_called()


# ── empty compartments ────────────────────────────────────────────────────────

def test_collect_costs_no_compartments_returns_empty():
    result = collect_costs(_factory(), _TENANT, [], _NOW, _NOW)
    assert result == []


# ── normal collection ─────────────────────────────────────────────────────────

def test_collect_costs_returns_cost_records():
    with patch("src.collector.cost._request_usages_page", return_value=_resp([_item()])):
        result = collect_costs(_factory(), _TENANT, [_COMPARTMENT], _NOW, _NOW)
    assert len(result) == 1
    assert result[0].total_cost == pytest.approx(10.0)
    assert result[0].currency == "USD"


def test_collect_costs_sets_compartment_id():
    with patch("src.collector.cost._request_usages_page", return_value=_resp([_item()])):
        result = collect_costs(_factory(), _TENANT, [_COMPARTMENT], _NOW, _NOW)
    assert result[0].compartment_id == _COMPARTMENT


def test_collect_costs_sets_period():
    with patch("src.collector.cost._request_usages_page", return_value=_resp([_item()])):
        result = collect_costs(_factory(), _TENANT, [_COMPARTMENT], _NOW, _NOW)
    assert result[0].period_start == _NOW
    assert result[0].period_end == _NOW


def test_collect_costs_defaults_zero_when_computed_amount_none():
    with patch("src.collector.cost._request_usages_page", return_value=_resp([_item(amount=None)])):
        result = collect_costs(_factory(), _TENANT, [_COMPARTMENT], _NOW, _NOW)
    assert result[0].total_cost == pytest.approx(0.0)


def test_collect_costs_multi_page():
    responses = [
        _resp([_item(resource_id="ocid1.instance.oc1..r1", amount=5.0)], next_page="p2"),
        _resp([_item(resource_id="ocid1.instance.oc1..r2", amount=8.0)]),
    ]
    with patch("src.collector.cost._request_usages_page", side_effect=responses):
        result = collect_costs(_factory(), _TENANT, [_COMPARTMENT], _NOW, _NOW)
    assert len(result) == 2


def test_collect_costs_service_error_skips_compartment():
    import oci
    err = oci.exceptions.ServiceError(429, "TooManyRequests", {}, "rate limit")
    with patch("src.collector.cost._request_usages_page", side_effect=err):
        result = collect_costs(_factory(), _TENANT, [_COMPARTMENT], _NOW, _NOW)
    assert result == []


def test_collect_costs_multiple_compartments():
    with patch("src.collector.cost._request_usages_page", return_value=_resp([_item()])):
        result = collect_costs(
            _factory(), _TENANT,
            [_COMPARTMENT, "ocid1.compartment.oc1..bbb"],
            _NOW, _NOW,
        )
    assert len(result) == 2


def test_collect_costs_empty_items_list():
    with patch("src.collector.cost._request_usages_page", return_value=_resp([])):
        result = collect_costs(_factory(), _TENANT, [_COMPARTMENT], _NOW, _NOW)
    assert result == []


# ── _dim helper ───────────────────────────────────────────────────────────────

def test_dim_finds_by_namespace():
    tag = MagicMock()
    tag.namespace = "resourceId"
    tag.key = "something_else"
    tag.value = "ocid1.instance.oc1..x"
    item = MagicMock()
    item.tags = [tag]
    assert _dim(item, "resourceId") == "ocid1.instance.oc1..x"


def test_dim_finds_by_key():
    tag = MagicMock()
    tag.namespace = "other"
    tag.key = "resourceId"
    tag.value = "ocid1.instance.oc1..y"
    item = MagicMock()
    item.tags = [tag]
    assert _dim(item, "resourceId") == "ocid1.instance.oc1..y"


def test_dim_returns_none_when_not_found():
    tag = MagicMock()
    tag.namespace = "unrelated"
    tag.key = "unrelated"
    item = MagicMock()
    item.tags = [tag]
    assert _dim(item, "resourceId") is None


def test_dim_returns_none_when_tags_empty():
    item = MagicMock()
    item.tags = []
    assert _dim(item, "resourceId") is None


def test_dim_handles_none_tags():
    item = MagicMock()
    item.tags = None
    assert _dim(item, "resourceId") is None
