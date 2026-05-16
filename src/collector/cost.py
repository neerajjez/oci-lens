from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import oci

from src.collector.oci_client import OciClientFactory, with_retry
from src.models.schemas import CostRecord
from src.utils.date_utils import to_rfc3339
from src.utils.logger import get_logger

log = get_logger(__name__)

@with_retry
def _request_usages_page(
    client: oci.usage_api.UsageapiClient,
    request_details: oci.usage_api.models.RequestSummarizedUsagesDetails,
    page: Optional[str],
) -> oci.response.Response:
    kwargs: dict = {"request_summarized_usages_details": request_details}
    if page:
        kwargs["page"] = page
    return client.request_summarized_usages(**kwargs)


def collect_costs(
    factory: OciClientFactory,
    tenant_id: str,
    compartment_ids: list[str],
    start: datetime,
    end: datetime,
    dry_run: bool = False,
    home_region: str = "me-jeddah-1",
) -> list[CostRecord]:
    if dry_run:
        log.info("cost_collection_skipped", reason="dry_run")
        return []

    log.info("cost_api_region", home_region=home_region)
    client = factory.usage_api(home_region)
    records: list[CostRecord] = []

    for compartment_id in compartment_ids:
        log.info("collecting_costs", compartment=compartment_id)

        request_details = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=tenant_id,
            time_usage_started=to_rfc3339(start),
            time_usage_ended=to_rfc3339(end),
            granularity="DAILY",
            group_by=["resourceId", "service", "compartmentId", "skuName"],
            compartment_depth=1,
            filter=oci.usage_api.models.Filter(
                operator="AND",
                dimensions=[
                    oci.usage_api.models.Dimension(
                        key="compartmentId",
                        value=compartment_id,
                    )
                ],
            ),
        )

        page: Optional[str] = None
        while True:
            try:
                resp = _request_usages_page(client, request_details, page)
            except oci.exceptions.ServiceError as exc:
                log.error("cost_api_error", compartment=compartment_id, status=exc.status, message=exc.message)
                break
            except Exception as exc:
                log.warning("cost_api_request_failed", compartment=compartment_id, error=str(exc))
                break

            for item in resp.data.items or []:
                cost = item.computed_amount or 0.0
                records.append(
                    CostRecord(
                        resource_id=item.resource_id or _dim(item, "resourceId") or "",
                        service=item.service or _dim(item, "service") or "",
                        compartment_id=compartment_id,
                        sku_description=item.sku_name or _dim(item, "skuName") or "",
                        currency=item.currency or "USD",
                        total_cost=float(cost),
                        period_start=start,
                        period_end=end,
                    )
                )

            page = resp.next_page
            if not page:
                break

    log.info("cost_records_collected", count=len(records))
    return records


def _dim(item: Any, key: str) -> Optional[str]:
    for tag in (item.tags or []):
        if tag.namespace == key or tag.key == key:
            return tag.value
    return None
