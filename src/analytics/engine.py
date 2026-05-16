from __future__ import annotations

import json
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.analytics.anomaly import Anomaly, detect_anomalies
from src.analytics.confidence import ConfidenceLabel, ConfidenceResult
from src.analytics.loader import ValidationReport, load_raw
from src.analytics.ratios import FleetKPIs, compute_fleet_kpis
from src.analytics.right_sizer import (
    Recommendation, RecommendationType, RiskLevel, ShapeConfig,
    generate_recommendations,
)
from src.analytics.shape_catalog import ShapeCatalog
from src.analytics.utilization import UtilizationPattern, profile_utilization
from src.analytics.cost_mapper import CostMapperResult, InstanceCostSummary, attribute_costs
from src.utils.logger import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = "1.0.0"
LARGE_FLEET_THRESHOLD = 100   # use ProcessPoolExecutor above this


@dataclass
class AnalyticsResult:
    schema_version: str
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    raw_input_path: str
    validation_report: ValidationReport
    recommendations: list[Recommendation]
    fleet_kpis: FleetKPIs
    anomalies: list[Anomaly]
    instance_costs: list[InstanceCostSummary] = field(default_factory=list)
    object_storage_costs: dict = field(default_factory=dict)  # bucket_name → total_cost
    volumes: list = field(default_factory=list)               # raw volume dicts for storage section
    buckets: list = field(default_factory=list)               # raw bucket dicts for object storage section
    tenancy_name: str = ""
    compartment_name: str = ""


class _AnalyticsEncoder(json.JSONEncoder):
    """Handles Decimal, datetime, Enum, dataclasses in JSON serialization."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        return super().default(obj)


class AnalyticsEngine:
    def __init__(
        self,
        config: dict,
        catalog: Optional[ShapeCatalog] = None,
        catalog_path: Optional[Path] = None,
    ):
        self._config = config
        if catalog is not None:
            self._catalog = catalog
        else:
            cp = catalog_path or (Path(__file__).parent.parent.parent / "config" / "shapes.json")
            override_path = None
            if config.get("pricing_override_path"):
                override_path = Path(config["pricing_override_path"])
            self._catalog = ShapeCatalog(cp, override_path)

    def run(
        self,
        raw_data_path: Path,
        previous_run_path: Optional[Path] = None,
    ) -> AnalyticsResult:
        """
        Full analytics pipeline:
        1. Load and validate raw data
        2. Profile utilization (parallel for large fleets)
        3. Attribute costs
        4. Generate right-sizing recommendations
        5. Compute fleet KPIs
        6. Detect anomalies
        7. Return AnalyticsResult
        """
        # 1. Load and validate
        log.info("analytics_load_start", path=str(raw_data_path))
        instances_df, metrics_df, costs_df, volumes_df, buckets_df, validation_report = load_raw(
            raw_data_path, self._config
        )
        if not validation_report.passed:
            log.warning("validation_issues", violations=len(validation_report.violations))
        log.info("analytics_load_complete",
                 instances=len(instances_df),
                 metrics=len(metrics_df),
                 costs=len(costs_df),
                 volumes=len(volumes_df),
                 buckets=len(buckets_df))

        # Parse period and metadata from raw data
        raw = json.loads(raw_data_path.read_text(encoding="utf-8"))
        period_start = datetime.fromisoformat(raw["period_start"])
        period_end = datetime.fromisoformat(raw["period_end"])
        collection_period_days = max(1, (period_end - period_start).days)
        tenancy_name = str(raw.get("tenancy_name") or "")
        compartment_name = str(raw.get("compartment_name") or "")

        # 2. Utilization profiling
        log.info("analytics_utilization_start")
        utilization_df = profile_utilization(instances_df, metrics_df)
        log.info("analytics_utilization_complete", instances=len(utilization_df))

        # 3. Cost attribution
        log.info("analytics_cost_attribution_start")
        cost_result = attribute_costs(
            instances_df, costs_df, volumes_df, utilization_df, collection_period_days,
            buckets_df=buckets_df,
        )
        log.info("analytics_cost_attribution_complete",
                 orphaned_cost=cost_result.orphaned_cost_total)

        # 4. Recommendations
        log.info("analytics_recommendations_start")
        recommendations = generate_recommendations(
            instances_df, utilization_df, cost_result.cost_attribution_df, self._catalog
        )
        log.info("analytics_recommendations_complete", count=len(recommendations))

        # 5. Fleet KPIs
        log.info("analytics_kpis_start")
        fleet_kpis = compute_fleet_kpis(
            instances_df, utilization_df, cost_result.cost_attribution_df,
            recommendations, collection_period_days,
            orphaned_cost_total=cost_result.orphaned_cost_total,
            previous_run_path=previous_run_path,
        )

        # 6. Anomalies
        log.info("analytics_anomalies_start")
        anomalies = detect_anomalies(
            instances_df, utilization_df, cost_result.cost_attribution_df,
            volumes_df, metrics_df, collection_period_days
        )
        log.info("analytics_anomalies_complete", count=len(anomalies))

        # Build per-instance cost summaries for the cost report
        instance_costs: list[InstanceCostSummary] = []
        if not cost_result.cost_attribution_df.empty:
            name_shape = {}
            if "instance_id" in instances_df.columns:
                for _, irow in instances_df.iterrows():
                    iid = str(irow["instance_id"])
                    name_shape[iid] = (
                        str(irow.get("display_name", iid)),
                        str(irow.get("shape", "")),
                    )
            for _, crow in cost_result.cost_attribution_df.iterrows():
                iid = str(crow["instance_id"])
                dname, shape = name_shape.get(iid, (iid, ""))
                instance_costs.append(InstanceCostSummary(
                    instance_id=iid,
                    display_name=dname,
                    shape=shape,
                    compute_cost=float(crow.get("compute_cost", 0.0) or 0.0),
                    storage_cost=float(crow.get("attached_storage_cost", 0.0) or 0.0),
                    total_cost=float(crow.get("total_cost", 0.0) or 0.0),
                    daily_cost_avg=float(crow.get("daily_cost_avg", 0.0) or 0.0),
                    wasted_spend_estimate=float(crow.get("wasted_spend_estimate", 0.0) or 0.0),
                    no_billing_data=bool(crow.get("no_billing_data", True)),
                ))
            instance_costs.sort(key=lambda x: x.total_cost, reverse=True)

        volumes_list = volumes_df.to_dict("records") if not volumes_df.empty else []
        buckets_list = buckets_df.to_dict("records") if not buckets_df.empty else []

        return AnalyticsResult(
            schema_version=SCHEMA_VERSION,
            generated_at=datetime.now(timezone.utc),
            period_start=period_start,
            period_end=period_end,
            raw_input_path=str(raw_data_path),
            validation_report=validation_report,
            recommendations=recommendations,
            fleet_kpis=fleet_kpis,
            anomalies=anomalies,
            instance_costs=instance_costs,
            object_storage_costs=cost_result.object_storage_cost_map,
            volumes=volumes_list,
            buckets=buckets_list,
            tenancy_name=tenancy_name,
            compartment_name=compartment_name,
        )

    def to_json(self, result: AnalyticsResult, indent: int = 2) -> str:
        """Serialize AnalyticsResult to JSON string.

        Uses asdict() to recursively convert all nested dataclasses to plain
        dicts, then _AnalyticsEncoder to handle Decimal, datetime, and Enum
        values that asdict() leaves as-is.
        """
        return json.dumps(asdict(result), cls=_AnalyticsEncoder, indent=indent)
