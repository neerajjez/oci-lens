"""
src/reporter/narrative.py
==========================
Auto-generates plain-English narrative paragraphs from AnalyticsResult.
All functions return a single str.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def executive_paragraph(result: "AnalyticsResult") -> str:
    """
    3–5 sentence fleet overview for the executive summary page.

    Example output:
    "Across 42 compute instances analyzed over 15 days, the fleet incurred
    $18,450 in compute and storage charges ($36,900 monthly run rate).
    14 instances (33%) are operating below the 30% composite utilization
    threshold, representing an estimated $3,200/month in recoverable spend.
    Of these, 9 are high-confidence right-sizing opportunities totaling
    $2,800/month. 3 anomalies were flagged, including 1 idle instance and
    1 stranded storage volume."
    """
    kpis = result.fleet_kpis
    recs = result.recommendations
    anomalies = result.anomalies

    n_instances = (
        (kpis.overprovisioned_count or 0)
        + (kpis.rightsized_count or 0)
        + (kpis.underprovisioned_count or 0)
        + (kpis.idle_count or 0)
        + (kpis.insufficient_data_count or 0)
    )

    period_start = result.period_start.date() if result.period_start else "?"
    period_end = result.period_end.date() if result.period_end else "?"
    period_days = max(1, (result.period_end - result.period_start).days) if result.period_end and result.period_start else 15

    total_cost = float(kpis.total_fleet_cost_period or 0)
    monthly_rate = float(kpis.total_fleet_cost_monthly_run_rate or 0)
    savings = float(kpis.total_potential_monthly_savings or 0)
    savings_pct = float(kpis.savings_opportunity_pct or 0)

    from src.analytics.right_sizer import RecommendationType
    from src.analytics.confidence import ConfidenceLabel

    high_conf_recs = [
        r for r in recs
        if (
            r.recommendation_type in (RecommendationType.DOWNSIZE, RecommendationType.TERMINATE)
            and r.confidence_label == ConfidenceLabel.HIGH
        )
    ]
    high_conf_savings = sum(r.estimated_monthly_savings for r in high_conf_recs)
    zombie_count = sum(1 for a in anomalies if a.signal == "zombie")
    stranded_count = sum(1 for a in anomalies if a.signal == "stranded_volume")
    total_anomalies = len(anomalies)

    parts = []

    if n_instances > 0:
        parts.append(
            f"Across {n_instances} compute instance{'s' if n_instances != 1 else ''} "
            f"analyzed over {period_days} days ({period_start} to {period_end}), "
            f"the fleet incurred ${total_cost:,.0f} in compute and storage charges "
            f"(${monthly_rate:,.0f}/month run rate)."
        )
    else:
        return "No instances were found in the configured compartments for this analysis period."

    if savings > 0:
        overprov = kpis.overprovisioned_count or 0
        overprov_pct = (overprov / n_instances * 100) if n_instances > 0 else 0
        parts.append(
            f"{overprov} instance{'s' if overprov != 1 else ''} ({overprov_pct:.0f}%) "
            f"are operating below the composite utilization threshold, representing an "
            f"estimated ${savings:,.0f}/month ({savings_pct:.1f}%) in recoverable spend."
        )
        if high_conf_recs:
            parts.append(
                f"Of these, {len(high_conf_recs)} are high-confidence right-sizing "
                f"opportunities totaling ${high_conf_savings:,.0f}/month."
            )
    else:
        parts.append(
            "The fleet is well-optimized; no significant right-sizing opportunities "
            "were identified this period."
        )

    if total_anomalies > 0:
        anomaly_details = []
        if zombie_count:
            anomaly_details.append(f"{zombie_count} idle instance{'s' if zombie_count != 1 else ''}")
        if stranded_count:
            anomaly_details.append(
                f"{stranded_count} stranded storage volume{'s' if stranded_count != 1 else ''}"
            )
        detail_str = (
            ", including " + " and ".join(anomaly_details)
            if anomaly_details
            else ""
        )
        parts.append(
            f"{total_anomalies} anomal{'ies' if total_anomalies != 1 else 'y'} "
            f"{'were' if total_anomalies != 1 else 'was'} flagged{detail_str}."
        )

    return " ".join(parts)


def top_recommendations_paragraph(result: "AnalyticsResult") -> str:
    """Highlight the top 3 savings opportunities."""
    from src.analytics.right_sizer import RecommendationType

    actionable = [
        r for r in result.recommendations
        if r.recommendation_type in (RecommendationType.DOWNSIZE, RecommendationType.TERMINATE)
    ]
    actionable.sort(key=lambda r: r.estimated_monthly_savings, reverse=True)
    top3 = actionable[:3]

    if not top3:
        return "No actionable right-sizing recommendations were identified this period."

    lines = []
    for i, rec in enumerate(top3, 1):
        action = "Downsizing" if rec.recommendation_type == RecommendationType.DOWNSIZE else "Terminating"
        lines.append(
            f"{i}. {action} {rec.instance_name} "
            f"({rec.current_shape} → {rec.recommended_shape or 'n/a'}) "
            f"saves ${rec.estimated_monthly_savings:,.0f}/month "
            f"({rec.confidence_label.value} confidence)."
        )

    total = sum(r.estimated_monthly_savings for r in top3)
    lines.append(f"These three actions alone would recover ${total:,.0f}/month.")
    return " ".join(lines)


def anomaly_summary_paragraph(result: "AnalyticsResult") -> str:
    """Summarize anomalies. Returns empty string if none detected."""
    if not result.anomalies:
        return ""

    from src.analytics.anomaly import AnomalySeverity

    critical = [a for a in result.anomalies if a.severity == AnomalySeverity.CRITICAL]
    warnings = [a for a in result.anomalies if a.severity == AnomalySeverity.WARNING]
    total_recoverable = sum(a.estimated_recoverable_amount for a in result.anomalies)

    parts = [
        f"{len(result.anomalies)} anomal{'ies' if len(result.anomalies) != 1 else 'y'} "
        f"{'were' if len(result.anomalies) != 1 else 'was'} detected this period."
    ]
    if critical:
        parts.append(
            f"{len(critical)} critical issue{'s' if len(critical) != 1 else ''} "
            f"require immediate attention."
        )
    if warnings:
        parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''} should be reviewed.")
    if total_recoverable > 0:
        parts.append(
            f"Total estimated recoverable amount: ${total_recoverable:,.0f}/month."
        )
    return " ".join(parts)


def trend_summary_paragraph(result: "AnalyticsResult") -> str:
    """Period-over-period comparison. Returns suppressed message if no previous run."""
    kpis = result.fleet_kpis

    if kpis.trend_unavailable_reason:
        return (
            "This is the first run; trend metrics will be available from the next report."
            if "first" in (kpis.trend_unavailable_reason or "").lower()
            else f"Trend data unavailable: {kpis.trend_unavailable_reason}"
        )

    cost_trend = kpis.fleet_cost_trend_pct
    util_trend = kpis.utilization_trend_pct

    if cost_trend is None and util_trend is None:
        return "Trend data is not available for this reporting period."

    parts = []
    if cost_trend is not None:
        direction = "increased" if cost_trend > 0 else "decreased"
        parts.append(f"Fleet cost {direction} by {abs(cost_trend):.1f}% vs. the previous period.")
    if util_trend is not None:
        direction = "improved" if util_trend > 0 else "declined"
        parts.append(f"Average composite utilization {direction} by {abs(util_trend):.1f} points.")
    return " ".join(parts)
