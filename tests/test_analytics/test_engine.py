"""End-to-end tests for AnalyticsEngine.run()."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.analytics.engine import AnalyticsEngine, AnalyticsResult, _AnalyticsEncoder


# ── happy path ────────────────────────────────────────────────────────────────

def test_engine_run_returns_analytics_result(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    assert isinstance(result, AnalyticsResult)


def test_engine_result_has_recommendations(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    assert isinstance(result.recommendations, list)


def test_engine_result_has_fleet_kpis(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    assert result.fleet_kpis is not None


def test_engine_result_has_anomalies_list(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    assert isinstance(result.anomalies, list)


def test_engine_result_validation_report(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    assert result.validation_report is not None
    assert result.validation_report.total_records > 0


def test_engine_result_period_dates(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    assert result.period_start is not None
    assert result.period_end is not None


def test_engine_schema_version(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    assert result.schema_version == "1.0.0"


# ── scenario fixture (real mixed data) ───────────────────────────────────────

def test_engine_scenario_fixture_non_empty_recs(raw_json_path, empty_config):
    result = AnalyticsEngine(empty_config).run(raw_json_path)
    assert isinstance(result, AnalyticsResult)
    assert len(result.recommendations) > 0


# ── error cases ───────────────────────────────────────────────────────────────

def test_engine_missing_file_raises(tmp_path, empty_config):
    with pytest.raises(FileNotFoundError):
        AnalyticsEngine(empty_config).run(tmp_path / "nonexistent.json")


# ── JSON serialization round-trip ─────────────────────────────────────────────

def test_engine_result_json_serializable(minimal_raw_path, empty_config):
    result = AnalyticsEngine(empty_config).run(minimal_raw_path)
    serialized = json.dumps(asdict(result), cls=_AnalyticsEncoder)
    data = json.loads(serialized)
    assert "recommendations" in data
    assert "fleet_kpis" in data
    assert "anomalies" in data
    assert data["schema_version"] == "1.0.0"
