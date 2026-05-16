"""Tests for RunStateManager."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.orchestrator.state import RunStateManager, _ORPHAN_THRESHOLD_S


# ── create / load ─────────────────────────────────────────────────────────────

def test_create_writes_state_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("run001")
    state = mgr.load_or_create()
    assert state["run_id"] == "run001"
    assert state["status"] == "running"
    assert (tmp_path / "reports" / "state" / "run001.json").exists()


def test_load_existing_state_persists_steps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("run002")
    mgr.load_or_create()
    mgr.complete_step("step_a")

    mgr2 = RunStateManager("run002")
    state = mgr2.load_or_create()
    assert "step_a" in state["completed_steps"]


# ── step tracking ─────────────────────────────────────────────────────────────

def test_complete_step_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("run003")
    mgr.load_or_create()
    mgr.complete_step("step_a")
    mgr.complete_step("step_a")
    assert mgr._state["completed_steps"].count("step_a") == 1


def test_is_step_done_false_then_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("run004")
    mgr.load_or_create()
    assert not mgr.is_step_done("step_a")
    mgr.complete_step("step_a")
    assert mgr.is_step_done("step_a")


def test_artifact_stored_and_retrieved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("run005")
    mgr.load_or_create()
    artifact = tmp_path / "reports" / "raw" / "run005_raw.json"
    mgr.complete_step("collect_data", artifact_path=artifact)
    assert mgr.artifact_for("collect_data") == artifact


def test_artifact_none_for_unknown_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("run006")
    mgr.load_or_create()
    assert mgr.artifact_for("nonexistent") is None


# ── mark complete ─────────────────────────────────────────────────────────────

def test_mark_complete_sets_status_and_finished_at(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("run007")
    mgr.load_or_create()
    mgr.mark_complete("success")
    assert mgr._state["status"] == "success"
    assert "finished_at" in mgr._state


# ── orphan detection ──────────────────────────────────────────────────────────

def test_scan_returns_empty_when_no_state_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert RunStateManager.scan_orphans() == []


def test_scan_detects_stale_orphan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "reports" / "state"
    state_dir.mkdir(parents=True)

    stale = state_dir / "stale001.json"
    stale.write_text(json.dumps({"run_id": "stale001", "status": "running"}))
    past = time.time() - (_ORPHAN_THRESHOLD_S + 60)
    os.utime(stale, (past, past))

    orphans = RunStateManager.scan_orphans()
    found = [o for o in orphans if o["run_id"] == "stale001"]
    assert len(found) == 1
    assert found[0]["stale"] is True


def test_completed_runs_not_reported_as_orphans(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("done01")
    mgr.load_or_create()
    mgr.mark_complete("success")
    orphans = RunStateManager.scan_orphans()
    assert not any(o["run_id"] == "done01" for o in orphans)


def test_mark_stale_orphans_failed_updates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "reports" / "state"
    state_dir.mkdir(parents=True)

    stale = state_dir / "stale002.json"
    stale.write_text(json.dumps({"run_id": "stale002", "status": "running"}))
    past = time.time() - (_ORPHAN_THRESHOLD_S + 60)
    os.utime(stale, (past, past))

    count = RunStateManager.mark_stale_orphans_failed()
    assert count == 1
    updated = json.loads(stale.read_text())
    assert updated["status"] == "failed"


def test_fresh_running_state_not_marked_stale(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mgr = RunStateManager("fresh01")
    mgr.load_or_create()

    orphans = RunStateManager.scan_orphans()
    found = [o for o in orphans if o["run_id"] == "fresh01"]
    assert len(found) == 1
    assert found[0]["stale"] is False
