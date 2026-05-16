"""
src/analytics/loader.py
=======================
OCI Cost Optimisation Analytics – raw-JSON loader.

Reads the Phase-1 collector output (a single JSON file written by main.py's
_write_raw()) and converts it into four tidy pandas DataFrames plus a
ValidationReport that callers can inspect before proceeding.

Public API
----------
load_raw(path, config) -> (instances_df, metrics_df, costs_df, volumes_df, report)

Design decisions
----------------
* No pandas SettingWithCopyWarning footguns: every mutation is done on a
  freshly-constructed DataFrame or via .loc on the owning frame.
* Currency conversion uses the fx_rates from the JSON file; config can
  supply additional or override rates via config["fx_rates"].
* Metric gap-filling inserts NaN rows without interpolation.
* Deduplication keeps the *last* occurrence of (instance_id, metric_name, ts).
* Pandera schemas are defined but validation is best-effort: if pandera is not
  installed the schemas are skipped and a warning is logged.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    import pandera as pa
    from pandera import DataFrameSchema, Column, Check

    _PANDERA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PANDERA_AVAILABLE = False

from src.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

_ASSUMED_COVERAGE_HOURS: float = 24.0 * 15  # 360 h – used when only agg stats exist
_SUFFICIENT_DATA_HOURS: float = 24.0
_MAX_VALID_FRACTION: float = 0.05

_KNOWN_METRIC_NAMES = frozenset(
    {
        "cpu_utilization",
        "memory_utilization",
        "network_in_kbps",
        "network_out_kbps",
        "disk_read_iops",
        "disk_write_iops",
    }
)


@dataclass
class ValidationViolation:
    record_type: str  # "instance" | "metric" | "cost" | "volume"
    record_id: str
    field: str
    reason: str


@dataclass
class ValidationReport:
    total_records: int
    violations: list[ValidationViolation] = field(default_factory=list)
    currencies_missing_rates: list[str] = field(default_factory=list)
    passed: bool = True

    @property
    def invalid_fraction(self) -> float:
        if self.total_records == 0:
            return 0.0
        # resource_id violations on cost records are informational (OCI Usage API
        # commonly returns service-level aggregates with no per-resource OCID);
        # exclude them from the hard-failure threshold.
        hard = sum(1 for v in self.violations if v.field != "resource_id")
        return hard / self.total_records

    def summary(self) -> str:
        return (
            f"ValidationReport: {len(self.violations)} violations out of "
            f"{self.total_records} records "
            f"({'PASS' if self.passed else 'FAIL'})"
        )


# ---------------------------------------------------------------------------
# Pandera schemas (informational – validated after DataFrame construction)
# ---------------------------------------------------------------------------

def _build_pandera_schemas() -> dict[str, Any]:
    """Return pandera DataFrameSchema objects keyed by name, or empty dict."""
    if not _PANDERA_AVAILABLE:
        return {}

    instances_schema = DataFrameSchema(
        {
            "instance_id": Column(str, nullable=False),
            "display_name": Column(str, nullable=False),
            "shape": Column(str, nullable=False),
            "region": Column(str, nullable=False),
            "compartment_id": Column(str, nullable=False),
            "lifecycle_state": Column(str, nullable=False),
            "has_timeseries": Column(bool, nullable=False),
            "data_coverage_hours": Column(float, Check.ge(0), nullable=False),
            "data_coverage_days": Column(float, Check.ge(0), nullable=False),
            "sufficient_data": Column(bool, nullable=False),
            "cpu_avg": Column(float, nullable=True),
            "cpu_p50": Column(float, nullable=True),
            "cpu_p95": Column(float, nullable=True),
            "cpu_p99": Column(float, nullable=True),
            "cpu_peak": Column(float, nullable=True),
            "memory_avg": Column(float, nullable=True),
            "memory_p50": Column(float, nullable=True),
            "memory_p95": Column(float, nullable=True),
            "memory_p99": Column(float, nullable=True),
            "memory_peak": Column(float, nullable=True),
        },
        coerce=False,
        strict=False,  # allow extra columns (e.g. time_created, collected_at)
    )

    metrics_schema = DataFrameSchema(
        {
            "instance_id": Column(str, nullable=False),
            "metric_name": Column(
                str,
                Check.isin(list(_KNOWN_METRIC_NAMES)),
                nullable=False,
            ),
            "value": Column(float, nullable=True),
        },
        coerce=False,
        strict=False,
    )

    costs_schema = DataFrameSchema(
        {
            "resource_id": Column(str, nullable=False),
            "service": Column(str, nullable=False),
            "compartment_id": Column(str, nullable=False),
            "currency": Column(str, nullable=False),
            "original_cost": Column(float, Check.ge(0), nullable=False),
            "is_orphaned": Column(bool, nullable=False),
        },
        coerce=False,
        strict=False,
    )

    volumes_schema = DataFrameSchema(
        {
            "volume_id": Column(str, nullable=False),
            "display_name": Column(str, nullable=False),
            "size_gb": Column(int, Check.gt(0), nullable=False),
            "lifecycle_state": Column(str, nullable=False),
            "compartment_id": Column(str, nullable=False),
            "region": Column(str, nullable=False),
            "attached_instance_id": Column(str, nullable=False),
        },
        coerce=False,
        strict=False,
    )

    return {
        "instances": instances_schema,
        "metrics": metrics_schema,
        "costs": costs_schema,
        "volumes": volumes_schema,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_utc_timestamp(value: Any) -> pd.Timestamp:
    """
    Parse an ISO-8601 string (or datetime) into a UTC-aware pd.Timestamp.
    Returns pd.NaT on failure.
    """
    if value is None:
        return pd.NaT  # type: ignore[return-value]
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts
    except Exception:
        return pd.NaT  # type: ignore[return-value]


def _safe_float(value: Any) -> float:
    """Return float or NaN for None / non-numeric."""
    if value is None:
        return float("nan")
    try:
        result = float(value)
        if math.isnan(result):
            return float("nan")
        return result
    except (TypeError, ValueError):
        return float("nan")


def _safe_int(value: Any, default: int = 0) -> int:
    """Return int or default for None / non-numeric."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _merge_fx_rates(json_fx: dict, config_fx: dict) -> dict[str, float]:
    """
    Merge fx_rates from JSON and config. Config values take precedence.
    USD is always 1.0.
    """
    merged: dict[str, float] = {"USD": 1.0}
    for currency, rate in json_fx.items():
        try:
            merged[str(currency).upper()] = float(rate)
        except (TypeError, ValueError):
            log.warning("fx_rate_invalid", currency=currency, rate=rate)
    for currency, rate in config_fx.items():
        try:
            merged[str(currency).upper()] = float(rate)
        except (TypeError, ValueError):
            log.warning("fx_rate_invalid_config", currency=currency, rate=rate)
    merged["USD"] = 1.0  # always anchor
    return merged


# ---------------------------------------------------------------------------
# Metric timeseries helpers
# ---------------------------------------------------------------------------

def _detect_interval_seconds(timestamps: list[pd.Timestamp]) -> float:
    """
    Estimate the expected interval between consecutive metric points (seconds).
    Uses the median of pairwise differences among the first min(50, N) pairs.
    Falls back to 3600 (1 h) if < 2 points.
    """
    if len(timestamps) < 2:
        return 3600.0
    diffs = [
        (timestamps[i + 1] - timestamps[i]).total_seconds()
        for i in range(min(len(timestamps) - 1, 50))
        if (timestamps[i + 1] - timestamps[i]).total_seconds() > 0
    ]
    if not diffs:
        return 3600.0
    return statistics.median(diffs)


def _fill_gaps(
    points: list[dict],
    instance_id: str,
    metric_name: str,
) -> list[dict]:
    """
    Given a list of raw {"ts": str, "v": float|None} dicts for one metric on
    one instance, return an expanded list that includes NaN sentinel rows for
    any gap that exceeds 2× the median interval.

    The returned list may be longer than the input; the original rows are kept
    verbatim (no interpolation).
    """
    if len(points) < 2:
        return points

    parsed: list[tuple[pd.Timestamp, Any]] = []
    for pt in points:
        ts = _parse_utc_timestamp(pt.get("ts"))
        if ts is pd.NaT:
            continue
        parsed.append((ts, pt.get("v")))

    if len(parsed) < 2:
        return points

    parsed.sort(key=lambda x: x[0])
    timestamps = [p[0] for p in parsed]
    interval = _detect_interval_seconds(timestamps)
    gap_threshold = 2.0 * interval

    result: list[dict] = []
    for i, (ts, v) in enumerate(parsed):
        result.append({"ts": ts, "v": v})
        if i < len(parsed) - 1:
            next_ts = parsed[i + 1][0]
            gap_seconds = (next_ts - ts).total_seconds()
            if gap_seconds > gap_threshold:
                # Insert NaN placeholders at expected interval increments
                n_missing = int(round(gap_seconds / interval)) - 1
                for k in range(1, n_missing + 1):
                    gap_ts = ts + pd.Timedelta(seconds=interval * k)
                    if gap_ts < next_ts:
                        result.append({"ts": gap_ts, "v": None})
    return result


def _compute_coverage_hours(
    points: list[dict],
    interval_seconds: float,
) -> float:
    """
    Coverage = span from min_ts to max_ts + one interval (to count the last
    observation period).
    """
    timestamps: list[pd.Timestamp] = []
    for pt in points:
        ts = pt.get("ts")
        if isinstance(ts, pd.Timestamp):
            timestamps.append(ts)
        else:
            parsed = _parse_utc_timestamp(ts)
            if parsed is not pd.NaT:
                timestamps.append(parsed)
    if len(timestamps) < 2:
        return 0.0
    span_seconds = (max(timestamps) - min(timestamps)).total_seconds()
    return (span_seconds + interval_seconds) / 3600.0


# ---------------------------------------------------------------------------
# Per-section loaders
# ---------------------------------------------------------------------------

def _load_instances(
    raw_instances: list[dict],
    report: ValidationReport,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Parse instances list → (instances_df, metrics_rows).

    metrics_rows is a flat list of dicts ready for pd.DataFrame construction;
    returned separately so deduplication can happen in one pass.
    """
    inst_rows: list[dict] = []
    all_metric_rows: list[dict] = []

    for inst_raw in raw_instances:
        instance_id: str = str(inst_raw.get("ocid") or "").strip()
        display_name: str = str(inst_raw.get("display_name") or "")
        shape: str = str(inst_raw.get("shape") or "").strip()
        region: str = str(inst_raw.get("region") or "").strip()
        compartment_id: str = str(inst_raw.get("compartment_id") or "").strip()
        lifecycle_state: str = str(inst_raw.get("lifecycle_state") or "").strip()

        record_id = instance_id or f"<unknown@{len(inst_rows)}>"

        # --- Required field validation ---
        missing: list[str] = []
        if not instance_id:
            missing.append("instance_id")
        if not shape:
            missing.append("shape")
        if not region:
            missing.append("region")
        if not compartment_id:
            missing.append("compartment_id")

        for fld in missing:
            report.violations.append(
                ValidationViolation(
                    record_type="instance",
                    record_id=record_id,
                    field=fld,
                    reason=f"Required field '{fld}' is missing or empty",
                )
            )

        time_created = _parse_utc_timestamp(inst_raw.get("time_created"))
        collected_at = _parse_utc_timestamp(inst_raw.get("collected_at"))

        # --- Aggregated metric stats ---
        cpu_raw: dict = inst_raw.get("cpu") or {}
        mem_raw: dict = inst_raw.get("memory") or {}

        cpu_avg = _safe_float(cpu_raw.get("avg"))
        cpu_p50 = _safe_float(cpu_raw.get("p50"))
        cpu_p95 = _safe_float(cpu_raw.get("p95"))
        cpu_p99 = _safe_float(cpu_raw.get("p99"))
        cpu_peak = _safe_float(cpu_raw.get("peak"))
        memory_avg = _safe_float(mem_raw.get("avg"))
        memory_p50 = _safe_float(mem_raw.get("p50"))
        memory_p95 = _safe_float(mem_raw.get("p95"))
        memory_p99 = _safe_float(mem_raw.get("p99"))
        memory_peak = _safe_float(mem_raw.get("peak"))

        has_aggregated_stats = not (
            math.isnan(cpu_avg)
            and math.isnan(memory_avg)
        )

        # --- Timeseries ---
        ts_dict: Optional[dict] = inst_raw.get("metrics_timeseries")
        has_timeseries = bool(ts_dict)
        data_coverage_hours: float = 0.0

        if has_timeseries and ts_dict:
            # Pick a canonical metric to estimate coverage (prefer cpu_utilization)
            canonical_key = "cpu_utilization"
            all_keys = list(ts_dict.keys())
            ref_key = canonical_key if canonical_key in ts_dict else (all_keys[0] if all_keys else None)

            if ref_key:
                ref_points = ts_dict[ref_key] or []
                parsed_ref_pts = []
                for pt in ref_points:
                    ts_val = _parse_utc_timestamp(pt.get("ts"))
                    if ts_val is not pd.NaT:
                        parsed_ref_pts.append(ts_val)

                if len(parsed_ref_pts) >= 2:
                    interval_s = _detect_interval_seconds(parsed_ref_pts)
                    # Reconstruct point list for coverage computation
                    ref_for_cov = [{"ts": t, "v": None} for t in parsed_ref_pts]
                    data_coverage_hours = _compute_coverage_hours(ref_for_cov, interval_s)
                elif len(parsed_ref_pts) == 1:
                    data_coverage_hours = 1.0  # single point = 1 h
                # else 0.0

            # Build metric rows for all metric names in the timeseries
            for metric_name, raw_points in ts_dict.items():
                if metric_name not in _KNOWN_METRIC_NAMES:
                    log.debug(
                        "unknown_metric_skipped",
                        instance_id=instance_id,
                        metric_name=metric_name,
                    )
                    continue
                if not raw_points:
                    continue

                filled_points = _fill_gaps(raw_points, instance_id, metric_name)

                for pt in filled_points:
                    raw_ts = pt.get("ts")
                    raw_v = pt.get("v")

                    # Validate metric point
                    ts_parsed = (
                        raw_ts
                        if isinstance(raw_ts, pd.Timestamp)
                        else _parse_utc_timestamp(raw_ts)
                    )
                    if ts_parsed is pd.NaT:
                        report.violations.append(
                            ValidationViolation(
                                record_type="metric",
                                record_id=instance_id,
                                field="ts",
                                reason="Metric point has null/unparseable timestamp",
                            )
                        )
                        continue

                    value = _safe_float(raw_v)  # NaN is fine for gap rows

                    all_metric_rows.append(
                        {
                            "instance_id": instance_id,
                            "metric_name": metric_name,
                            "timestamp": ts_parsed,
                            "value": value,
                        }
                    )
        elif has_aggregated_stats:
            # No timeseries but has aggregated stats — use assumed coverage
            data_coverage_hours = _ASSUMED_COVERAGE_HOURS

        data_coverage_days = data_coverage_hours / 24.0
        sufficient_data = data_coverage_hours >= _SUFFICIENT_DATA_HOURS

        inst_rows.append(
            {
                "instance_id": instance_id,
                "display_name": display_name,
                "shape": shape,
                "region": region,
                "compartment_id": compartment_id,
                "lifecycle_state": lifecycle_state,
                "time_created": time_created,
                "collected_at": collected_at,
                "has_timeseries": has_timeseries,
                "data_coverage_hours": data_coverage_hours,
                "data_coverage_days": data_coverage_days,
                "sufficient_data": sufficient_data,
                "cpu_avg": cpu_avg,
                "cpu_p50": cpu_p50,
                "cpu_p95": cpu_p95,
                "cpu_p99": cpu_p99,
                "cpu_peak": cpu_peak,
                "memory_avg": memory_avg,
                "memory_p50": memory_p50,
                "memory_p95": memory_p95,
                "memory_p99": memory_p99,
                "memory_peak": memory_peak,
            }
        )

    instances_df = pd.DataFrame(inst_rows)
    if instances_df.empty:
        instances_df = _empty_instances_df()

    return instances_df, all_metric_rows


def _build_metrics_df(all_metric_rows: list[dict]) -> pd.DataFrame:
    """
    Deduplicate metric rows and build the metrics DataFrame.

    Deduplication rule: same (instance_id, metric_name, timestamp) →
    keep the last occurrence (last index position wins because rows are
    appended in source order).
    """
    if not all_metric_rows:
        return _empty_metrics_df()

    df = pd.DataFrame(all_metric_rows)
    # Ensure timestamp column is UTC-aware Timestamps
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Deduplicate: keep last occurrence
    df = df.drop_duplicates(
        subset=["instance_id", "metric_name", "timestamp"],
        keep="last",
    ).reset_index(drop=True)

    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)
    return df


def _load_costs(
    raw_cost_records: list[dict],
    fx_rates: dict[str, float],
    report: ValidationReport,
) -> pd.DataFrame:
    """Parse cost records → costs_df. Mutates report for currency issues."""
    rows: list[dict] = []
    missing_currencies: set[str] = set()

    for rec in raw_cost_records:
        resource_id: str = str(rec.get("resource_id") or "").strip()
        service: str = str(rec.get("service") or "").strip()
        compartment_id: str = str(rec.get("compartment_id") or "").strip()
        sku_description: str = str(rec.get("sku_description") or "")
        currency: str = str(rec.get("currency") or "USD").strip().upper()
        raw_cost = rec.get("total_cost")

        record_id = resource_id or f"<cost@{len(rows)}>"

        # --- Required field validation ---
        if not resource_id:
            report.violations.append(
                ValidationViolation(
                    record_type="cost",
                    record_id=record_id,
                    field="resource_id",
                    reason="Cost record has no resource_id; cannot be attributed to a specific instance",
                )
            )

        if not currency:
            report.violations.append(
                ValidationViolation(
                    record_type="cost",
                    record_id=record_id,
                    field="currency",
                    reason="Required field 'currency' is missing or empty",
                )
            )

        original_cost = _safe_float(raw_cost)
        if math.isnan(original_cost) or original_cost < 0:
            report.violations.append(
                ValidationViolation(
                    record_type="cost",
                    record_id=record_id,
                    field="original_cost",
                    reason=(
                        f"original_cost must be >= 0 (got {raw_cost!r})"
                    ),
                )
            )

        # --- Currency conversion ---
        if currency == "USD" or currency not in fx_rates:
            if currency not in fx_rates and currency != "USD":
                missing_currencies.add(currency)
                cost_usd = float("nan")
            else:
                # USD → 1.0
                cost_usd = original_cost
        else:
            rate = fx_rates[currency]
            cost_usd = original_cost * rate

        period_start = _parse_utc_timestamp(rec.get("period_start"))
        period_end = _parse_utc_timestamp(rec.get("period_end"))

        rows.append(
            {
                "resource_id": resource_id,
                "service": service,
                "compartment_id": compartment_id,
                "sku_description": sku_description,
                "currency": currency,
                "original_cost": original_cost,
                "cost_usd": cost_usd,
                "period_start": period_start,
                "period_end": period_end,
                "is_orphaned": False,
            }
        )

    # Update report with missing currencies
    for cur in sorted(missing_currencies):
        if cur not in report.currencies_missing_rates:
            report.currencies_missing_rates.append(cur)
            log.warning(
                "currency_rate_missing",
                currency=cur,
                note="cost_usd set to NaN for affected records",
            )

    if report.currencies_missing_rates:
        report.passed = False

    if not rows:
        return _empty_costs_df()

    df = pd.DataFrame(rows)
    df["original_cost"] = pd.to_numeric(df["original_cost"], errors="coerce").astype(float)
    df["cost_usd"] = pd.to_numeric(df["cost_usd"], errors="coerce").astype(float)
    return df


def _load_volumes(
    raw_volumes: list[dict],
    report: ValidationReport,
) -> pd.DataFrame:
    """Parse volumes list → volumes_df."""
    rows: list[dict] = []

    for vol in raw_volumes:
        volume_id: str = str(vol.get("ocid") or "").strip()
        display_name: str = str(vol.get("display_name") or "")
        size_gb_raw = vol.get("size_gb")
        vpu_per_gb_raw = vol.get("vpu_per_gb")
        lifecycle_state: str = str(vol.get("lifecycle_state") or "").strip()
        compartment_id: str = str(vol.get("compartment_id") or "").strip()
        region: str = str(vol.get("region") or "").strip()
        attached_instance_id: str = str(vol.get("attached_instance_id") or "")
        collected_at = _parse_utc_timestamp(vol.get("collected_at"))

        record_id = volume_id or f"<volume@{len(rows)}>"

        size_gb = _safe_int(size_gb_raw, default=0)
        vpu_per_gb = _safe_int(vpu_per_gb_raw, default=10)

        # --- Required field validation ---
        if not volume_id:
            report.violations.append(
                ValidationViolation(
                    record_type="volume",
                    record_id=record_id,
                    field="volume_id",
                    reason="Required field 'volume_id' (ocid) is missing or empty",
                )
            )

        if size_gb <= 0:
            report.violations.append(
                ValidationViolation(
                    record_type="volume",
                    record_id=record_id,
                    field="size_gb",
                    reason=f"size_gb must be > 0 (got {size_gb_raw!r})",
                )
            )

        read_throughput_avg = _safe_float(vol.get("read_throughput_avg"))
        write_throughput_avg = _safe_float(vol.get("write_throughput_avg"))
        read_iops_avg = _safe_float(vol.get("read_iops_avg"))
        write_iops_avg = _safe_float(vol.get("write_iops_avg"))

        rows.append(
            {
                "volume_id": volume_id,
                "display_name": display_name,
                "size_gb": size_gb,
                "vpu_per_gb": vpu_per_gb,
                "lifecycle_state": lifecycle_state,
                "compartment_id": compartment_id,
                "region": region,
                "attached_instance_id": attached_instance_id,
                "read_throughput_avg": read_throughput_avg,
                "write_throughput_avg": write_throughput_avg,
                "read_iops_avg": read_iops_avg,
                "write_iops_avg": write_iops_avg,
                "collected_at": collected_at,
            }
        )

    if not rows:
        return _empty_volumes_df()

    df = pd.DataFrame(rows)
    df["size_gb"] = df["size_gb"].astype(int)
    df["vpu_per_gb"] = df["vpu_per_gb"].astype(int)
    for col in ("read_throughput_avg", "write_throughput_avg", "read_iops_avg", "write_iops_avg"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


# ---------------------------------------------------------------------------
# Empty DataFrame constructors (used when a section is absent in the JSON)
# ---------------------------------------------------------------------------

def _empty_instances_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "instance_id",
            "display_name",
            "shape",
            "region",
            "compartment_id",
            "lifecycle_state",
            "time_created",
            "collected_at",
            "has_timeseries",
            "data_coverage_hours",
            "data_coverage_days",
            "sufficient_data",
            "cpu_avg",
            "cpu_p50",
            "cpu_p95",
            "cpu_p99",
            "cpu_peak",
            "memory_avg",
            "memory_p50",
            "memory_p95",
            "memory_p99",
            "memory_peak",
        ]
    )


def _empty_metrics_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["instance_id", "metric_name", "timestamp", "value"]
    )


def _empty_costs_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "resource_id",
            "service",
            "compartment_id",
            "sku_description",
            "currency",
            "original_cost",
            "cost_usd",
            "period_start",
            "period_end",
            "is_orphaned",
        ]
    )


def _empty_volumes_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "volume_id",
            "display_name",
            "size_gb",
            "vpu_per_gb",
            "lifecycle_state",
            "compartment_id",
            "region",
            "attached_instance_id",
            "read_throughput_avg",
            "write_throughput_avg",
            "read_iops_avg",
            "write_iops_avg",
            "collected_at",
        ]
    )


def _load_buckets(raw_buckets: list[dict]) -> "pd.DataFrame":
    """Build a tidy DataFrame from raw bucket inventory records."""
    rows = []
    for b in raw_buckets:
        rows.append({
            "name": str(b.get("name") or ""),
            "storage_tier": str(b.get("storage_tier") or "Standard"),
            "approximate_size_gb": float(b.get("approximate_size_gb") or b.get("approximate_size") or 0.0),
            "approximate_count": int(b.get("approximate_count") or 0),
            "lifecycle_state": str(b.get("lifecycle_state") or "ACTIVE"),
            "compartment_id": str(b.get("compartment_id") or ""),
            "namespace": str(b.get("namespace") or ""),
        })
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=["name", "storage_tier", "approximate_size_gb", "approximate_count",
                                  "lifecycle_state", "compartment_id", "namespace"])


# ---------------------------------------------------------------------------
# Pandera post-validation
# ---------------------------------------------------------------------------

def _run_pandera_validation(
    name: str,
    df: pd.DataFrame,
    schema: Any,
) -> None:
    """Run pandera schema validation and log any errors. Non-fatal."""
    if not _PANDERA_AVAILABLE or schema is None:
        return
    try:
        schema.validate(df, lazy=True)
        log.debug("pandera_validation_passed", dataframe=name)
    except pa.errors.SchemaErrors as exc:
        log.warning(
            "pandera_validation_errors",
            dataframe=name,
            n_errors=len(exc.failure_cases),
            sample=str(exc.failure_cases.head(5).to_dict("records")),
        )
    except Exception as exc:  # pragma: no cover
        log.warning("pandera_validation_unexpected_error", dataframe=name, error=str(exc))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_raw(
    path: Path,
    config: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, ValidationReport]:
    """
    Load a raw OCI collector JSON file and return tidy DataFrames.

    Parameters
    ----------
    path:
        Path to the *_raw.json file written by the Phase-1 collector.
    config:
        Application config dict (from config.yaml / _load_config()).
        Used for:
          - config.get("fx_rates", {}) → additional / override currency rates.

    Returns
    -------
    (instances_df, metrics_df, costs_df, volumes_df, buckets_df, report)

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    json.JSONDecodeError
        If the file is not valid JSON.
    ValueError
        If the fraction of invalid records exceeds 5 %.
    """
    path = Path(path)
    log.info("load_raw_start", path=str(path))

    if not path.exists():
        raise FileNotFoundError(f"Raw data file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw: dict = json.load(fh)

    raw_instances: list[dict] = raw.get("instances") or []
    # Merge block volumes + boot volumes into one list; boot volume OCIDs contain "bootvolume"
    raw_volumes: list[dict] = (raw.get("volumes") or []) + (raw.get("boot_volumes") or [])
    raw_cost_records: list[dict] = raw.get("cost_records") or []
    raw_buckets: list[dict] = raw.get("buckets") or []

    total_records = len(raw_instances) + len(raw_volumes) + len(raw_cost_records)
    report = ValidationReport(total_records=total_records)

    log.info(
        "load_raw_counts",
        instances=len(raw_instances),
        volumes=len(raw_volumes),
        cost_records=len(raw_cost_records),
        buckets=len(raw_buckets),
    )

    # --- FX rates: JSON file wins over config for defaults; config overrides ---
    json_fx: dict = raw.get("fx_rates") or {}
    config_fx: dict = config.get("fx_rates") or {}
    fx_rates = _merge_fx_rates(json_fx, config_fx)
    log.debug("fx_rates_loaded", rates=fx_rates)

    # --- Load each section ---
    instances_df, all_metric_rows = _load_instances(raw_instances, report)
    metrics_df = _build_metrics_df(all_metric_rows)
    costs_df = _load_costs(raw_cost_records, fx_rates, report)
    volumes_df = _load_volumes(raw_volumes, report)
    buckets_df = _load_buckets(raw_buckets)

    # --- Post-load violation threshold check ---
    if report.invalid_fraction > _MAX_VALID_FRACTION:
        report.passed = False
        raise ValueError(
            f"Validation failed: {report.invalid_fraction:.1%} of records failed "
            f"— {len(report.violations)} violations"
        )

    # --- Pandera structural validation (non-fatal) ---
    schemas = _build_pandera_schemas()
    _run_pandera_validation("instances", instances_df, schemas.get("instances"))
    _run_pandera_validation("metrics", metrics_df, schemas.get("metrics"))
    _run_pandera_validation("costs", costs_df, schemas.get("costs"))
    _run_pandera_validation("volumes", volumes_df, schemas.get("volumes"))

    log.info(
        "load_raw_complete",
        instances_rows=len(instances_df),
        metrics_rows=len(metrics_df),
        costs_rows=len(costs_df),
        volumes_rows=len(volumes_df),
        buckets_rows=len(buckets_df),
        violations=len(report.violations),
        passed=report.passed,
    )
    log.info("validation_summary", summary=report.summary())

    return instances_df, metrics_df, costs_df, volumes_df, buckets_df, report
