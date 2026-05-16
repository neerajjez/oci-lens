"""Orchestrates a full OCI collection run and writes raw JSON output."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.date_utils import collection_window
from src.utils.logger import get_logger

log = get_logger(__name__)


class _DatetimeEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class CollectorRunner:
    def __init__(self, config: dict) -> None:
        self._config = config

    def run(self, output_path: Path) -> None:
        from src.collector.compute import collect_instances
        from src.collector.cost import collect_costs
        from src.collector.oci_client import OciClientFactory
        from src.collector.storage import collect_volumes

        cfg = self._config
        compartments: list[str] = cfg.get("compartments", [])
        regions: list[str] = cfg.get("regions", ["us-ashburn-1"])
        period_days: int = cfg.get("collection_period_days", 15)
        metrics_interval: int = cfg.get("metrics_interval_minutes", 5)
        tenant_id: str = cfg.get("tenant_id", "")

        start, end = collection_window(period_days)
        factory = OciClientFactory(cfg)

        all_instances = []
        all_volumes = []
        for compartment_id in compartments:
            for region in regions:
                log.info("collecting_region", compartment=compartment_id, region=region)
                instances = collect_instances(
                    factory, compartment_id, region, start, end,
                    metrics_interval_minutes=metrics_interval,
                )
                all_instances.extend(instances)
                volumes = collect_volumes(
                    factory, compartment_id, region, start, end,
                    metrics_interval_minutes=metrics_interval,
                )
                all_volumes.extend(volumes)

        all_costs = collect_costs(factory, tenant_id, compartments, start, end)

        raw = {
            "schema_version": "1.0.0",
            "collected_at": datetime.utcnow().isoformat(),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "instances": [dataclasses.asdict(i) for i in all_instances],
            "volumes": [dataclasses.asdict(v) for v in all_volumes],
            "costs": [dataclasses.asdict(c) for c in all_costs],
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(raw, cls=_DatetimeEncoder, indent=2))
        log.info("collection_written", path=str(output_path))
