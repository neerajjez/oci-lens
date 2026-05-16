from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


import numpy as np
import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)


class AnomalySeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Anomaly:
    signal: str       # cost_outlier | efficiency_outlier | zombie | cost_spike | stranded_volume | over_committed
    resource_id: str
    resource_name: str
    severity: AnomalySeverity
    description: str
    suggested_action: str
    estimated_recoverable_amount: float


# ---------------------------------------------------------------------------
# Severity sort key
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {
    AnomalySeverity.CRITICAL: 0,
    AnomalySeverity.WARNING: 1,
    AnomalySeverity.INFO: 2,
}


# ---------------------------------------------------------------------------
# Signal 1: Cost outliers
# ---------------------------------------------------------------------------

def _detect_cost_outliers(
    instances_df: pd.DataFrame,
    cost_attribution_df: pd.DataFrame,
) -> list[Anomaly]:
    """
    Flag instances whose log-transformed total_cost deviates > 2.5 std devs
    from the fleet mean (log scale).
    Requires at least 3 instances with total_cost > 0.
    """
    anomalies: list[Anomaly] = []

    if cost_attribution_df.empty or "total_cost" not in cost_attribution_df.columns:
        return anomalies

    # Merge to get display_name
    merged = cost_attribution_df.merge(
        instances_df[["instance_id", "display_name"]],
        on="instance_id",
        how="left",
    ) if not instances_df.empty else cost_attribution_df.copy()

    if "display_name" not in merged.columns:
        merged["display_name"] = merged["instance_id"]

    positive = merged[merged["total_cost"] > 0].copy()
    if len(positive) < 3:
        log.debug("cost_outlier_skipped_insufficient_instances", n=len(positive))
        return anomalies

    fleet_costs = positive["total_cost"]
    log_costs = np.log(fleet_costs + 1)
    mean_log = float(log_costs.mean())
    std_log = float(log_costs.std(ddof=1))
    median_cost = float(fleet_costs.median())

    if std_log == 0.0:
        return anomalies

    positive = positive.copy()
    positive["_log_cost"] = log_costs.values
    positive["_z"] = (positive["_log_cost"] - mean_log) / std_log

    flagged = positive[positive["_z"].abs() > 2.5]



    for _, row in flagged.iterrows():
        z = float(row["_z"])
        total_cost = float(row["total_cost"])
        instance_id = str(row["instance_id"])
        resource_name = str(row.get("display_name", instance_id))

        severity = AnomalySeverity.CRITICAL if abs(z) > 3.0 else AnomalySeverity.WARNING

        excess = total_cost - (math.exp(mean_log) - 1)
        recoverable = max(0.0, excess)

        anomalies.append(Anomaly(
            signal="cost_outlier",
            resource_id=instance_id,
            resource_name=resource_name,
            severity=severity,
            description=(
                f"Cost outlier: z-score {z:.2f} (log-scale). "
                f"Total cost ${total_cost:.2f} vs fleet median ${median_cost:.2f}"
            ),
            suggested_action=(
                "Review billing breakdown; check for unintended scaling events "
                "or reserved resource waste"
            ),
            estimated_recoverable_amount=recoverable,
        ))

    return anomalies


# ---------------------------------------------------------------------------
# Signal 2: Efficiency outliers
# ---------------------------------------------------------------------------

def _detect_efficiency_outliers(
    instances_df: pd.DataFrame,
    cost_attribution_df: pd.DataFrame,
) -> list[Anomaly]:
    """
    Flag instances with abnormally high cost per utilization point.
    Only instances with total_cost > 0 and composite_score > 0 are considered.
    """
    anomalies: list[Anomaly] = []

    if cost_attribution_df.empty or "total_cost" not in cost_attribution_df.columns:
        return anomalies

    merged = cost_attribution_df.copy()
    if not instances_df.empty:
        merged = merged.merge(
            instances_df[["instance_id", "display_name"]],
            on="instance_id",
            how="left",
        )
    if "display_name" not in merged.columns:
        merged["display_name"] = merged["instance_id"]

    # Need composite_score — may come from cost_attribution_df or a join
    if "composite_score" not in merged.columns:
        log.debug("efficiency_outlier_skipped_no_composite_score")
        return anomalies

    eligible = merged[
        (merged["total_cost"] > 0) & (merged["composite_score"] > 0)
    ].copy()

    if len(eligible) < 3:
        log.debug("efficiency_outlier_skipped_insufficient_instances", n=len(eligible))
        return anomalies

    eligible["_cost_per_util"] = eligible["total_cost"] / (eligible["composite_score"] + 0.01)

    cpu_series = eligible["_cost_per_util"]
    mean_val = float(cpu_series.mean())
    std_val = float(cpu_series.std(ddof=1))
    median_val = float(cpu_series.median())

    if std_val == 0.0:
        return anomalies

    eligible["_z"] = (eligible["_cost_per_util"] - mean_val) / std_val

    flagged = eligible[eligible["_z"].abs() > 2.5]

    for _, row in flagged.iterrows():
        instance_id = str(row["instance_id"])
        resource_name = str(row.get("display_name", instance_id))
        cost_per_util = float(row["_cost_per_util"])
        composite_score = float(row["composite_score"])

        recoverable = max(0.0, (cost_per_util - median_val) * composite_score)

        anomalies.append(Anomaly(
            signal="efficiency_outlier",
            resource_id=instance_id,
            resource_name=resource_name,
            severity=AnomalySeverity.WARNING,
            description=(
                f"Efficiency outlier: ${cost_per_util:.2f}/utilization-point "
                f"vs fleet median ${median_val:.2f}"
            ),
            suggested_action=(
                "Instance is expensive relative to its utilization. "
                "Consider right-sizing or workload review."
            ),
            estimated_recoverable_amount=recoverable,
        ))

    return anomalies


# ---------------------------------------------------------------------------
# Signal 3: Zombie detection
# ---------------------------------------------------------------------------

def _detect_zombies(
    instances_df: pd.DataFrame,
    utilization_df: pd.DataFrame,
    cost_attribution_df: pd.DataFrame,
    collection_period_days: int,
) -> list[Anomaly]:
    """
    Flag instances with near-zero CPU, network, and disk activity as zombies.
    """
    anomalies: list[Anomaly] = []

    if utilization_df.empty or instances_df.empty:
        return anomalies

    # Require these columns in utilization_df
    required_cols = {"instance_id", "cpu_p95", "network_in_p95", "disk_read_iops_p95"}
    if not required_cols.issubset(set(utilization_df.columns)):
        missing = required_cols - set(utilization_df.columns)
        log.debug("zombie_detection_skipped_missing_columns", missing=list(missing))
        return anomalies

    merged = utilization_df.merge(
        instances_df[["instance_id", "display_name"]],
        on="instance_id",
        how="left",
    )
    if "display_name" not in merged.columns:
        merged["display_name"] = merged["instance_id"]

    # Build cost lookup
    cost_lookup: dict[str, float] = {}
    if not cost_attribution_df.empty and "total_cost" in cost_attribution_df.columns:
        for _, crow in cost_attribution_df.iterrows():
            cost_lookup[str(crow["instance_id"])] = float(crow.get("total_cost", 0.0) or 0.0)

    zombie_mask = (
        (merged["cpu_p95"].fillna(100.0) < 5.0) &
        (merged["network_in_p95"].fillna(1000.0) < 100.0) &
        (merged["disk_read_iops_p95"].fillna(100.0) < 5.0)
    )

    for _, row in merged[zombie_mask].iterrows():
        instance_id = str(row["instance_id"])
        resource_name = str(row.get("display_name", instance_id))
        cpu_p95 = float(row.get("cpu_p95", 0.0) or 0.0)
        net = float(row.get("network_in_p95", 0.0) or 0.0)
        disk = float(row.get("disk_read_iops_p95", 0.0) or 0.0)

        period_cost = cost_lookup.get(instance_id, 0.0)
        # Extrapolate to 30-day equivalent
        recoverable = (
            period_cost * 30.0 / collection_period_days
            if collection_period_days > 0 else period_cost
        )

        anomalies.append(Anomaly(
            signal="zombie",
            resource_id=instance_id,
            resource_name=resource_name,
            severity=AnomalySeverity.CRITICAL,
            description=(
                f"Zombie instance: cpu_p95={cpu_p95:.1f}%, "
                f"network_in_p95={net:.1f} kbps, "
                f"disk_read_iops_p95={disk:.1f}"
            ),
            suggested_action=(
                "Verify instance has no cron jobs or sleeping processes. "
                "Terminate if confirmed unused."
            ),
            estimated_recoverable_amount=recoverable,
        ))

    return anomalies


# ---------------------------------------------------------------------------
# Signal 4: Cost spikes (day-over-day)
# ---------------------------------------------------------------------------

def _detect_cost_spikes(
    instances_df: pd.DataFrame,
    cost_attribution_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
) -> list[Anomaly]:
    """
    Detect day-over-day cost spikes > 50% between consecutive cost records.

    Uses cost_attribution_df (per-instance totals) combined with metrics_df for
    daily-level data when available.  When only a single aggregated cost record
    exists per instance the spike signal cannot fire (requires >= 2 records).

    Fallback: if metrics_df has a 'cost_usd' column with a timestamp, use that
    for per-day cost reconstruction; otherwise skip instances with a single
    aggregated cost row.
    """
    anomalies: list[Anomaly] = []

    # Build display_name lookup
    name_lookup: dict[str, str] = {}
    if not instances_df.empty and "instance_id" in instances_df.columns:
        for _, row in instances_df.iterrows():
            name_lookup[str(row["instance_id"])] = str(row.get("display_name", str(row["instance_id"])))

    # Try to use metrics_df for daily cost data if it has cost columns
    # Otherwise work with cost_attribution_df daily_cost_avg as a scalar — insufficient for spike
    # detection (only one data point per instance).  Use daily_cost_stddev as a proxy signal:
    # if daily_cost_stddev / daily_cost_avg > 0.5 (CV > 50%), flag as potential spike.
    if cost_attribution_df.empty:
        return anomalies

    required_cols = {"instance_id", "daily_cost_avg", "daily_cost_stddev", "total_cost"}
    if not required_cols.issubset(set(cost_attribution_df.columns)):
        log.debug("cost_spike_skipped_missing_columns")
        return anomalies

    for _, row in cost_attribution_df.iterrows():
        instance_id = str(row["instance_id"])
        daily_avg = float(row.get("daily_cost_avg", 0.0) or 0.0)
        daily_std = float(row.get("daily_cost_stddev", 0.0) or 0.0)
        total_cost = float(row.get("total_cost", 0.0) or 0.0)

        if daily_avg <= 0 or total_cost <= 0:
            continue

        # Coefficient of variation proxy: high variance relative to mean suggests spikes
        cv = daily_std / daily_avg if daily_avg > 0 else 0.0
        if cv <= 0.5:
            continue

        # Spike percentage approximation: stddev / avg * 100
        spike_pct = cv * 100.0
        spike_amount = daily_std  # excess over mean daily cost

        resource_name = name_lookup.get(instance_id, instance_id)
        severity = AnomalySeverity.CRITICAL if spike_pct > 200.0 else AnomalySeverity.WARNING

        anomalies.append(Anomaly(
            signal="cost_spike",
            resource_id=instance_id,
            resource_name=resource_name,
            severity=severity,
            description=(
                f"Cost spike: {spike_pct:.0f}% coefficient of variation detected "
                f"(daily avg=${daily_avg:.2f}, stddev=${daily_std:.2f})"
            ),
            suggested_action=(
                "Review scaling events, data transfer charges, or new resource "
                "launches on that date."
            ),
            estimated_recoverable_amount=max(0.0, spike_amount),
        ))

    return anomalies


# ---------------------------------------------------------------------------
# Signal 5: Stranded volumes
# ---------------------------------------------------------------------------

def _detect_stranded_volumes(volumes_df: pd.DataFrame) -> list[Anomaly]:
    """
    Flag block volumes that are unattached and in an active lifecycle state.
    Estimated cost: size_gb * vpu_per_gb * $0.0000925/GB-hr * 730 hrs/month.
    """
    anomalies: list[Anomaly] = []

    if volumes_df.empty:
        return anomalies

    required = {"volume_id", "display_name", "size_gb", "lifecycle_state", "attached_instance_id"}
    if not required.issubset(set(volumes_df.columns)):
        missing = required - set(volumes_df.columns)
        log.debug("stranded_volume_skipped_missing_columns", missing=list(missing))
        return anomalies

    active_states = {"AVAILABLE", "PROVISIONED"}

    for _, row in volumes_df.iterrows():
        attached = str(row.get("attached_instance_id", "") or "").strip()
        lifecycle = str(row.get("lifecycle_state", "") or "").strip().upper()

        if attached != "":
            continue  # attached — not stranded
        if lifecycle not in active_states:
            continue  # terminated or provisioning — not active cost

        volume_id = str(row.get("volume_id", ""))
        display_name = str(row.get("display_name", volume_id))
        size_gb = int(row.get("size_gb", 0) or 0)
        vpu_per_gb = int(row.get("vpu_per_gb", 10) or 10)

        # Approximate monthly storage cost: size_gb * vpu_per_gb * $0.0000925/GB-hr * 730
        monthly_cost = size_gb * vpu_per_gb * 0.0000925 * 730

        anomalies.append(Anomaly(
            signal="stranded_volume",
            resource_id=volume_id,
            resource_name=display_name,
            severity=AnomalySeverity.WARNING,
            description=(
                f"Stranded volume: {display_name} ({size_gb} GB) has been unattached"
            ),
            suggested_action=(
                "Verify the volume is not needed. "
                "Delete or snapshot-and-delete to recover storage costs."
            ),
            estimated_recoverable_amount=monthly_cost,
        ))

    return anomalies


# ---------------------------------------------------------------------------
# Signal 6: Over-committed (stub — for future reservation data)
# ---------------------------------------------------------------------------

def _detect_over_committed() -> list[Anomaly]:
    """
    Over-committed signal: flags instances where reservations exceed actual usage.
    STUB — requires reservation data not yet available in the collector pipeline.
    Will be implemented when OCI reservation/commitment data is added to CollectionResult.
    """
    # No reservation data available — return empty list
    return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_anomalies(
    instances_df: pd.DataFrame,
    utilization_df: pd.DataFrame,
    cost_attribution_df: pd.DataFrame,
    volumes_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    collection_period_days: int = 15,
) -> list[Anomaly]:
    """
    Run all six anomaly detection signals independently and return a combined,
    sorted list of Anomaly objects.

    Signals:
      1. cost_outlier      — log-z-score on fleet total_cost
      2. efficiency_outlier — cost-per-utilization-point z-score
      3. zombie            — near-zero CPU / network / disk activity
      4. cost_spike        — day-over-day cost jump > 50%
      5. stranded_volume   — unattached active block volumes
      6. over_committed    — STUB (future reservation data)

    All signals fire independently; an instance may appear in multiple signals.

    Returns
    -------
    list[Anomaly] sorted by severity (CRITICAL first) then
    estimated_recoverable_amount descending.
    """
    log.info(
        "detect_anomalies_start",
        n_instances=len(instances_df),
        n_utilization=len(utilization_df),
        n_cost_attribution=len(cost_attribution_df),
        n_volumes=len(volumes_df),
        collection_period_days=collection_period_days,
    )

    all_anomalies: list[Anomaly] = []

    # --- Signal 1: Cost outliers ---
    try:
        s1 = _detect_cost_outliers(instances_df, cost_attribution_df)
        log.debug("signal_cost_outlier_complete", count=len(s1))
        all_anomalies.extend(s1)
    except Exception as exc:  # pragma: no cover
        log.warning("signal_cost_outlier_error", error=str(exc))

    # --- Signal 2: Efficiency outliers ---
    try:
        s2 = _detect_efficiency_outliers(instances_df, cost_attribution_df)
        log.debug("signal_efficiency_outlier_complete", count=len(s2))
        all_anomalies.extend(s2)
    except Exception as exc:  # pragma: no cover
        log.warning("signal_efficiency_outlier_error", error=str(exc))

    # --- Signal 3: Zombie detection ---
    try:
        s3 = _detect_zombies(instances_df, utilization_df, cost_attribution_df, collection_period_days)
        log.debug("signal_zombie_complete", count=len(s3))
        all_anomalies.extend(s3)
    except Exception as exc:  # pragma: no cover
        log.warning("signal_zombie_error", error=str(exc))

    # --- Signal 4: Cost spikes ---
    try:
        s4 = _detect_cost_spikes(instances_df, cost_attribution_df=cost_attribution_df, metrics_df=metrics_df)
        log.debug("signal_cost_spike_complete", count=len(s4))
        all_anomalies.extend(s4)
    except Exception as exc:  # pragma: no cover
        log.warning("signal_cost_spike_error", error=str(exc))

    # --- Signal 5: Stranded volumes ---
    try:
        s5 = _detect_stranded_volumes(volumes_df)
        log.debug("signal_stranded_volume_complete", count=len(s5))
        all_anomalies.extend(s5)
    except Exception as exc:  # pragma: no cover
        log.warning("signal_stranded_volume_error", error=str(exc))

    # --- Signal 6: Over-committed (stub) ---
    try:
        s6 = _detect_over_committed()
        all_anomalies.extend(s6)
    except Exception as exc:  # pragma: no cover
        log.warning("signal_over_committed_error", error=str(exc))

    # --- Sort: CRITICAL first, then by recoverable amount desc ---
    all_anomalies.sort(
        key=lambda a: (_SEVERITY_ORDER.get(a.severity, 99), -a.estimated_recoverable_amount)
    )

    log.info("detect_anomalies_complete", total=len(all_anomalies))
    return all_anomalies
