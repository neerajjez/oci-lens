"""Tests for PipelineRunner."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.orchestrator.pipeline import PipelineRunner
from src.orchestrator.steps import RunContext, Step, StepResult


# ── stub helpers ──────────────────────────────────────────────────────────────

def _ok(name: str, critical: bool = True) -> Step:
    s = MagicMock(spec=Step)
    s.name = name
    s.critical = critical
    s.run.return_value = StepResult(step_name=name, status="success")
    return s


def _fail(name: str, critical: bool = True) -> Step:
    s = MagicMock(spec=Step)
    s.name = name
    s.critical = critical
    s.run.return_value = StepResult(step_name=name, status="failed", error="boom")
    return s


def _cleanup() -> Step:
    s = MagicMock(spec=Step)
    s.name = "cleanup"
    s.critical = False
    s.run.return_value = StepResult(step_name="cleanup", status="success")
    return s


# ── happy path ────────────────────────────────────────────────────────────────

def test_happy_path_all_succeed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = PipelineRunner({}, steps=[_ok("s1"), _ok("s2"), _cleanup()])
    result = runner.run()
    assert result.success
    assert result.status == "success"


# ── critical failure skips downstream steps ───────────────────────────────────

def test_critical_failure_skips_downstream(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s1, s2, s3, cu = _ok("s1"), _fail("s2"), _ok("s3"), _cleanup()
    runner = PipelineRunner({}, steps=[s1, s2, s3, cu])
    result = runner.run()

    assert not result.success
    statuses = {sr.step_name: sr.status for sr in result.step_results}
    assert statuses["s1"] == "success"
    assert statuses["s2"] == "failed"
    assert statuses["s3"] == "skipped"
    assert statuses["cleanup"] == "success"
    s3.run.assert_not_called()
    cu.run.assert_called_once()


# ── cleanup always runs ───────────────────────────────────────────────────────

def test_cleanup_always_runs_after_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cu = _cleanup()
    runner = PipelineRunner({}, steps=[_fail("s1", critical=True), cu])
    runner.run()
    cu.run.assert_called_once()


# ── non-critical failure does not abort ──────────────────────────────────────

def test_non_critical_failure_does_not_abort(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s1, s2, s3, cu = _ok("s1"), _fail("s2", critical=False), _ok("s3"), _cleanup()
    runner = PipelineRunner({}, steps=[s1, s2, s3, cu])
    result = runner.run()
    assert result.success
    s3.run.assert_called_once()


# ── skip_notify propagated ────────────────────────────────────────────────────

def test_skip_notify_in_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured: list[RunContext] = []

    class Cap(Step):
        name = "cap"
        critical = False
        def execute(self, ctx: RunContext) -> StepResult:
            captured.append(ctx)
            return StepResult(step_name=self.name, status="success")

    PipelineRunner({}, steps=[Cap(), _cleanup()]).run(skip_notify=True)
    assert captured[0].skip_notify is True


# ── dry_run propagated ────────────────────────────────────────────────────────

def test_dry_run_in_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured: list[RunContext] = []

    class Cap(Step):
        name = "cap"
        critical = False
        def execute(self, ctx: RunContext) -> StepResult:
            captured.append(ctx)
            return StepResult(step_name=self.name, status="success")

    PipelineRunner({}, steps=[Cap(), _cleanup()]).run(dry_run=True)
    assert captured[0].dry_run is True


# ── run log written ───────────────────────────────────────────────────────────

def test_run_log_appended(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = PipelineRunner({}, steps=[_ok("s1"), _cleanup()])
    result = runner.run()

    log_path = tmp_path / "reports" / "run_log.jsonl"
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert entry["run_id"] == result.run_id
    assert entry["status"] == "success"


# ── resume reuses completed steps ────────────────────────────────────────────

def test_resume_skips_completed_steps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s1, s2, cu = _ok("s1"), _ok("s2"), _cleanup()
    first = PipelineRunner({}, steps=[s1, s2, cu]).run()

    s1.run.reset_mock()
    s2.run.reset_mock()

    PipelineRunner({}, steps=[s1, s2, cu]).run(resume_run_id=first.run_id)
    s1.run.assert_not_called()
    s2.run.assert_not_called()
