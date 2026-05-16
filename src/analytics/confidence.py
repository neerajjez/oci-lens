from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ConfidenceLabel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ConfidenceResult:
    score: float
    label: ConfidenceLabel
    penalties: list[str] = field(default_factory=list)
    bonuses: list[str] = field(default_factory=list)


def compute_confidence(
    data_coverage_days: float,
    pattern: str,           # UtilizationPattern.value string e.g. "STEADY"
    has_memory_data: bool,
    cost_gap_days: float,
) -> ConfidenceResult:
    """
    Compute recommendation confidence score in [0.0, 1.0].

    base_score = 1.0
    Penalties (subtract):
      - 0.20 if data_coverage_days < 14
      - 0.15 if pattern == "ERRATIC"
      - 0.10 if not has_memory_data
      - 0.10 if cost_gap_days > 7
    Bonuses (add):
      + 0.10 if pattern == "STEADY"
    Final: clamped to [0.0, 1.0]

    Labels:
      >= 0.80 -> HIGH
      >= 0.55 -> MEDIUM
      <  0.55 -> LOW
    """
    base_score = 1.0
    penalties: list[str] = []
    bonuses: list[str] = []

    if data_coverage_days < 14:
        penalties.append(
            f"data coverage {data_coverage_days:.1f} days < 14 (-0.20)"
        )
        base_score -= 0.20

    if pattern == "ERRATIC":
        penalties.append("utilization pattern is ERRATIC (-0.15)")
        base_score -= 0.15

    if not has_memory_data:
        penalties.append("no memory utilization data available (-0.10)")
        base_score -= 0.10

    if cost_gap_days > 7:
        penalties.append(
            f"cost data gap {cost_gap_days:.1f} days > 7 (-0.10)"
        )
        base_score -= 0.10

    if pattern == "STEADY":
        bonuses.append("utilization pattern is STEADY (+0.10)")
        base_score += 0.10

    score = max(0.0, min(1.0, base_score))

    if score >= 0.80:
        label = ConfidenceLabel.HIGH
    elif score >= 0.55:
        label = ConfidenceLabel.MEDIUM
    else:
        label = ConfidenceLabel.LOW

    return ConfidenceResult(
        score=score,
        label=label,
        penalties=penalties,
        bonuses=bonuses,
    )
