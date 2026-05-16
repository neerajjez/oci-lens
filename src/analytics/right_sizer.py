"""
src/analytics/right_sizer.py
============================
OCI Cost Optimisation Analytics – right-sizing recommendation engine.

For each compute instance, evaluates the current shape against observed
utilization patterns and the shape catalog, then emits a typed Recommendation
with rationale, confidence scoring, risk assessment, and rejected alternatives.

Public API
----------
generate_recommendations(instances_df, utilization_df, cost_attribution_df,
                         catalog) -> list[Recommendation]
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd

from src.analytics.confidence import ConfidenceLabel, ConfidenceResult, compute_confidence
from src.analytics.shape_catalog import Shape, ShapeCatalog
from src.analytics.utilization import UtilizationPattern
from src.utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums and public dataclasses
# ---------------------------------------------------------------------------

class RecommendationType(str, Enum):
    DOWNSIZE = "DOWNSIZE"
    UPSIZE_OR_INVESTIGATE = "UPSIZE_OR_INVESTIGATE"
    TERMINATE = "TERMINATE"
    MONITOR = "MONITOR"
    OPTIMAL = "OPTIMAL"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ShapeConfig:
    ocpu: int
    ram_gb: int


@dataclass
class RejectedAlternative:
    shape_name: str
    ocpu: int
    ram_gb: int
    monthly_cost: float
    rejection_reason: str


@dataclass
class Recommendation:
    instance_id: str
    instance_name: str
    recommendation_type: RecommendationType
    current_shape: str
    current_config: ShapeConfig
    recommended_shape: Optional[str]
    recommended_config: Optional[ShapeConfig]
    current_monthly_cost: float
    estimated_monthly_cost: float
    estimated_monthly_savings: float
    savings_pct: float
    confidence_score: float
    confidence_label: ConfidenceLabel
    rationale: str
    prerequisites: list[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    rejected_alternatives: list[RejectedAlternative] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Safety multipliers by utilization pattern
# ---------------------------------------------------------------------------

_SAFETY_MULTIPLIERS: dict[str, float] = {
    "STEADY":      1.15,
    "BURSTY":      1.40,
    "CYCLICAL":    1.25,
    "WEEKLY":      1.25,
    "TRENDING_UP": 1.50,
    "IDLE":        0.50,
    "ERRATIC":     1.35,
}

# Default multiplier for unknown patterns
_DEFAULT_MULTIPLIER: float = 1.25

# Shape families that are bare-metal or GPU and cannot be flex-downsized
_BM_GPU_PREFIXES: tuple[str, ...] = ("BM.", "GPU", "Optimized3", "HPC")

# Thresholds for the savings filter
_MIN_SAVINGS_PCT: float = 5.0
_MIN_SAVINGS_ABS: float = 20.0

# Idle thresholds used in rationale text
_IDLE_CPU_P95_THRESHOLD: float = 5.0
_IDLE_NET_P95_THRESHOLD: float = 1000.0  # kbps

# Default flex shape capacity when shape_config is absent
_FLEX_DEFAULT_OCPU: int = 4
_FLEX_DEFAULT_RAM_GB: int = 32

# Max rejected alternatives to retain
_MAX_REJECTED: int = 3

# UPSIZE/investigate trigger
_UPSIZE_CPU_P99_THRESHOLD: float = 90.0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_flex_shape(shape_name: str) -> bool:
    """Return True if the shape name indicates a flex shape."""
    return "Flex" in shape_name


def _is_bm_or_gpu(shape_name: str) -> bool:
    """Return True for bare-metal or GPU shapes that should not auto-resize."""
    return shape_name.startswith(_BM_GPU_PREFIXES)


def _shape_family(shape_name: str) -> str:
    """
    Extract the shape family prefix.
    E.g. 'VM.Standard.E4.Flex' -> 'VM.Standard.E4'
         'VM.Standard3.Flex'    -> 'VM.Standard3'
         'VM.Standard.E4.Flex'  -> everything up to .Flex
    """
    parts = shape_name.split(".")
    # Drop trailing 'Flex' token if present
    if parts and parts[-1].lower() == "flex":
        parts = parts[:-1]
    return ".".join(parts)


def _get_shape_config(row: pd.Series, catalog: ShapeCatalog, shape_name: str) -> ShapeConfig:
    """
    Resolve the current shape's OCPU and RAM from (in priority order):
    1. instances_df 'shape_config' column (dict with 'ocpu' / 'ram_gb')
    2. ShapeCatalog lookup
    3. Flex defaults (4 OCPU / 32 GB)
    """
    cfg_raw = row.get("shape_config") if "shape_config" in row.index else None

    if cfg_raw and isinstance(cfg_raw, dict):
        try:
            ocpu = int(cfg_raw.get("ocpu") or 0)
            ram_gb = int(cfg_raw.get("ram_gb") or 0)
            if ocpu > 0 and ram_gb > 0:
                return ShapeConfig(ocpu=ocpu, ram_gb=ram_gb)
        except (TypeError, ValueError):
            pass

    # Try catalog
    try:
        shape_obj: Optional[Shape] = catalog.get(shape_name)
        if shape_obj is not None:
            return ShapeConfig(ocpu=shape_obj.ocpu, ram_gb=shape_obj.ram_gb)
    except Exception:
        pass

    # Flex default
    if _is_flex_shape(shape_name):
        return ShapeConfig(ocpu=_FLEX_DEFAULT_OCPU, ram_gb=_FLEX_DEFAULT_RAM_GB)

    # Last resort: cannot infer → use 1/1 so downstream maths don't divide by zero
    log.warning("shape_config_unknown", shape=shape_name)
    return ShapeConfig(ocpu=1, ram_gb=1)


def _current_monthly_cost(
    iid: str,
    cost_row: Optional[pd.Series],
    collection_period_days: int,
) -> float:
    """
    Derive current monthly cost from cost_attribution_df total_cost.
    Returns 0.0 if no billing data.
    """
    if cost_row is None:
        return 0.0
    total = float(cost_row.get("total_cost", 0.0) or 0.0)
    if collection_period_days > 0:
        return total * 30.0 / collection_period_days
    return 0.0


def _build_rationale(
    rec_type: RecommendationType,
    pattern: str,
    cpu_p95: float,
    memory_p95: float,
    net_p95: float,
    current_shape: str,
    multiplier: float,
    req_ocpu: int,
    req_ram_gb: int,
    savings_pct: float,
) -> str:
    """Generate a human-readable rationale sentence for a recommendation."""
    cpu_str = f"{cpu_p95:.1f}%" if not math.isnan(cpu_p95) else "N/A"
    mem_str = f"{memory_p95:.1f}%" if not math.isnan(memory_p95) else "N/A"
    net_str = f"{net_p95:.0f} kbps" if not math.isnan(net_p95) else "N/A"

    if rec_type == RecommendationType.DOWNSIZE:
        return (
            f"CPU p95 of {cpu_str} and memory p95 of {mem_str} are well below capacity "
            f"on the current {current_shape}; required OCPUs with {multiplier:.2f}× headroom "
            f"= {req_ocpu} OCPU / {req_ram_gb} GB RAM — a downsize saves "
            f"approximately {savings_pct:.1f}% monthly."
        )
    if rec_type == RecommendationType.TERMINATE:
        return (
            f"CPU p95 {cpu_str}, network p95 {net_str} — well below zombie thresholds "
            f"({_IDLE_CPU_P95_THRESHOLD:.0f}% / {_IDLE_NET_P95_THRESHOLD:.0f} kbps) "
            f"for the entire analysis period; instance appears idle and is a candidate "
            f"for termination."
        )
    if rec_type == RecommendationType.UPSIZE_OR_INVESTIGATE:
        return (
            f"CPU p99 exceeds {_UPSIZE_CPU_P99_THRESHOLD:.0f}% — the current {current_shape} "
            f"is likely undersized for the observed {pattern} workload; investigate or upsize."
        )
    if rec_type == RecommendationType.MONITOR:
        return (
            "Insufficient metric history to make a confident recommendation; "
            "continue monitoring and re-evaluate once at least 14 days of data are available."
        )
    # OPTIMAL
    return (
        f"Current shape is optimal for the observed {pattern} workload pattern; "
        f"savings threshold not met (required >{_MIN_SAVINGS_PCT:.0f}% and "
        f">${_MIN_SAVINGS_ABS:.0f}/month)."
    )


def _determine_risk(
    rec_type: RecommendationType,
    pattern: str,
    savings_pct: float,
    cpu_p99: float,
) -> RiskLevel:
    """Assign a risk level based on recommendation type and workload signals."""
    if rec_type in (RecommendationType.MONITOR, RecommendationType.OPTIMAL):
        return RiskLevel.LOW

    if rec_type == RecommendationType.TERMINATE:
        return RiskLevel.HIGH

    if rec_type == RecommendationType.UPSIZE_OR_INVESTIGATE:
        return RiskLevel.HIGH

    # DOWNSIZE
    if pattern in ("ERRATIC", "TRENDING_UP") or (not math.isnan(cpu_p99) and cpu_p99 > _UPSIZE_CPU_P99_THRESHOLD):
        return RiskLevel.HIGH
    if pattern == "BURSTY" or savings_pct >= 30.0:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_recommendations(
    instances_df: pd.DataFrame,
    utilization_df: pd.DataFrame,
    cost_attribution_df: pd.DataFrame,
    catalog: ShapeCatalog,
    collection_period_days: int = 15,
) -> list[Recommendation]:
    """
    Generate a right-sizing Recommendation for every instance in instances_df.

    Parameters
    ----------
    instances_df:
        Per-instance inventory from the loader / utilization pipeline.
    utilization_df:
        Per-instance utilization summary (one row per instance_id).
    cost_attribution_df:
        Output of cost_mapper.attribute_costs — one row per instance_id.
    catalog:
        Shape catalog for candidate lookups and cost estimation.
    collection_period_days:
        Number of days the current metrics window covers (used to annualise costs).

    Returns
    -------
    list[Recommendation]
        One Recommendation per instance in instances_df.
    """
    if instances_df.empty:
        log.warning("generate_recommendations_no_instances")
        return []

    # -----------------------------------------------------------------------
    # STEP 1 – Merge the three DataFrames on instance_id
    # -----------------------------------------------------------------------
    # Left join from instances so every instance gets a row
    merged = instances_df.merge(utilization_df, on="instance_id", how="left", suffixes=("", "_util"))
    merged = merged.merge(cost_attribution_df, on="instance_id", how="left", suffixes=("", "_cost"))

    # Build cost lookup by instance_id for fast access
    cost_lookup: dict[str, pd.Series] = {}
    if not cost_attribution_df.empty:
        for _, crow in cost_attribution_df.iterrows():
            cost_lookup[str(crow["instance_id"])] = crow

    recommendations: list[Recommendation] = []

    for _, row in merged.iterrows():
        iid = str(row.get("instance_id", ""))
        instance_name = str(row.get("display_name", iid))
        shape_name = str(row.get("shape", ""))

        # -----------------------------------------------------------------------
        # Resolve scalar fields; guard against NaN
        # -----------------------------------------------------------------------
        sufficient_data = bool(row.get("sufficient_data", False))
        data_coverage_days = float(row.get("data_coverage_days", 0.0) or 0.0)
        has_memory_data = bool(row.get("has_memory_data", False))
        has_timeseries = bool(row.get("has_timeseries", False))

        pattern_raw = str(row.get("pattern", "STEADY") or "STEADY")

        cpu_p95 = float(row.get("cpu_p95", float("nan")) or float("nan"))
        cpu_p99 = float(row.get("cpu_p99", float("nan")) or float("nan"))
        memory_p95 = float(row.get("memory_p95", float("nan")) or float("nan"))
        network_in_p95 = float(row.get("network_in_p95", float("nan")) or float("nan"))
        network_out_p95 = float(row.get("network_out_p95", float("nan")) or float("nan"))
        composite_score = float(row.get("composite_score", 0.0) or 0.0)
        no_billing_data = bool(row.get("no_billing_data", True))

        # Net p95 for rationale (use whichever is larger)
        net_p95 = max(
            network_in_p95 if not math.isnan(network_in_p95) else 0.0,
            network_out_p95 if not math.isnan(network_out_p95) else 0.0,
        )

        # -----------------------------------------------------------------------
        # Resolve current shape config
        # -----------------------------------------------------------------------
        current_config = _get_shape_config(row, catalog, shape_name)
        current_monthly_cost = _current_monthly_cost(iid, cost_lookup.get(iid), collection_period_days)

        # -----------------------------------------------------------------------
        # STEP 2 – MONITOR: insufficient data
        # -----------------------------------------------------------------------
        if not sufficient_data:
            conf_result = compute_confidence(
                data_coverage_days=data_coverage_days,
                pattern=pattern_raw,
                has_memory_data=has_memory_data,
                cost_gap_days=15.0 if no_billing_data else 0.0,
            )
            rec = Recommendation(
                instance_id=iid,
                instance_name=instance_name,
                recommendation_type=RecommendationType.MONITOR,
                current_shape=shape_name,
                current_config=current_config,
                recommended_shape=None,
                recommended_config=None,
                current_monthly_cost=current_monthly_cost,
                estimated_monthly_cost=current_monthly_cost,
                estimated_monthly_savings=0.0,
                savings_pct=0.0,
                confidence_score=conf_result.score,
                confidence_label=conf_result.label,
                rationale=_build_rationale(
                    RecommendationType.MONITOR, pattern_raw,
                    cpu_p95, memory_p95, net_p95,
                    shape_name, 1.0, 0, 0, 0.0,
                ),
                prerequisites=[],
                risk_level=RiskLevel.LOW,
                rejected_alternatives=[],
            )
            recommendations.append(rec)
            log.debug("recommendation_monitor", instance_id=iid, coverage_days=data_coverage_days)
            continue

        # -----------------------------------------------------------------------
        # STEP 3 – UPSIZE / INVESTIGATE: high CPU p99
        # -----------------------------------------------------------------------
        if not math.isnan(cpu_p99) and cpu_p99 > _UPSIZE_CPU_P99_THRESHOLD:
            conf_result = compute_confidence(
                data_coverage_days=data_coverage_days,
                pattern=pattern_raw,
                has_memory_data=has_memory_data,
                cost_gap_days=15.0 if no_billing_data else 0.0,
            )
            risk = _determine_risk(
                RecommendationType.UPSIZE_OR_INVESTIGATE, pattern_raw, 0.0, cpu_p99
            )
            rationale = _build_rationale(
                RecommendationType.UPSIZE_OR_INVESTIGATE, pattern_raw,
                cpu_p95, memory_p95, net_p95,
                shape_name, 1.0, current_config.ocpu, current_config.ram_gb, 0.0,
            )
            rec = Recommendation(
                instance_id=iid,
                instance_name=instance_name,
                recommendation_type=RecommendationType.UPSIZE_OR_INVESTIGATE,
                current_shape=shape_name,
                current_config=current_config,
                recommended_shape=None,
                recommended_config=None,
                current_monthly_cost=current_monthly_cost,
                estimated_monthly_cost=current_monthly_cost,
                estimated_monthly_savings=0.0,
                savings_pct=0.0,
                confidence_score=conf_result.score,
                confidence_label=conf_result.label,
                rationale=rationale,
                prerequisites=[],
                risk_level=risk,
                rejected_alternatives=[],
            )
            recommendations.append(rec)
            log.debug("recommendation_upsize", instance_id=iid, cpu_p99=cpu_p99)
            continue

        # -----------------------------------------------------------------------
        # STEP 4 – IDLE → TERMINATE
        # -----------------------------------------------------------------------
        if pattern_raw == UtilizationPattern.IDLE.value:
            conf_result = compute_confidence(
                data_coverage_days=data_coverage_days,
                pattern=pattern_raw,
                has_memory_data=has_memory_data,
                cost_gap_days=15.0 if no_billing_data else 0.0,
            )
            rationale = _build_rationale(
                RecommendationType.TERMINATE, pattern_raw,
                cpu_p95, memory_p95, net_p95,
                shape_name, _SAFETY_MULTIPLIERS["IDLE"], 0, 0, 100.0,
            )
            rec = Recommendation(
                instance_id=iid,
                instance_name=instance_name,
                recommendation_type=RecommendationType.TERMINATE,
                current_shape=shape_name,
                current_config=current_config,
                recommended_shape=None,
                recommended_config=None,
                current_monthly_cost=current_monthly_cost,
                estimated_monthly_cost=0.0,
                estimated_monthly_savings=current_monthly_cost,
                savings_pct=100.0 if current_monthly_cost > 0 else 0.0,
                confidence_score=conf_result.score,
                confidence_label=conf_result.label,
                rationale=rationale,
                prerequisites=[
                    "Verify no scheduled traffic or cron jobs in next 30 days before terminating",
                    "Confirm instance is not used as a jump host or bastion",
                    "Snapshot any data volumes before terminating",
                ],
                risk_level=RiskLevel.HIGH,
                rejected_alternatives=[],
            )
            recommendations.append(rec)
            log.debug("recommendation_terminate", instance_id=iid)
            continue

        # -----------------------------------------------------------------------
        # STEP 5 – Compute required resources
        # -----------------------------------------------------------------------
        multiplier = _SAFETY_MULTIPLIERS.get(pattern_raw, _DEFAULT_MULTIPLIER)
        current_ocpu = current_config.ocpu
        current_ram_gb = current_config.ram_gb

        # Required OCPU
        if not math.isnan(cpu_p95) and cpu_p95 > 0:
            required_ocpu = max(1, math.ceil(cpu_p95 / 100.0 * current_ocpu * multiplier))
        else:
            required_ocpu = current_ocpu

        # Required RAM: do not downsize blindly if memory data is absent
        if math.isnan(memory_p95) or memory_p95 == 0.0:
            required_ram_gb = current_ram_gb
        else:
            required_ram_gb = max(1, math.ceil(memory_p95 / 100.0 * current_ram_gb * multiplier))

        # -----------------------------------------------------------------------
        # STEP 6 – BM/GPU guard — cannot auto-resize
        # -----------------------------------------------------------------------
        if _is_bm_or_gpu(shape_name):
            conf_result = compute_confidence(
                data_coverage_days=data_coverage_days,
                pattern=pattern_raw,
                has_memory_data=has_memory_data,
                cost_gap_days=15.0 if no_billing_data else 0.0,
            )
            rationale = (
                f"Shape {shape_name} is a bare-metal or GPU type that cannot be "
                f"automatically downsized to a flex configuration without explicit operator approval. "
                f"Current shape is treated as OPTIMAL."
            )
            rec = Recommendation(
                instance_id=iid,
                instance_name=instance_name,
                recommendation_type=RecommendationType.OPTIMAL,
                current_shape=shape_name,
                current_config=current_config,
                recommended_shape=None,
                recommended_config=None,
                current_monthly_cost=current_monthly_cost,
                estimated_monthly_cost=current_monthly_cost,
                estimated_monthly_savings=0.0,
                savings_pct=0.0,
                confidence_score=conf_result.score,
                confidence_label=conf_result.label,
                rationale=rationale,
                prerequisites=[],
                risk_level=RiskLevel.LOW,
                rejected_alternatives=[],
            )
            recommendations.append(rec)
            log.debug("recommendation_bm_gpu_optimal", instance_id=iid, shape=shape_name)
            continue

        # -----------------------------------------------------------------------
        # STEP 6 (continued) – Candidate lookup from catalog
        # -----------------------------------------------------------------------
        is_flex = _is_flex_shape(shape_name)
        current_family = _shape_family(shape_name)

        try:
            if is_flex:
                candidates: list[Shape] = catalog.candidates_for(
                    required_ocpu, required_ram_gb, same_family=current_family
                )
            else:
                candidates = catalog.candidates_for(
                    required_ocpu, required_ram_gb, same_family=None
                )
        except Exception as exc:
            log.warning("catalog_candidates_error", instance_id=iid, error=str(exc))
            candidates = []

        # -----------------------------------------------------------------------
        # STEP 7 – Evaluate candidates
        # -----------------------------------------------------------------------
        best_shape: Optional[Shape] = None
        best_new_monthly_cost: float = current_monthly_cost
        best_savings: float = 0.0
        best_savings_pct: float = 0.0
        best_opt_ocpu: int = required_ocpu
        best_opt_ram_gb: int = required_ram_gb
        rejected_alternatives: list[RejectedAlternative] = []

        for cand in candidates:
            try:
                # For flex shapes, pass required resources; for fixed shapes use shape defaults
                if hasattr(cand, "monthly_cost"):
                    if is_flex or _is_flex_shape(cand.name):
                        opt_ocpu = required_ocpu
                        opt_ram_gb = required_ram_gb
                        new_monthly = float(cand.monthly_cost(opt_ocpu, opt_ram_gb))
                    else:
                        opt_ocpu = cand.ocpu
                        opt_ram_gb = cand.ram_gb
                        new_monthly = float(cand.monthly_cost(opt_ocpu, opt_ram_gb))
                else:
                    # Fallback: no monthly_cost method
                    opt_ocpu = getattr(cand, "ocpu", required_ocpu)
                    opt_ram_gb = getattr(cand, "ram_gb", required_ram_gb)
                    new_monthly = 0.0
            except Exception as exc:
                log.warning("candidate_cost_error", candidate=getattr(cand, "name", str(cand)), error=str(exc))
                continue

            savings = current_monthly_cost - new_monthly
            spct = (savings / current_monthly_cost * 100.0) if current_monthly_cost > 0 else 0.0

            cand_name = getattr(cand, "name", str(cand))

            if best_shape is None and savings > _MIN_SAVINGS_ABS and spct > _MIN_SAVINGS_PCT:
                best_shape = cand
                best_new_monthly_cost = new_monthly
                best_savings = savings
                best_savings_pct = spct
                best_opt_ocpu = opt_ocpu
                best_opt_ram_gb = opt_ram_gb
            else:
                # Track as rejected alternative (up to _MAX_REJECTED)
                if len(rejected_alternatives) < _MAX_REJECTED:
                    if savings <= _MIN_SAVINGS_ABS:
                        reason = (
                            f"Absolute savings ${savings:.2f}/mo below "
                            f"${_MIN_SAVINGS_ABS:.0f} threshold"
                        )
                    elif spct <= _MIN_SAVINGS_PCT:
                        reason = (
                            f"Savings {spct:.1f}% below {_MIN_SAVINGS_PCT:.0f}% threshold"
                        )
                    else:
                        reason = "Better candidate already selected"
                    rejected_alternatives.append(
                        RejectedAlternative(
                            shape_name=cand_name,
                            ocpu=opt_ocpu,
                            ram_gb=opt_ram_gb,
                            monthly_cost=new_monthly,
                            rejection_reason=reason,
                        )
                    )

        # -----------------------------------------------------------------------
        # STEP 8 & 9 – Determine final recommendation type
        # -----------------------------------------------------------------------
        if best_shape is None:
            # No candidate passed the filter → current shape is optimal
            final_type = RecommendationType.OPTIMAL
            recommended_shape_name: Optional[str] = None
            recommended_config: Optional[ShapeConfig] = None
            final_monthly = current_monthly_cost
            final_savings = 0.0
            final_savings_pct = 0.0
        else:
            cand_name = getattr(best_shape, "name", str(best_shape))
            # Check if the best candidate IS the current shape/config
            same_shape = cand_name == shape_name
            same_config = (best_opt_ocpu == current_ocpu and best_opt_ram_gb == current_ram_gb)
            if same_shape and same_config:
                final_type = RecommendationType.OPTIMAL
                recommended_shape_name = None
                recommended_config = None
                final_monthly = current_monthly_cost
                final_savings = 0.0
                final_savings_pct = 0.0
            else:
                final_type = RecommendationType.DOWNSIZE
                recommended_shape_name = cand_name
                recommended_config = ShapeConfig(ocpu=best_opt_ocpu, ram_gb=best_opt_ram_gb)
                final_monthly = best_new_monthly_cost
                final_savings = best_savings
                final_savings_pct = best_savings_pct

        # -----------------------------------------------------------------------
        # STEP 10 – Confidence scoring
        # -----------------------------------------------------------------------
        cost_gap_days = 15.0 if no_billing_data else 0.0
        conf_result = compute_confidence(
            data_coverage_days=data_coverage_days,
            pattern=pattern_raw,
            has_memory_data=has_memory_data,
            cost_gap_days=cost_gap_days,
        )

        # -----------------------------------------------------------------------
        # STEP 11 – Risk level
        # -----------------------------------------------------------------------
        risk = _determine_risk(final_type, pattern_raw, final_savings_pct, cpu_p99)

        # -----------------------------------------------------------------------
        # STEP 12 – Rationale
        # -----------------------------------------------------------------------
        rationale = _build_rationale(
            final_type, pattern_raw,
            cpu_p95, memory_p95, net_p95,
            shape_name, multiplier, required_ocpu, required_ram_gb, final_savings_pct,
        )

        rec = Recommendation(
            instance_id=iid,
            instance_name=instance_name,
            recommendation_type=final_type,
            current_shape=shape_name,
            current_config=current_config,
            recommended_shape=recommended_shape_name,
            recommended_config=recommended_config,
            current_monthly_cost=current_monthly_cost,
            estimated_monthly_cost=final_monthly,
            estimated_monthly_savings=final_savings,
            savings_pct=final_savings_pct,
            confidence_score=conf_result.score,
            confidence_label=conf_result.label,
            rationale=rationale,
            prerequisites=[],
            risk_level=risk,
            rejected_alternatives=rejected_alternatives,
        )
        recommendations.append(rec)

        log.debug(
            "recommendation_generated",
            instance_id=iid,
            rec_type=final_type.value,
            savings=round(final_savings, 2),
            confidence=conf_result.label.value,
        )

    log.info(
        "generate_recommendations_complete",
        total=len(recommendations),
        downsize=sum(1 for r in recommendations if r.recommendation_type == RecommendationType.DOWNSIZE),
        terminate=sum(1 for r in recommendations if r.recommendation_type == RecommendationType.TERMINATE),
        optimal=sum(1 for r in recommendations if r.recommendation_type == RecommendationType.OPTIMAL),
        monitor=sum(1 for r in recommendations if r.recommendation_type == RecommendationType.MONITOR),
        upsize=sum(1 for r in recommendations if r.recommendation_type == RecommendationType.UPSIZE_OR_INVESTIGATE),
    )

    return recommendations
