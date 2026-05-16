"""
Shared fixtures for test_reporter: 3 AnalyticsResult scenarios.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from src.analytics.anomaly import Anomaly, AnomalySeverity
from src.analytics.confidence import ConfidenceLabel
from src.analytics.engine import AnalyticsResult
from src.analytics.loader import ValidationReport
from src.analytics.ratios import FleetKPIs
from src.analytics.right_sizer import (
    Recommendation, RecommendationType, RiskLevel, ShapeConfig,
)


def _kpis(
    total_cost=5000.0,
    monthly_rate=10000.0,
    savings=2000.0,
    orphaned=100.0,
    overprov=5,
    rightsz=10,
    underprov=2,
    idle=3,
    insuff=0,
) -> FleetKPIs:
    return FleetKPIs(
        total_fleet_cost_period=total_cost,
        total_fleet_cost_monthly_run_rate=monthly_rate,
        orphaned_resource_cost=orphaned,
        total_potential_monthly_savings=savings,
        savings_opportunity_pct=(savings / monthly_rate * 100) if monthly_rate > 0 else 0,
        net_recoverable_savings=savings - 50 * (overprov + idle),
        fleet_avg_cpu_utilization=22.5,
        fleet_avg_memory_utilization=30.0,
        weighted_composite_score=0.35,
        overprovisioned_count=overprov,
        rightsized_count=rightsz,
        underprovisioned_count=underprov,
        idle_count=idle,
        insufficient_data_count=insuff,
        cost_efficiency_index=0.35,
        top_5_wasteful=[
            {"display_name": f"waste-{i}", "total_cost": 500.0 - i * 50, "composite_score": 0.1 + i * 0.05}
            for i in range(5)
        ],
        top_5_efficient=[
            {"display_name": f"eff-{i}", "total_cost": 200.0, "composite_score": 0.8 + i * 0.02}
            for i in range(5)
        ],
        fleet_cost_trend_pct=None,
        utilization_trend_pct=None,
        trend_unavailable_reason="No previous run available — first run",
    )


def _rec(
    idx: int,
    rec_type: RecommendationType = RecommendationType.DOWNSIZE,
    savings: float = 200.0,
    confidence: ConfidenceLabel = ConfidenceLabel.HIGH,
) -> Recommendation:
    return Recommendation(
        instance_id=f"ocid1.instance.oc1.phx.instance{idx:04d}",
        instance_name=f"test-instance-{idx:02d}",
        recommendation_type=rec_type,
        current_shape="VM.Standard.E4.Flex",
        current_config=ShapeConfig(ocpu=4, ram_gb=60),
        recommended_shape="VM.Standard.E4.Flex" if rec_type != RecommendationType.TERMINATE else None,
        recommended_config=ShapeConfig(ocpu=2, ram_gb=32) if rec_type != RecommendationType.TERMINATE else None,
        current_monthly_cost=savings * 2,
        estimated_monthly_cost=savings,
        estimated_monthly_savings=savings,
        savings_pct=50.0,
        confidence_score=0.85 if confidence == ConfidenceLabel.HIGH else 0.60,
        confidence_label=confidence,
        rationale=f"Instance {idx} is consistently below 20% CPU utilization.",
        prerequisites=["Verify no scheduled batch jobs", "Confirm with application team"],
        risk_level=RiskLevel.LOW,
        rejected_alternatives=[],
    )


def _anomaly(signal: str = "zombie", severity: AnomalySeverity = AnomalySeverity.CRITICAL) -> Anomaly:
    return Anomaly(
        signal=signal,
        resource_id="ocid1.instance.oc1.phx.xxx",
        resource_name="idle-server-01",
        severity=severity,
        description="CPU p95 < 5% for entire collection period",
        suggested_action="Verify no traffic, then terminate",
        estimated_recoverable_amount=150.0,
    )


def _validation() -> ValidationReport:
    return ValidationReport(total_records=0)


def _base_result(
    kpis: FleetKPIs,
    recs: list,
    anomalies: list,
) -> AnalyticsResult:
    now = datetime.now(timezone.utc)
    return AnalyticsResult(
        schema_version="1.0.0",
        generated_at=now,
        period_start=datetime(2026, 3, 23, tzinfo=timezone.utc),
        period_end=datetime(2026, 4, 7, tzinfo=timezone.utc),
        raw_input_path="tests/fixtures/scenario_mixed_raw.json",
        validation_report=_validation(),
        recommendations=recs,
        fleet_kpis=kpis,
        anomalies=anomalies,
    )


@pytest.fixture
def healthy_result() -> AnalyticsResult:
    """Fleet where all instances are right-sized, no anomalies."""
    kpis = _kpis(savings=0, overprov=0, rightsz=10, underprov=0, idle=0)
    recs = [_rec(i, RecommendationType.OPTIMAL, savings=0) for i in range(5)]
    return _base_result(kpis, recs, [])


@pytest.fixture
def wasteful_result() -> AnalyticsResult:
    """Fleet with many over-provisioned instances and anomalies."""
    kpis = _kpis(savings=3500.0, overprov=10, rightsz=2, underprov=1, idle=5)
    recs = (
        [_rec(i, RecommendationType.DOWNSIZE, savings=300.0) for i in range(10)]
        + [_rec(i + 10, RecommendationType.TERMINATE, savings=150.0) for i in range(5)]
        + [_rec(i + 15, RecommendationType.UPSIZE_OR_INVESTIGATE, savings=0) for i in range(1)]
    )
    anomalies = [
        _anomaly("zombie", AnomalySeverity.CRITICAL),
        _anomaly("cost_outlier", AnomalySeverity.WARNING),
        _anomaly("stranded_volume", AnomalySeverity.INFO),
    ]
    return _base_result(kpis, recs, anomalies)


@pytest.fixture
def mixed_result() -> AnalyticsResult:
    """Mixed fleet: some right-sized, some over-provisioned, a few anomalies."""
    kpis = _kpis(savings=1200.0, overprov=4, rightsz=8, underprov=2, idle=2)
    recs = (
        [_rec(i, RecommendationType.DOWNSIZE, savings=250.0) for i in range(4)]
        + [_rec(i + 4, RecommendationType.OPTIMAL, savings=0) for i in range(8)]
        + [_rec(i + 12, RecommendationType.MONITOR, savings=0,
                confidence=ConfidenceLabel.LOW) for i in range(2)]
    )
    anomalies = [_anomaly("zombie", AnomalySeverity.CRITICAL)]
    return _base_result(kpis, recs, anomalies)
