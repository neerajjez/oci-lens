"""Tests for src/orchestrator/steps.py."""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.orchestrator.steps import (
    AnalyzeDataStep,
    CleanupStep,
    CollectDataStep,
    DispatchNotificationsStep,
    GenerateReportStep,
    RunContext,
    Step,
    StepResult,
    ValidateConfigStep,
)


def _ctx(**kw) -> RunContext:
    base = dict(run_id="test001", config={}, dry_run=False, skip_notify=False)
    base.update(kw)
    return RunContext(**base)


# ── StepResult / RunContext ───────────────────────────────────────────────────

def test_step_result_defaults():
    r = StepResult(step_name="x", status="success")
    assert r.artifact_path is None
    assert r.error is None
    assert r.duration_s == 0.0


def test_run_context_defaults():
    ctx = RunContext(run_id="abc", config={})
    assert not ctx.dry_run
    assert not ctx.skip_notify
    assert ctx.raw_data_path is None


# ── Step.run() exception handling ─────────────────────────────────────────────

class _BrokenStep(Step):
    name = "broken"

    def execute(self, context: RunContext) -> StepResult:
        raise RuntimeError("boom")


def test_step_run_catches_exception():
    result = _BrokenStep().run(_ctx())
    assert result.status == "failed"
    assert "boom" in result.error
    assert result.duration_s >= 0.0


def test_step_run_records_duration_on_success():
    class _OkStep(Step):
        name = "ok"

        def execute(self, context: RunContext) -> StepResult:
            return StepResult(step_name="ok", status="success")

    result = _OkStep().run(_ctx())
    assert result.status == "success"
    assert result.duration_s >= 0.0


# ── ValidateConfigStep ────────────────────────────────────────────────────────

def test_validate_config_step_success():
    with patch("src.config.loader.validate_config", return_value=[]):
        result = ValidateConfigStep().execute(_ctx())
    assert result.status == "success"
    assert result.step_name == "validate_config"


def test_validate_config_step_failure():
    with patch("src.config.loader.validate_config", return_value=["missing compartment"]):
        result = ValidateConfigStep().execute(_ctx())
    assert result.status == "failed"
    assert "missing compartment" in result.error


def test_validate_config_step_multiple_issues():
    with patch("src.config.loader.validate_config", return_value=["issue1", "issue2"]):
        result = ValidateConfigStep().execute(_ctx())
    assert "issue1" in result.error
    assert "issue2" in result.error


# ── CollectDataStep ───────────────────────────────────────────────────────────

def test_collect_data_dry_run():
    result = CollectDataStep().execute(_ctx(dry_run=True))
    assert result.status == "skipped"


def test_collect_data_reuses_existing_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "reports" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "test001_raw.json").write_text("{}")
    ctx = _ctx()
    result = CollectDataStep().execute(ctx)
    assert result.status == "success"
    assert ctx.raw_data_path is not None


def test_collect_data_runs_collector(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _ctx()
    mock_instance = MagicMock()
    with patch("src.collector.runner.CollectorRunner", return_value=mock_instance):
        result = CollectDataStep().execute(ctx)
    assert result.status == "success"
    mock_instance.run.assert_called_once()
    assert ctx.raw_data_path is not None


# ── AnalyzeDataStep ───────────────────────────────────────────────────────────

def test_analyze_data_dry_run():
    result = AnalyzeDataStep().execute(_ctx(dry_run=True))
    assert result.status == "skipped"


def test_analyze_data_reuses_existing_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    analytics_dir = tmp_path / "reports" / "analytics"
    analytics_dir.mkdir(parents=True)
    (analytics_dir / "test001_analytics.json").write_text("{}")
    ctx = _ctx()
    mock_engine = MagicMock()
    with patch("src.analytics.engine.AnalyticsEngine", return_value=mock_engine):
        result = AnalyzeDataStep().execute(ctx)
    assert result.status == "success"
    assert ctx.analytics_path is not None


def test_analyze_data_full_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _ctx()
    ctx.raw_data_path = tmp_path / "dummy_raw.json"
    mock_engine = MagicMock()
    mock_engine.run.return_value = MagicMock()
    with patch("src.analytics.engine.AnalyticsEngine", return_value=mock_engine):
        result = AnalyzeDataStep().execute(ctx)
    assert result.status == "success"
    mock_engine.run.assert_called_once()
    assert ctx.run_result is not None


# ── GenerateReportStep ────────────────────────────────────────────────────────

def test_generate_report_dry_run():
    result = GenerateReportStep().execute(_ctx(dry_run=True))
    assert result.status == "skipped"


def test_generate_report_reuses_existing_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_dir = tmp_path / "reports" / "pdf"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "test001_report.pdf").write_bytes(b"%PDF-1.4")
    ctx = _ctx()
    ctx.run_result = MagicMock()
    result = GenerateReportStep().execute(ctx)
    assert result.status == "success"
    assert ctx.report_path is not None


def test_generate_report_full_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _ctx()
    ctx.run_result = MagicMock()
    meta = MagicMock()
    meta.path = tmp_path / "reports" / "pdf" / "test001_report.pdf"
    meta.page_count = 5
    mock_builder = MagicMock()
    mock_builder.build.return_value = meta
    with patch("src.reporter.ReportBuilder", return_value=mock_builder):
        result = GenerateReportStep().execute(ctx)
    assert result.status == "success"
    mock_builder.build.assert_called_once()


# ── DispatchNotificationsStep ─────────────────────────────────────────────────

def test_dispatch_skipped_when_skip_notify():
    result = DispatchNotificationsStep().execute(_ctx(skip_notify=True))
    assert result.status == "skipped"


def test_dispatch_skipped_when_dry_run():
    result = DispatchNotificationsStep().execute(_ctx(dry_run=True))
    assert result.status == "skipped"


def test_dispatch_all_failed():
    dispatch_result = MagicMock()
    dispatch_result.all_failed = True
    mock_dispatcher = MagicMock()
    mock_dispatcher.send.return_value = dispatch_result
    with patch("src.notifier.NotificationDispatcher", return_value=mock_dispatcher), \
         patch("src.notifier.SMTPEmailChannel"), \
         patch("src.notifier.SlackChannel"), \
         patch("src.notifier.TeamsChannel"):
        result = DispatchNotificationsStep().execute(_ctx())
    assert result.status == "failed"


def test_dispatch_success():
    dispatch_result = MagicMock()
    dispatch_result.all_failed = False
    dispatch_result.success = True
    dispatch_result.partial = False
    mock_dispatcher = MagicMock()
    mock_dispatcher.send.return_value = dispatch_result
    with patch("src.notifier.NotificationDispatcher", return_value=mock_dispatcher), \
         patch("src.notifier.SMTPEmailChannel"), \
         patch("src.notifier.SlackChannel"), \
         patch("src.notifier.TeamsChannel"):
        result = DispatchNotificationsStep().execute(_ctx())
    assert result.status == "success"


# ── CleanupStep ───────────────────────────────────────────────────────────────

def test_cleanup_skipped_when_keep_days_zero():
    ctx = _ctx(config={"cleanup": {"keep_raw_days": 0}})
    result = CleanupStep().execute(ctx)
    assert result.status == "skipped"


def test_cleanup_no_raw_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CleanupStep().execute(_ctx(config={"cleanup": {"keep_raw_days": 1}}))
    assert result.status == "success"


def test_cleanup_removes_old_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "reports" / "raw"
    raw_dir.mkdir(parents=True)
    old_file = raw_dir / "old_raw.json"
    old_file.write_text("{}")
    old_mtime = time.time() - (10 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))
    result = CleanupStep().execute(_ctx(config={"cleanup": {"keep_raw_days": 7}}))
    assert result.status == "success"
    assert not old_file.exists()


def test_cleanup_keeps_recent_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw_dir = tmp_path / "reports" / "raw"
    raw_dir.mkdir(parents=True)
    new_file = raw_dir / "new_raw.json"
    new_file.write_text("{}")
    result = CleanupStep().execute(_ctx(config={"cleanup": {"keep_raw_days": 7}}))
    assert result.status == "success"
    assert new_file.exists()
