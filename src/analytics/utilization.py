from __future__ import annotations

import math
import warnings
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

log = get_logger(__name__)


# ─── Pattern enum ────────────────────────────────────────────────────────────

class UtilizationPattern(str, Enum):
    STEADY      = "STEADY"
    BURSTY      = "BURSTY"
    CYCLICAL    = "CYCLICAL"
    WEEKLY      = "WEEKLY"
    TRENDING_UP = "TRENDING_UP"
    IDLE        = "IDLE"
    ERRATIC     = "ERRATIC"


# ─── Sigmoid scoring ─────────────────────────────────────────────────────────

def sigmoid_score(value: float, target: float) -> float:
    """
    Sigmoid-weighted utilization score in [0.0, 1.0].

    Returns 0.0 at value=0, 1.0 when value==target,
    decays gracefully when value exceeds target.

    Formula
    -------
    - Below target : score = (value / target) ** 0.7   [concave rise]
    - Above target : score = exp(-2.0 * (value / target - 1))  [exponential decay]

    Worked example (cpu_score, target=70%):
      value=  0%  → 0.000  (completely idle)
      value= 35%  → 0.616  (under-utilised)
      value= 70%  → 1.000  (optimal)
      value= 85%  → 0.741  (slightly over-target)
      value=100%  → 0.407  (significantly over-target)
    """
    if target <= 0 or value < 0:
        return 0.0
    if value == 0:
        return 0.0
    ratio = value / target
    if ratio <= 1.0:
        return ratio ** 0.7
    return math.exp(-2.0 * (ratio - 1.0))


# ─── Autocorrelation helper ───────────────────────────────────────────────────

def autocorr_at_lag(series: np.ndarray, lag: int) -> float:
    """Pearson autocorrelation at given lag. Returns 0.0 on failure."""
    clean = series[~np.isnan(series)]
    if len(clean) <= lag + 1:
        return 0.0
    x = clean[:-lag]
    y = clean[lag:]
    if np.std(x) < 1e-9 or np.std(y) < 1e-9:
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        corr = np.corrcoef(x, y)[0, 1]
    return float(corr) if not math.isnan(corr) else 0.0


# ─── Distribution computation ────────────────────────────────────────────────

def _safe_percentile(arr: np.ndarray, pct: float) -> float:
    """Return np.nanpercentile for *pct*; 0.0 if array is empty or all-NaN."""
    if arr is None or len(arr) == 0:
        return 0.0
    valid = arr[~np.isnan(arr)]
    if len(valid) == 0:
        return 0.0
    return float(np.nanpercentile(arr, pct))


def _safe_mean(arr: np.ndarray) -> float:
    """Return np.nanmean; 0.0 if array is empty or all-NaN."""
    if arr is None or len(arr) == 0:
        return 0.0
    valid = arr[~np.isnan(arr)]
    if len(valid) == 0:
        return 0.0
    return float(np.nanmean(arr))


def _compute_distribution(arr: np.ndarray) -> dict[str, float]:
    """
    Compute full percentile distribution for *arr*.

    Returns keys: mean, median (p50), p25, p75, p90, p95, p99, max.
    All values are 0.0 when the array is empty or all-NaN.
    """
    return {
        "mean":   _safe_mean(arr),
        "median": _safe_percentile(arr, 50),
        "p25":    _safe_percentile(arr, 25),
        "p75":    _safe_percentile(arr, 75),
        "p90":    _safe_percentile(arr, 90),
        "p95":    _safe_percentile(arr, 95),
        "p99":    _safe_percentile(arr, 99),
        "max":    _safe_percentile(arr, 100),
    }


# ─── Pattern detection ────────────────────────────────────────────────────────

def _detect_pattern(
    cpu_series: np.ndarray,
    cpu_dist: dict[str, float],
    network_in_p95: float,
    has_timeseries: bool,
) -> UtilizationPattern:
    """
    Detect the utilization pattern for one instance.

    Priority order (timeseries-capable checks first):
    1. IDLE        — cpu_p95 < 5.0 AND network_in_p95 < 1000
    2. WEEKLY      — autocorr at lag 168 > 0.6 (requires >= 336 points)
    3. CYCLICAL    — autocorr at lag 24  > 0.6 (requires >= 48 points)
    4. TRENDING_UP — linear slope > 5.0 per 168-point window (requires >= 48 points)
    5. BURSTY      — cpu_p99 / cpu_median > 3.0
    6. STEADY      — cpu_p95 - cpu_p25 < 15.0
    7. ERRATIC     — fallback

    When *has_timeseries* is False, only IDLE, BURSTY, and STEADY are checked.
    """
    cpu_p95    = cpu_dist["p95"]
    cpu_p25    = cpu_dist["p25"]
    cpu_p99    = cpu_dist["p99"]
    cpu_median = cpu_dist["median"]

    # 1. IDLE (applies regardless of timeseries availability)
    if cpu_p95 < 5.0 and network_in_p95 < 1000.0:
        return UtilizationPattern.IDLE

    if has_timeseries and cpu_series is not None and len(cpu_series) > 0:
        n = len(cpu_series[~np.isnan(cpu_series)])

        # 2. WEEKLY (7-day autocorrelation)
        if n >= 336:
            if autocorr_at_lag(cpu_series, 168) > 0.6:
                return UtilizationPattern.WEEKLY

        # 3. CYCLICAL (daily autocorrelation)
        if n >= 48:
            if autocorr_at_lag(cpu_series, 24) > 0.6:
                return UtilizationPattern.CYCLICAL

        # 4. TRENDING_UP (linear regression slope check)
        if n >= 48:
            clean = cpu_series[~np.isnan(cpu_series)]
            if len(clean) >= 48:
                x = np.arange(len(clean), dtype=float)
                coeffs = np.polyfit(x, clean, 1)
                slope_per_point = coeffs[0]
                # Convert to per-168-point window
                slope_per_week = slope_per_point * 168.0
                if slope_per_week > 5.0:
                    return UtilizationPattern.TRENDING_UP

    # 5. BURSTY
    if cpu_p99 > 0 and cpu_median > 0 and cpu_p99 / cpu_median > 3.0:
        return UtilizationPattern.BURSTY

    # 6. STEADY
    if cpu_p95 - cpu_p25 < 15.0:
        return UtilizationPattern.STEADY

    # 7. ERRATIC
    return UtilizationPattern.ERRATIC


# ─── IO utilization ──────────────────────────────────────────────────────────

def _compute_io_utilization(disk_read_iops_p95: float, disk_write_iops_p95: float) -> float:
    """
    Compute IO utilisation percentage from p95 IOPS values.

    io_utilization_pct = mean(disk_read_iops_p95, disk_write_iops_p95) / 10000 * 100
    Clamped to [0, 100].
    """
    raw = (disk_read_iops_p95 + disk_write_iops_p95) / 2.0 / 10000.0 * 100.0
    return max(0.0, min(100.0, raw))


# ─── Composite scoring ────────────────────────────────────────────────────────

def _composite_score(
    cpu_p95: float,
    memory_p95: float,
    io_utilization_pct: float,
    has_memory_data: bool,
) -> tuple[float, float, float, float]:
    """
    Compute (cpu_score, memory_score, io_score, composite_score).

    Weights with memory data    : 0.45 cpu + 0.35 memory + 0.20 io
    Weights without memory data : 0.65 cpu + 0.00 memory + 0.35 io
    """
    cpu_score = sigmoid_score(cpu_p95, target=70.0)
    io_score  = sigmoid_score(io_utilization_pct, target=60.0)

    if has_memory_data:
        memory_score = sigmoid_score(memory_p95, target=70.0)
        composite = 0.45 * cpu_score + 0.35 * memory_score + 0.20 * io_score
    else:
        memory_score = 0.0
        composite = 0.65 * cpu_score + 0.35 * io_score

    return cpu_score, memory_score, io_score, composite


# ─── Per-instance row builders ────────────────────────────────────────────────

def _build_row_from_timeseries(
    instance_id: str,
    ts: pd.DataFrame,
) -> dict:
    """
    Build a result row for an instance that has timeseries data in *ts*.

    Expected columns in *ts* (subset used here):
        cpu_utilization, memory_utilization,
        network_bytes_in, network_bytes_out,
        disk_read_iops, disk_write_iops
    """
    def _col(name: str) -> np.ndarray:
        if name in ts.columns:
            return ts[name].to_numpy(dtype=float, na_value=np.nan)
        return np.array([], dtype=float)

    cpu_arr  = _col("cpu_utilization")
    mem_arr  = _col("memory_utilization")
    net_in   = _col("network_bytes_in")
    net_out  = _col("network_bytes_out")
    dr_iops  = _col("disk_read_iops")
    dw_iops  = _col("disk_write_iops")

    cpu_dist = _compute_distribution(cpu_arr)
    mem_dist = _compute_distribution(mem_arr)

    # Check whether meaningful memory data exists (not all-zero / all-NaN)
    has_memory_data = bool(
        len(mem_arr) > 0
        and not np.all(np.isnan(mem_arr))
        and _safe_percentile(mem_arr, 95) > 0.0
    )

    network_in_p50  = _safe_percentile(net_in,  50)
    network_in_p95  = _safe_percentile(net_in,  95)
    network_out_p50 = _safe_percentile(net_out, 50)
    network_out_p95 = _safe_percentile(net_out, 95)

    disk_read_iops_p95  = _safe_percentile(dr_iops, 95)
    disk_write_iops_p95 = _safe_percentile(dw_iops, 95)

    io_utilization_pct = _compute_io_utilization(disk_read_iops_p95, disk_write_iops_p95)

    pattern = _detect_pattern(
        cpu_series=cpu_arr,
        cpu_dist=cpu_dist,
        network_in_p95=network_in_p95,
        has_timeseries=True,
    )

    cpu_score, memory_score, io_score, composite_score = _composite_score(
        cpu_p95=cpu_dist["p95"],
        memory_p95=mem_dist["p95"],
        io_utilization_pct=io_utilization_pct,
        has_memory_data=has_memory_data,
    )

    return {
        "instance_id":          instance_id,
        # CPU distribution
        "cpu_mean":             cpu_dist["mean"],
        "cpu_median":           cpu_dist["median"],
        "cpu_p25":              cpu_dist["p25"],
        "cpu_p75":              cpu_dist["p75"],
        "cpu_p90":              cpu_dist["p90"],
        "cpu_p95":              cpu_dist["p95"],
        "cpu_p99":              cpu_dist["p99"],
        "cpu_max":              cpu_dist["max"],
        # Memory distribution
        "memory_mean":          mem_dist["mean"],
        "memory_median":        mem_dist["median"],
        "memory_p25":           mem_dist["p25"],
        "memory_p75":           mem_dist["p75"],
        "memory_p90":           mem_dist["p90"],
        "memory_p95":           mem_dist["p95"],
        "memory_p99":           mem_dist["p99"],
        "memory_max":           mem_dist["max"],
        # Network
        "network_in_p50":       network_in_p50,
        "network_in_p95":       network_in_p95,
        "network_out_p50":      network_out_p50,
        "network_out_p95":      network_out_p95,
        # Disk IOPS
        "disk_read_iops_p95":   disk_read_iops_p95,
        "disk_write_iops_p95":  disk_write_iops_p95,
        # Derived
        "io_utilization_pct":   io_utilization_pct,
        "pattern":              pattern.value,
        "cpu_score":            cpu_score,
        "memory_score":         memory_score,
        "io_score":             io_score,
        "composite_score":      composite_score,
        "has_memory_data":      has_memory_data,
        "has_timeseries":       True,
    }


def _build_row_from_aggregates(
    instance_id: str,
    row: pd.Series,
) -> dict:
    """
    Build a result row for an instance that has NO timeseries data.

    Uses aggregated columns from *instances_df*:
        cpu_avg, cpu_p50, cpu_p95, cpu_p99

    Heuristic derivations:
        p25 = (cpu_avg + cpu_p50) / 2
        p75 = (cpu_p50 + cpu_p95) / 2
        p90 = (cpu_p95 + cpu_p99) / 2
    """
    def _get(col: str, default: float = 0.0) -> float:
        val = row.get(col, default)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return default
        return float(val)

    cpu_mean   = _get("cpu_avg")
    cpu_median = _get("cpu_p50")
    cpu_p95    = _get("cpu_p95")
    cpu_p99    = _get("cpu_p99")

    cpu_p25 = (cpu_mean + cpu_median) / 2.0
    cpu_p75 = (cpu_median + cpu_p95) / 2.0
    cpu_p90 = (cpu_p95 + cpu_p99) / 2.0
    cpu_max = cpu_p99   # best approximation without raw series

    cpu_dist = {
        "mean":   cpu_mean,
        "median": cpu_median,
        "p25":    cpu_p25,
        "p75":    cpu_p75,
        "p90":    cpu_p90,
        "p95":    cpu_p95,
        "p99":    cpu_p99,
        "max":    cpu_max,
    }

    # No memory / network / disk granular data available from aggregates
    network_in_p95 = 0.0
    disk_read_iops_p95 = 0.0
    disk_write_iops_p95 = 0.0
    io_utilization_pct = 0.0
    has_memory_data = False

    # Limited pattern detection (no autocorr/regression without timeseries)
    pattern = _detect_pattern(
        cpu_series=np.array([]),    # empty – timeseries checks will be skipped
        cpu_dist=cpu_dist,
        network_in_p95=network_in_p95,
        has_timeseries=False,
    )

    cpu_score, memory_score, io_score, composite_score = _composite_score(
        cpu_p95=cpu_p95,
        memory_p95=0.0,
        io_utilization_pct=io_utilization_pct,
        has_memory_data=has_memory_data,
    )

    return {
        "instance_id":          instance_id,
        # CPU distribution (from aggregates + heuristics)
        "cpu_mean":             cpu_mean,
        "cpu_median":           cpu_median,
        "cpu_p25":              cpu_p25,
        "cpu_p75":              cpu_p75,
        "cpu_p90":              cpu_p90,
        "cpu_p95":              cpu_p95,
        "cpu_p99":              cpu_p99,
        "cpu_max":              cpu_max,
        # Memory distribution — all zeroes (no data)
        "memory_mean":          0.0,
        "memory_median":        0.0,
        "memory_p25":           0.0,
        "memory_p75":           0.0,
        "memory_p90":           0.0,
        "memory_p95":           0.0,
        "memory_p99":           0.0,
        "memory_max":           0.0,
        # Network — unavailable
        "network_in_p50":       0.0,
        "network_in_p95":       0.0,
        "network_out_p50":      0.0,
        "network_out_p95":      0.0,
        # Disk IOPS — unavailable
        "disk_read_iops_p95":   0.0,
        "disk_write_iops_p95":  0.0,
        # Derived
        "io_utilization_pct":   io_utilization_pct,
        "pattern":              pattern.value,
        "cpu_score":            cpu_score,
        "memory_score":         memory_score,
        "io_score":             io_score,
        "composite_score":      composite_score,
        "has_memory_data":      has_memory_data,
        "has_timeseries":       False,
    }


# ─── Main entry-point ────────────────────────────────────────────────────────

def profile_utilization(
    instances_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Profile utilization for every instance in *instances_df*.

    Parameters
    ----------
    instances_df : pd.DataFrame
        One row per compute instance.  Must contain ``instance_id``.
        Aggregated CPU columns (``cpu_avg``, ``cpu_p50``, ``cpu_p95``,
        ``cpu_p99``) are used as fallback when no timeseries is available.

    metrics_df : pd.DataFrame
        Raw metric timeseries.  Must contain ``instance_id`` plus some
        subset of: ``cpu_utilization``, ``memory_utilization``,
        ``network_bytes_in``, ``network_bytes_out``,
        ``disk_read_iops``, ``disk_write_iops``.

    Returns
    -------
    pd.DataFrame
        One row per instance with columns:

        instance_id,
        cpu_mean, cpu_median, cpu_p25, cpu_p75, cpu_p90, cpu_p95, cpu_p99, cpu_max,
        memory_mean, memory_median, memory_p25, memory_p75, memory_p90, memory_p95,
        memory_p99, memory_max,
        network_in_p50, network_in_p95, network_out_p50, network_out_p95,
        disk_read_iops_p95, disk_write_iops_p95,
        io_utilization_pct, pattern,
        cpu_score, memory_score, io_score, composite_score,
        has_memory_data, has_timeseries
    """
    if instances_df.empty:
        log.warning("profile_utilization called with empty instances_df")
        return pd.DataFrame()

    # Pre-index metrics by instance_id for O(1) group lookups
    has_metrics = (
        metrics_df is not None
        and not metrics_df.empty
        and "instance_id" in metrics_df.columns
    )
    if has_metrics:
        grouped_metrics = metrics_df.groupby("instance_id", sort=False)
        ts_index: set[str] = set(grouped_metrics.groups.keys())
    else:
        grouped_metrics = None
        ts_index = set()

    rows: list[dict] = []

    for _, inst in instances_df.iterrows():
        instance_id = str(inst.get("instance_id", ""))
        if not instance_id:
            log.warning("Skipping instance row with missing instance_id")
            continue

        if instance_id in ts_index:
            try:
                ts = grouped_metrics.get_group(instance_id)
                row = _build_row_from_timeseries(instance_id, ts)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Failed to build timeseries row; falling back to aggregates",
                    instance_id=instance_id,
                    error=str(exc),
                )
                row = _build_row_from_aggregates(instance_id, inst)
        else:
            row = _build_row_from_aggregates(instance_id, inst)

        rows.append(row)

    if not rows:
        log.warning("profile_utilization produced no output rows")
        return pd.DataFrame()

    utilization_df = pd.DataFrame(rows)

    # Guarantee column order matches the documented contract
    ordered_cols = [
        "instance_id",
        "cpu_mean", "cpu_median", "cpu_p25", "cpu_p75",
        "cpu_p90", "cpu_p95", "cpu_p99", "cpu_max",
        "memory_mean", "memory_median", "memory_p25", "memory_p75",
        "memory_p90", "memory_p95", "memory_p99", "memory_max",
        "network_in_p50", "network_in_p95",
        "network_out_p50", "network_out_p95",
        "disk_read_iops_p95", "disk_write_iops_p95",
        "io_utilization_pct", "pattern",
        "cpu_score", "memory_score", "io_score", "composite_score",
        "has_memory_data", "has_timeseries",
    ]
    # Only reindex with columns that are actually present
    present = [c for c in ordered_cols if c in utilization_df.columns]
    utilization_df = utilization_df[present]

    log.info(
        "profile_utilization complete",
        total_instances=len(utilization_df),
        with_timeseries=int(utilization_df["has_timeseries"].sum()),
        without_timeseries=int((~utilization_df["has_timeseries"]).sum()),
    )

    return utilization_df
