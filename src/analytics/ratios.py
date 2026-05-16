"""
src/analytics/ratios.py
=======================
OCI Cost Optimisation Analytics – fleet KPI aggregation engine.

Aggregates per-instance cost and utilization data into a single FleetKPIs
summary for dashboards, reports, and trend alerting.

Public API
----------
compute_fleet_kpis(instances_df, utilization_df, cost_attribution_df,
                   recommendations, collection_period_days,
                   orphaned_cost_total, previous_run_path) -> FleetKPIs
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.analytics.right_sizer import Recommendation, RecommendationType
from src.analytics.utilization import UtilizationPattern
from src.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIGRATION_TOIL_PER_INSTANCE: float = 50.0  # dollars per instance resize

# Composite score thresholds
_OVER_PROVISION_THRESHOLD: float = 0.30
_RIGHT_SIZED_THRESHOLD: float = 0.70

# Actionable recommendation types that incur migration toil
_ACTIONABLE_TYPES = frozenset({RecommendationType.DOWNSIZE, RecommendationType.TERMINATE})

# Savings-contributing recommendation types
_SAVINGS_TYPES = frozenset({RecommendationType.DOWNSIZE, RecommendationType.TERMINATE})


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class FleetKPIs:
    # Financial
    total_fleet_cost_period: float
    total_fleet_cost_monthly_run_rate: float
    orphaned_resource_cost: float
    total_potential_monthly_savings: float
    savings_opportunity_pct: float
    net_recoverable_savings: float           # potential savings minus migration toil
    # Utilization
    fleet_avg_cpu_utilization: float         # cost-weighted mean of cpu_p95
    fleet_avg_memory_utilization: Optional[float]   # None if no memory data at all
    weighted_composite_score: float          # cost-weighted composite
    # Distribution
    overprovisioned_count: int               # composite < 0.30, not IDLE, sufficient_data
    rightsized_count: int                    # 0.30 <= composite < 0.70, sufficient_data
    underprovisioned_count: int              # composite >= 0.70 OR cpu_p99 > 90, sufficient_data
    idle_count: int                          # pattern == IDLE
    insufficient_data_count: int
    # Efficiency
    cost_efficiency_index: float             # sum(score*cost)/sum(cost)
    top_5_wasteful: list[dict]               # by wasted_spend_estimate desc
    top_5_efficient: list[dict]              # by effective_cost_ratio desc
    # Trend
    fleet_cost_trend_pct: Optional[float]
    utilization_trend_pct: Optional[float]
    trend_unavailable_reason: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_weighted_average(
    values: pd.Series,
    weights: pd.Series,
) -> float:
    """
    Cost-weighted mean of *values*.
    Falls back to simple mean if all weights are zero.
    Returns 0.0 for empty or all-NaN input.
    """
    mask = values.notna() & weights.notna()
    v = values[mask].astype(float)
    w = weights[mask].astype(float)

    if v.empty:
        return 0.0

    total_w = float(w.sum())
    if total_w == 0.0:
        # All costs zero — use simple mean
        return float(v.mean()) if not v.empty else 0.0

    return float(np.average(v, weights=w))


def _load_previous_run(path: Path) -> Optional[dict]:
    """
    Attempt to load a previous analytics JSON snapshot.
    Returns the parsed dict or None on any failure.
    """
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except Exception as exc:
        log.warning("previous_run_load_failed", path=str(path), error=str(exc))
        return None


def _compute_trend_pct(current: float, previous: float) -> Optional[float]:
    """
    Percentage change from previous to current.
    Returns None if previous is zero (avoids division by zero).
    """
    if previous == 0.0:
        return None
    return (current - previous) / abs(previous) * 100.0


def _build_empty_kpis() -> FleetKPIs:
    """Return a zeroed-out FleetKPIs for an empty fleet."""
    return FleetKPIs(
        total_fleet_cost_period=0.0,
        total_fleet_cost_monthly_run_rate=0.0,
        orphaned_resource_cost=0.0,
        total_potential_monthly_savings=0.0,
        savings_opportunity_pct=0.0,
        net_recoverable_savings=0.0,
        fleet_avg_cpu_utilization=0.0,
        fleet_avg_memory_utilization=None,
        weighted_composite_score=0.0,
        overprovisioned_count=0,
        rightsized_count=0,
        underprovisioned_count=0,
        idle_count=0,
        insufficient_data_count=0,
        cost_efficiency_index=0.0,
        top_5_wasteful=[],
        top_5_efficient=[],
        fleet_cost_trend_pct=None,
        utilization_trend_pct=None,
        trend_unavailable_reason="Previous run not available — trend metrics suppressed",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_fleet_kpis(
    instances_df: pd.DataFrame,
    utilization_df: pd.DataFrame,
    cost_attribution_df: pd.DataFrame,
    recommendations: list[Recommendation],
    collection_period_days: int = 15,
    orphaned_cost_total: float = 0.0,
    previous_run_path: Optional[Path] = None,
) -> FleetKPIs:
    """
    Aggregate per-instance cost and utilization data into fleet-level KPIs.

    Parameters
    ----------
    instances_df:
        One row per compute instance.
    utilization_df:
        Per-instance utilization summary.
    cost_attribution_df:
        Output of cost_mapper.attribute_costs.
    recommendations:
        Output of right_sizer.generate_recommendations.
    collection_period_days:
        Length of the analysis window (default 15 days).
    orphaned_cost_total:
        Total cost of orphaned billing records (from CostMapperResult).
    previous_run_path:
        Optional path to a previous analytics JSON for trend comparison.

    Returns
    -------
    FleetKPIs
    """
    log.info(
        "compute_fleet_kpis_start",
        n_instances=len(instances_df),
        n_recommendations=len(recommendations),
        collection_period_days=collection_period_days,
    )

    # Guard: empty fleet
    if instances_df.empty:
        log.warning("compute_fleet_kpis_empty_fleet")
        return _build_empty_kpis()

    # -----------------------------------------------------------------------
    # Merge instances + utilization + cost_attribution (left join from instances)
    # -----------------------------------------------------------------------
    merged = instances_df.merge(utilization_df, on="instance_id", how="left", suffixes=("", "_util"))
    merged = merged.merge(cost_attribution_df, on="instance_id", how="left", suffixes=("", "_cost"))

    # Fill missing numeric columns with safe defaults
    for col in ("composite_score", "total_cost", "wasted_spend_estimate", "effective_cost_ratio"):
        if col not in merged.columns:
            merged[col] = 0.0
        else:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)

    for col in ("cpu_p95", "cpu_p99", "memory_p95"):
        if col not in merged.columns:
            merged[col] = float("nan")
        else:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")

    if "sufficient_data" not in merged.columns:
        merged["sufficient_data"] = False
    else:
        merged["sufficient_data"] = merged["sufficient_data"].fillna(False).astype(bool)

    if "has_memory_data" not in merged.columns:
        merged["has_memory_data"] = False
    else:
        merged["has_memory_data"] = merged["has_memory_data"].fillna(False).astype(bool)

    if "pattern" not in merged.columns:
        merged["pattern"] = ""
    else:
        merged["pattern"] = merged["pattern"].fillna("").astype(str)

    if "no_billing_data" not in merged.columns:
        merged["no_billing_data"] = True
    else:
        merged["no_billing_data"] = merged["no_billing_data"].fillna(True).astype(bool)

    if "display_name" not in merged.columns:
        merged["display_name"] = merged["instance_id"]
    else:
        merged["display_name"] = merged["display_name"].fillna(merged["instance_id"])

    # -----------------------------------------------------------------------
    # FINANCIAL KPIs
    # -----------------------------------------------------------------------
    total_fleet_cost_period = float(merged["total_cost"].sum())

    monthly_run_rate = (
        total_fleet_cost_period * 30.0 / collection_period_days
        if collection_period_days > 0
        else 0.0
    )

    # Potential savings from DOWNSIZE and TERMINATE recommendations
    total_potential_monthly_savings = sum(
        rec.estimated_monthly_savings
        for rec in recommendations
        if rec.recommendation_type in _SAVINGS_TYPES
        and rec.estimated_monthly_savings > 0.0
    )

    savings_opportunity_pct = (
        total_potential_monthly_savings / monthly_run_rate * 100.0
        if monthly_run_rate > 0.0
        else 0.0
    )

    # Net recoverable = savings minus migration toil for each actionable recommendation
    actionable_count = sum(
        1 for rec in recommendations if rec.recommendation_type in _ACTIONABLE_TYPES
    )
    net_recoverable_savings = total_potential_monthly_savings - (
        actionable_count * MIGRATION_TOIL_PER_INSTANCE
    )

    log.debug(
        "fleet_financial",
        total_cost_period=round(total_fleet_cost_period, 2),
        monthly_run_rate=round(monthly_run_rate, 2),
        potential_savings=round(total_potential_monthly_savings, 2),
        net_recoverable=round(net_recoverable_savings, 2),
    )

    # -----------------------------------------------------------------------
    # UTILIZATION KPIs (cost-weighted)
    # -----------------------------------------------------------------------
    cpu_series = merged["cpu_p95"]
    cost_series = merged["total_cost"]

    fleet_avg_cpu_utilization = _safe_weighted_average(cpu_series, cost_series)

    # Memory: only instances with has_memory_data=True
    mem_instances = merged[merged["has_memory_data"] == True]
    if mem_instances.empty:
        fleet_avg_memory_utilization: Optional[float] = None
    else:
        fleet_avg_memory_utilization = _safe_weighted_average(
            mem_instances["memory_p95"],
            mem_instances["total_cost"],
        )

    weighted_composite_score = _safe_weighted_average(
        merged["composite_score"],
        cost_series,
    )

    # -----------------------------------------------------------------------
    # DISTRIBUTION COUNTS
    # -----------------------------------------------------------------------
    sufficient = merged["sufficient_data"] == True
    idle_pattern = merged["pattern"] == UtilizationPattern.IDLE.value
    composite = merged["composite_score"]
    cpu_p99_series = merged["cpu_p99"] if "cpu_p99" in merged.columns else pd.Series(
        [float("nan")] * len(merged)
    )

    # Overprovisioned: composite < 0.30, not IDLE, sufficient_data=True
    overprovisioned_mask = (
        sufficient
        & ~idle_pattern
        & (composite < _OVER_PROVISION_THRESHOLD)
    )
    overprovisioned_count = int(overprovisioned_mask.sum())

    # Right-sized: 0.30 <= composite < 0.70, sufficient_data=True
    rightsized_mask = (
        sufficient
        & (composite >= _OVER_PROVISION_THRESHOLD)
        & (composite < _RIGHT_SIZED_THRESHOLD)
    )
    rightsized_count = int(rightsized_mask.sum())

    # Underprovisioned: (composite >= 0.70 OR cpu_p99 > 90), sufficient_data=True
    over_composite = composite >= _RIGHT_SIZED_THRESHOLD
    high_cpu_p99 = cpu_p99_series.fillna(0.0) > 90.0
    underprovisioned_mask = sufficient & (over_composite | high_cpu_p99)
    underprovisioned_count = int(underprovisioned_mask.sum())

    # Idle: pattern == IDLE (regardless of sufficient_data)
    idle_count = int(idle_pattern.sum())

    # Insufficient data
    insufficient_data_count = int((~sufficient).sum())

    log.debug(
        "fleet_distribution",
        overprovisioned=overprovisioned_count,
        rightsized=rightsized_count,
        underprovisioned=underprovisioned_count,
        idle=idle_count,
        insufficient_data=insufficient_data_count,
    )

    # -----------------------------------------------------------------------
    # EFFICIENCY KPIs
    # -----------------------------------------------------------------------
    total_cost_sum = float(merged["total_cost"].sum())
    weighted_score_sum = float((merged["composite_score"] * merged["total_cost"]).sum())

    cost_efficiency_index = (
        weighted_score_sum / total_cost_sum
        if total_cost_sum > 0.0
        else 0.0
    )

    # Top-5 wasteful instances (by wasted_spend_estimate desc)
    wasteful_sorted = merged.nlargest(5, "wasted_spend_estimate")
    top_5_wasteful: list[dict] = []
    for _, wrow in wasteful_sorted.iterrows():
        top_5_wasteful.append(
            {
                "instance_id": str(wrow.get("instance_id", "")),
                "display_name": str(wrow.get("display_name", "")),
                "wasted_spend": float(wrow.get("wasted_spend_estimate", 0.0)),
                "composite_score": float(wrow.get("composite_score", 0.0)),
                "total_cost": float(wrow.get("total_cost", 0.0)),
            }
        )

    # Top-5 efficient instances (by effective_cost_ratio desc, exclude no_billing_data)
    billable = merged[merged["no_billing_data"] == False]
    if billable.empty:
        top_5_efficient: list[dict] = []
    else:
        efficient_sorted = billable.nlargest(5, "effective_cost_ratio")
        top_5_efficient = []
        for _, erow in efficient_sorted.iterrows():
            top_5_efficient.append(
                {
                    "instance_id": str(erow.get("instance_id", "")),
                    "display_name": str(erow.get("display_name", "")),
                    "effective_cost_ratio": float(erow.get("effective_cost_ratio", 0.0)),
                    "composite_score": float(erow.get("composite_score", 0.0)),
                    "total_cost": float(erow.get("total_cost", 0.0)),
                }
            )

    # -----------------------------------------------------------------------
    # TREND METRICS
    # -----------------------------------------------------------------------
    fleet_cost_trend_pct: Optional[float] = None
    utilization_trend_pct: Optional[float] = None
    trend_unavailable_reason: Optional[str] = None

    if previous_run_path is None:
        trend_unavailable_reason = "Previous run not available — trend metrics suppressed"
    else:
        prev_path = Path(previous_run_path)
        if not prev_path.exists():
            trend_unavailable_reason = "Previous run not available — trend metrics suppressed"
        else:
            prev_data = _load_previous_run(prev_path)
            if prev_data is None:
                trend_unavailable_reason = (
                    f"Previous run at {prev_path} could not be loaded — trend metrics suppressed"
                )
            else:
                try:
                    prev_cost = float(
                        prev_data.get("fleet_kpis", {}).get(
                            "total_fleet_cost_monthly_run_rate", 0.0
                        )
                        or 0.0
                    )
                    prev_util = prev_data.get("fleet_kpis", {}).get(
                        "fleet_avg_cpu_utilization"
                    )

                    fleet_cost_trend_pct = _compute_trend_pct(monthly_run_rate, prev_cost)
                    if fleet_cost_trend_pct is None:
                        trend_unavailable_reason = (
                            "Previous run monthly cost was 0 — cost trend percentage undefined"
                        )

                    if prev_util is not None:
                        try:
                            prev_util_f = float(prev_util)
                            utilization_trend_pct = _compute_trend_pct(
                                fleet_avg_cpu_utilization, prev_util_f
                            )
                        except (TypeError, ValueError):
                            utilization_trend_pct = None
                except Exception as exc:
                    log.warning(
                        "trend_computation_failed",
                        path=str(prev_path),
                        error=str(exc),
                    )
                    fleet_cost_trend_pct = None
                    utilization_trend_pct = None
                    trend_unavailable_reason = (
                        f"Trend computation failed ({exc}) — trend metrics suppressed"
                    )

    log.info(
        "compute_fleet_kpis_complete",
        total_cost_period=round(total_fleet_cost_period, 2),
        monthly_run_rate=round(monthly_run_rate, 2),
        cost_efficiency_index=round(cost_efficiency_index, 4),
        fleet_avg_cpu=round(fleet_avg_cpu_utilization, 2),
        overprovisioned=overprovisioned_count,
        idle=idle_count,
        insufficient_data=insufficient_data_count,
    )

    return FleetKPIs(
        total_fleet_cost_period=total_fleet_cost_period,
        total_fleet_cost_monthly_run_rate=monthly_run_rate,
        orphaned_resource_cost=orphaned_cost_total,
        total_potential_monthly_savings=total_potential_monthly_savings,
        savings_opportunity_pct=savings_opportunity_pct,
        net_recoverable_savings=net_recoverable_savings,
        fleet_avg_cpu_utilization=fleet_avg_cpu_utilization,
        fleet_avg_memory_utilization=fleet_avg_memory_utilization,
        weighted_composite_score=weighted_composite_score,
        overprovisioned_count=overprovisioned_count,
        rightsized_count=rightsized_count,
        underprovisioned_count=underprovisioned_count,
        idle_count=idle_count,
        insufficient_data_count=insufficient_data_count,
        cost_efficiency_index=cost_efficiency_index,
        top_5_wasteful=top_5_wasteful,
        top_5_efficient=top_5_efficient,
        fleet_cost_trend_pct=fleet_cost_trend_pct,
        utilization_trend_pct=utilization_trend_pct,
        trend_unavailable_reason=trend_unavailable_reason,
    )
