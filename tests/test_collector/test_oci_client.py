from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, call, patch

import oci
from oci.exceptions import ServiceError

from src.collector.oci_client import OciClientFactory, with_retry


def _make_service_error(status: int) -> ServiceError:
    err = ServiceError(status=status, code="TestCode", headers={}, message="test error")
    return err


class TestWithRetry(unittest.TestCase):
    def test_success_on_first_attempt(self):
        mock_fn = MagicMock(return_value="ok")
        decorated = with_retry(mock_fn)
        result = decorated("arg1", key="val")
        self.assertEqual(result, "ok")
        mock_fn.assert_called_once_with("arg1", key="val")

    @patch("src.collector.oci_client.time.sleep")
    def test_retry_on_429(self, mock_sleep: MagicMock):
        mock_fn = MagicMock(
            side_effect=[
                _make_service_error(429),
                _make_service_error(429),
                "success",
            ]
        )
        decorated = with_retry(mock_fn)
        result = decorated()
        self.assertEqual(result, "success")
        self.assertEqual(mock_fn.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)

    @patch("src.collector.oci_client.time.sleep")
    def test_retry_on_500(self, mock_sleep: MagicMock):
        mock_fn = MagicMock(
            side_effect=[
                _make_service_error(503),
                "recovered",
            ]
        )
        decorated = with_retry(mock_fn)
        result = decorated()
        self.assertEqual(result, "recovered")
        self.assertEqual(mock_fn.call_count, 2)
        mock_sleep.assert_called_once_with(2.0)

    @patch("src.collector.oci_client.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep: MagicMock):
        mock_fn = MagicMock(side_effect=_make_service_error(429))
        decorated = with_retry(mock_fn)
        with self.assertRaises(ServiceError) as ctx:
            decorated()
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(mock_fn.call_count, 3)

    @patch("src.collector.oci_client.time.sleep")
    def test_non_retryable_raises_immediately(self, mock_sleep: MagicMock):
        mock_fn = MagicMock(side_effect=_make_service_error(404))
        decorated = with_retry(mock_fn)
        with self.assertRaises(ServiceError) as ctx:
            decorated()
        self.assertEqual(ctx.exception.status, 404)
        mock_fn.assert_called_once()
        mock_sleep.assert_not_called()


class TestOciClientFactoryAuth(unittest.TestCase):
    @patch("src.collector.oci_client._try_instance_principal", return_value=None)
    @patch("src.collector.oci_client._load_config_file")
    def test_falls_back_to_config_file(self, mock_load: MagicMock, mock_ip: MagicMock):
        mock_load.return_value = {"region": "us-ashburn-1", "tenancy": "ocid1.tenancy.xxx"}
        factory = OciClientFactory("~/.oci/config", "DEFAULT")
        mock_ip.assert_called_once()
        mock_load.assert_called_once_with("~/.oci/config", "DEFAULT")

    @patch("src.collector.oci_client._try_instance_principal")
    def test_uses_instance_principal_when_available(self, mock_ip: MagicMock):
        fake_signer = MagicMock()
        mock_ip.return_value = {"signer": fake_signer}
        factory = OciClientFactory("~/.oci/config", "DEFAULT")
        self.assertEqual(factory._signer, fake_signer)
        self.assertEqual(factory._cfg, {})


class TestPagination(unittest.TestCase):
    @patch("src.collector.compute._list_instances_page")
    def test_pagination_across_two_pages(self, mock_page: MagicMock):
        from src.collector.compute import list_all_instances

        page1 = MagicMock()
        page1.data = [MagicMock(id=f"inst-{i}") for i in range(3)]
        page1.next_page = "token-page-2"

        page2 = MagicMock()
        page2.data = [MagicMock(id=f"inst-{i}") for i in range(3, 5)]
        page2.next_page = None

        mock_page.side_effect = [page1, page2]

        client = MagicMock()
        result = list_all_instances(client, "ocid1.compartment.xxx")

        self.assertEqual(len(result), 5)
        self.assertEqual(mock_page.call_count, 2)
        mock_page.assert_any_call(client, "ocid1.compartment.xxx", None)
        mock_page.assert_any_call(client, "ocid1.compartment.xxx", "token-page-2")

    @patch("src.collector.compute._list_instances_page")
    def test_empty_compartment_returns_empty_list(self, mock_page: MagicMock):
        from src.collector.compute import list_all_instances

        page1 = MagicMock()
        page1.data = []
        page1.next_page = None

        mock_page.return_value = page1

        client = MagicMock()
        result = list_all_instances(client, "ocid1.compartment.empty")

        self.assertEqual(result, [])

    @patch("src.collector.compute._query_metric", return_value=[])
    def test_missing_metrics_handled_gracefully(self, mock_metric: MagicMock):
        from src.collector.compute import _collect_cpu
        from datetime import datetime, timezone

        mon_client = MagicMock()
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, tzinfo=timezone.utc)

        result = _collect_cpu(mon_client, "ocid1.compartment.xxx", "ocid1.instance.xxx", start, end, "60m")

        self.assertIsNone(result.avg)
        self.assertIsNone(result.p50)
        self.assertIsNone(result.p95)
        self.assertIsNone(result.p99)
        self.assertIsNone(result.peak)


if __name__ == "__main__":
    unittest.main()
