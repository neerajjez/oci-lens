"""
src/analytics/cost_mapper.py
============================
OCI Cost Optimisation Analytics – cost attribution engine.

Joins OCI billing records to compute instances, volumes, and identifies
orphaned or fleet-overhead costs. Produces a cost_attribution_df with one
row per instance plus summary totals used by downstream modules.

Public API
----------
attribute_costs(instances_df, costs_df, volumes_df, utilization_df,
                collection_period_days) -> CostMapperResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class InstanceCostSummary:
    instance_id: str
    display_name: str
    shape: str
    compute_cost: float
    storage_cost: float
    total_cost: float
    daily_cost_avg: float
    wasted_spend_estimate: float
    no_billing_data: bool


@dataclass
class CostMapperResult:
    cost_attribution_df: pd.DataFrame
    orphaned_costs_df: pd.DataFrame    # cost records not matched to any instance
    fleet_overhead_cost: float         # untaggable / shared costs
    orphaned_cost_total: float
    object_storage_cost_map: dict = field(default_factory=dict)  # bucket_name → total_cost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_sum(series: pd.Series) -> float:
    """Sum a series, returning 0.0 if it is empty or all-NaN."""
    if series.empty:
        return 0.0
    total = series.sum()
    return float(total) if not np.isnan(total) else 0.0


def _std_or_zero(series: pd.Series) -> float:
    """Std-dev of a series; 0.0 when fewer than two finite values."""
    finite = series.dropna()
    if len(finite) < 2:
        return 0.0
    return float(finite.std(ddof=1))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def attribute_costs(
    instances_df: pd.DataFrame,
    costs_df: pd.DataFrame,
    volumes_df: pd.DataFrame,
    utilization_df: pd.DataFrame,
    collection_period_days: int = 15,
    buckets_df: Optional[pd.DataFrame] = None,
) -> CostMapperResult:
    """
    Attribute billing costs to compute instances, detect orphaned spend, and
    compute per-instance cost efficiency metrics.

    Parameters
    ----------
    instances_df:
        One row per compute instance (from loader / utilization pipeline).
    costs_df:
        OCI billing line-items (mutated in place to mark is_orphaned=True).
    volumes_df:
        Block-volume inventory (used to map storage costs to parent instances).
    utilization_df:
        Per-instance utilization summary including composite_score.
    collection_period_days:
        Length of the billing / metrics window (default 15 days).

    Returns
    -------
    CostMapperResult
    """
    log.info(
        "attribute_costs_start",
        n_instances=len(instances_df),
        n_cost_records=len(costs_df),
        n_volumes=len(volumes_df),
        collection_period_days=collection_period_days,
    )

    # Guard: empty fleet
    if instances_df.empty:
        log.warning("attribute_costs_no_instances")
        empty_attr = _empty_cost_attribution_df()
        orphaned_costs = costs_df.copy() if not costs_df.empty else _empty_costs_subset(costs_df)
        orphaned_total = _safe_sum(costs_df["cost_usd"]) if not costs_df.empty else 0.0
        return CostMapperResult(
            cost_attribution_df=empty_attr,
            orphaned_costs_df=orphaned_costs,
            fleet_overhead_cost=0.0,
            orphaned_cost_total=orphaned_total,
            object_storage_cost_map={},
        )

    # Collect known IDs for classification
    instance_ids: set[str] = set(instances_df["instance_id"].dropna().unique())
    volume_ids: set[str] = (
        set(volumes_df["volume_id"].dropna().unique()) if not volumes_df.empty else set()
    )
    bucket_names: set[str] = (
        set(buckets_df["name"].dropna().unique())
        if buckets_df is not None and not buckets_df.empty and "name" in buckets_df.columns
        else set()
    )
    object_storage_cost_map: dict[str, float] = {}

    # Build volume → parent instance lookup
    vol_to_instance: dict[str, str] = {}
    if not volumes_df.empty:
        for _, vrow in volumes_df.iterrows():
            vid = str(vrow.get("volume_id", ""))
            parent = str(vrow.get("attached_instance_id", ""))
            if vid and parent:
                vol_to_instance[vid] = parent

    # -----------------------------------------------------------------------
    # STEP 1 – DIRECT ATTRIBUTION: resource_id matches an instance_id
    # -----------------------------------------------------------------------
    compute_cost_map: dict[str, float] = {iid: 0.0 for iid in instance_ids}
    compute_cost_records: dict[str, list[float]] = {iid: [] for iid in instance_ids}

    # -----------------------------------------------------------------------
    # STEP 2 – VOLUME ATTRIBUTION: resource_id matches a volume_id
    # -----------------------------------------------------------------------
    storage_cost_map: dict[str, float] = {iid: 0.0 for iid in instance_ids}

    # -----------------------------------------------------------------------
    # STEP 4 & 5 – ORPHANED and FLEET OVERHEAD classification
    # -----------------------------------------------------------------------
    orphan_mask: list[bool] = []
    fleet_overhead_indices: list[int] = []

    if not costs_df.empty:
        for idx, crow in costs_df.iterrows():
            rid = str(crow.get("resource_id", "")).strip()
            cost = float(crow.get("cost_usd", 0.0) or 0.0)
            if np.isnan(cost):
                cost = 0.0

            if not rid:
                # Empty resource_id → fleet overhead
                fleet_overhead_indices.append(idx)
                orphan_mask.append(False)
                continue

            if rid in instance_ids:
                # Direct compute attribution
                compute_cost_map[rid] = compute_cost_map.get(rid, 0.0) + cost
                compute_cost_records[rid].append(cost)
                orphan_mask.append(False)
            elif rid in volume_ids:
                # Volume storage cost — map to parent instance if attached
                parent_iid = vol_to_instance.get(rid, "")
                if parent_iid and parent_iid in instance_ids:
                    storage_cost_map[parent_iid] = storage_cost_map.get(parent_iid, 0.0) + cost
                # If unattached volume cost, still not "orphaned" per spec
                # (it belongs to the volume, which has no instance)
                orphan_mask.append(False)
            elif rid in bucket_names:
                # Object storage cost attributed to a known bucket by name
                object_storage_cost_map[rid] = object_storage_cost_map.get(rid, 0.0) + cost
                orphan_mask.append(False)
            else:
                # Not matched to any known instance, volume, or bucket → orphaned
                orphan_mask.append(True)
    else:
        orphan_mask = []

    # -----------------------------------------------------------------------
    # Mark orphaned records in costs_df in-place
    # -----------------------------------------------------------------------
    if not costs_df.empty and orphan_mask:
        costs_df.loc[costs_df.index[:len(orphan_mask)], "is_orphaned"] = orphan_mask

    orphaned_costs_df: pd.DataFrame
    if not costs_df.empty:
        orphaned_costs_df = costs_df[costs_df["is_orphaned"]].copy()
    else:
        orphaned_costs_df = _empty_costs_subset(costs_df)

    orphaned_cost_total = _safe_sum(orphaned_costs_df["cost_usd"]) if not orphaned_costs_df.empty else 0.0

    # -----------------------------------------------------------------------
    # STEP 5 – FLEET OVERHEAD
    # -----------------------------------------------------------------------
    fleet_overhead_cost = 0.0
    if not costs_df.empty and fleet_overhead_indices:
        fleet_rows = costs_df.loc[fleet_overhead_indices]
        fleet_overhead_cost = _safe_sum(fleet_rows["cost_usd"])

    log.info(
        "attribute_costs_classification",
        orphaned_records=len(orphaned_costs_df),
        orphaned_cost_total=round(orphaned_cost_total, 4),
        fleet_overhead_cost=round(fleet_overhead_cost, 4),
    )

    # -----------------------------------------------------------------------
    # STEP 6 – DAILY COST STATS
    # -----------------------------------------------------------------------
    # Build daily_cost_stddev per instance from individual cost records
    daily_stddev_map: dict[str, float] = {}
    for iid in instance_ids:
        records = compute_cost_records.get(iid, [])
        daily_stddev_map[iid] = _std_or_zero(pd.Series(records))

    # -----------------------------------------------------------------------
    # Merge utilization_df to get composite_score and data coverage fields
    # -----------------------------------------------------------------------
    util_cols = [
        "instance_id",
        "composite_score",
        "has_memory_data",
        "has_timeseries",
        "pattern",
    ]
    # Only keep columns that actually exist in utilization_df
    available_util_cols = [c for c in util_cols if c in utilization_df.columns]

    if not utilization_df.empty and "instance_id" in utilization_df.columns:
        util_subset = utilization_df[available_util_cols].copy()
    else:
        util_subset = pd.DataFrame(columns=util_cols)

    # Merge instances with utilization (left join to keep all instances)
    inst_cols_needed = ["instance_id", "display_name", "sufficient_data", "data_coverage_days"]
    inst_extra = [c for c in ["shape_config"] if c in instances_df.columns]
    inst_subset = instances_df[inst_cols_needed + inst_extra].copy()

    merged = inst_subset.merge(util_subset, on="instance_id", how="left")

    # Fill missing composite_score with 0.0
    if "composite_score" not in merged.columns:
        merged["composite_score"] = 0.0
    else:
        merged["composite_score"] = merged["composite_score"].fillna(0.0)

    if "data_coverage_days" not in merged.columns:
        merged["data_coverage_days"] = 0.0

    # -----------------------------------------------------------------------
    # STEP 7 – PER-UNIT COSTS
    # -----------------------------------------------------------------------
    # We need shape_config (ocpu, ram_gb) if available
    # These come from instances_df if "shape_config" column exists

    # -----------------------------------------------------------------------
    # Build output rows
    # -----------------------------------------------------------------------
    rows: list[dict] = []

    for _, mrow in merged.iterrows():
        iid = str(mrow["instance_id"])
        compute_cost = compute_cost_map.get(iid, 0.0)
        storage_cost = storage_cost_map.get(iid, 0.0)

        # STEP 3 – NETWORK EGRESS: 0.0 (no detailed billing line items yet)
        network_egress_cost = 0.0

        total_cost = compute_cost + storage_cost + network_egress_cost
        no_billing_data = (total_cost == 0.0)

        # STEP 6 – Daily cost stats
        daily_cost_avg = total_cost / collection_period_days if collection_period_days > 0 else 0.0
        daily_cost_stddev = daily_stddev_map.get(iid, 0.0)

        # STEP 7 – Per-unit costs
        cost_per_vcpu_hour: float = -1.0
        cost_per_gb_ram_hour: float = -1.0

        shape_cfg = mrow.get("shape_config") if "shape_config" in mrow.index else None
        if shape_cfg and isinstance(shape_cfg, dict):
            ocpu = shape_cfg.get("ocpu")
            ram_gb = shape_cfg.get("ram_gb")
            if ocpu and ocpu > 0 and total_cost > 0:
                total_vcpu_hours = ocpu * collection_period_days * 24.0
                cost_per_vcpu_hour = total_cost / total_vcpu_hours
            if ram_gb and ram_gb > 0 and total_cost > 0:
                total_gb_ram_hours = ram_gb * collection_period_days * 24.0
                cost_per_gb_ram_hour = total_cost / total_gb_ram_hours

        # STEP 8 – WASTED SPEND
        composite_score = float(mrow.get("composite_score", 0.0))
        data_coverage_days = float(mrow.get("data_coverage_days", 0.0))
        sufficient_data = bool(mrow.get("sufficient_data", False))

        if no_billing_data or data_coverage_days < 7 or not sufficient_data:
            wasted_spend_estimate = 0.0
        else:
            wasted_spend_estimate = total_cost * (1.0 - composite_score)
            wasted_spend_estimate = max(0.0, wasted_spend_estimate)

        # STEP 9 – EFFECTIVE COST RATIO
        effective_cost_ratio = composite_score / total_cost if total_cost > 0.0 else 0.0

        rows.append(
            {
                "instance_id": iid,
                "compute_cost": compute_cost,
                "attached_storage_cost": storage_cost,
                "network_egress_cost": network_egress_cost,
                "total_cost": total_cost,
                "daily_cost_avg": daily_cost_avg,
                "daily_cost_stddev": daily_cost_stddev,
                "cost_per_vcpu_hour": cost_per_vcpu_hour,
                "cost_per_gb_ram_hour": cost_per_gb_ram_hour,
                "effective_cost_ratio": effective_cost_ratio,
                "wasted_spend_estimate": wasted_spend_estimate,
                "no_billing_data": no_billing_data,
            }
        )

    cost_attribution_df = pd.DataFrame(rows) if rows else _empty_cost_attribution_df()

    log.info(
        "attribute_costs_complete",
        n_attributed=len(cost_attribution_df),
        total_cost=round(cost_attribution_df["total_cost"].sum(), 4) if not cost_attribution_df.empty else 0.0,
        wasted_spend=round(cost_attribution_df["wasted_spend_estimate"].sum(), 4) if not cost_attribution_df.empty else 0.0,
    )

    return CostMapperResult(
        cost_attribution_df=cost_attribution_df,
        orphaned_costs_df=orphaned_costs_df,
        fleet_overhead_cost=fleet_overhead_cost,
        orphaned_cost_total=orphaned_cost_total,
        object_storage_cost_map=object_storage_cost_map,
    )


# ---------------------------------------------------------------------------
# Empty DataFrame constructors
# ---------------------------------------------------------------------------

def _empty_cost_attribution_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "instance_id",
            "compute_cost",
            "attached_storage_cost",
            "network_egress_cost",
            "total_cost",
            "daily_cost_avg",
            "daily_cost_stddev",
            "cost_per_vcpu_hour",
            "cost_per_gb_ram_hour",
            "effective_cost_ratio",
            "wasted_spend_estimate",
            "no_billing_data",
        ]
    )


def _empty_costs_subset(costs_df: pd.DataFrame) -> pd.DataFrame:
    """Return an empty DataFrame with the same columns as costs_df."""
    return pd.DataFrame(columns=costs_df.columns.tolist())
