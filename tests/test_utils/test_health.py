"""Tests for src/utils/health.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.utils.health import (
    CheckResult,
    check_disk_space,
    check_filesystem_writable,
    check_last_run_status,
    check_python_version,
    overall_exit_code,
    run_health_checks,
)


# ── check_python_version ──────────────────────────────────────────────────────

def test_python_version_ok():
    status, details = check_python_version()
    assert status == "ok"
    assert "Python" in details


# ── check_filesystem_writable ─────────────────────────────────────────────────

def test_filesystem_writable_ok(tmp_path):
    status, details = check_filesystem_writable(tmp_path)
    assert status == "ok"
    assert "writable" in details


def test_filesystem_writable_creates_dirs(tmp_path):
    check_filesystem_writable(tmp_path)
    assert (tmp_path / "logs").exists()
    assert (tmp_path / "reports" / "state").exists()


def test_filesystem_writable_no_probe_left(tmp_path):
    check_filesystem_writable(tmp_path)
    assert not (tmp_path / ".health_probe").exists()


# ── check_disk_space ──────────────────────────────────────────────────────────

def test_disk_space_ok(tmp_path):
    status, details = check_disk_space(tmp_path, warn_gb=0.0)
    assert status == "ok"
    assert "GB free" in details


def test_disk_space_warn_when_below_threshold(tmp_path):
    status, _ = check_disk_space(tmp_path, warn_gb=1_000_000.0)
    assert status == "warn"


# ── check_last_run_status ─────────────────────────────────────────────────────

def test_last_run_no_file_warns(tmp_path):
    status, details = check_last_run_status(tmp_path)
    assert status == "warn"
    assert "run_log" in details


def test_last_run_success_ok(tmp_path):
    log = tmp_path / "reports" / "run_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"run_id": "abc123", "status": "success"}) + "\n")
    status, details = check_last_run_status(tmp_path)
    assert status == "ok"
    assert "abc123" in details


def test_last_run_failed_warns(tmp_path):
    log = tmp_path / "reports" / "run_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"run_id": "xyz999", "status": "failed"}) + "\n")
    status, _ = check_last_run_status(tmp_path)
    assert status == "warn"


def test_last_run_empty_file_warns(tmp_path):
    log = tmp_path / "reports" / "run_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("")
    status, _ = check_last_run_status(tmp_path)
    assert status == "warn"


# ── overall_exit_code ─────────────────────────────────────────────────────────

def _r(status: str) -> CheckResult:
    return CheckResult(name="t", status=status, latency_ms=0.0, details="")


def test_all_ok_exits_0():
    assert overall_exit_code([_r("ok"), _r("ok")]) == 0


def test_warn_exits_1():
    assert overall_exit_code([_r("ok"), _r("warn")]) == 1


def test_fail_exits_2():
    assert overall_exit_code([_r("ok"), _r("fail")]) == 2


def test_fail_beats_warn():
    assert overall_exit_code([_r("warn"), _r("fail")]) == 2


# ── run_health_checks ─────────────────────────────────────────────────────────

def test_run_returns_list(tmp_path):
    results = run_health_checks(tmp_path)
    assert isinstance(results, list)
    assert len(results) >= 4


def test_run_all_results_have_valid_fields(tmp_path):
    for r in run_health_checks(tmp_path):
        assert r.name
        assert r.status in ("ok", "warn", "fail")
        assert isinstance(r.latency_ms, float)


def test_smtp_omitted_when_no_host(tmp_path):
    names = [r.name for r in run_health_checks(tmp_path, smtp_host="")]
    assert "smtp_connection" not in names


def test_smtp_included_when_host_set(tmp_path):
    names = [r.name for r in run_health_checks(tmp_path, smtp_host="localhost", smtp_port=9999)]
    assert "smtp_connection" in names


# ── redaction ─────────────────────────────────────────────────────────────────

def test_redact_secrets_replaces_password():
    from src.utils.redaction import redact_secrets
    result = redact_secrets({"password": "s3cr3t", "user": "alice"})
    assert result["password"] == "***REDACTED***"
    assert result["user"] == "alice"


def test_redact_secrets_nested():
    from src.utils.redaction import redact_secrets
    result = redact_secrets({"smtp": {"smtp_pass": "hunter2", "host": "mail.example.com"}})
    assert result["smtp"]["smtp_pass"] == "***REDACTED***"
    assert result["smtp"]["host"] == "mail.example.com"


def test_redact_secrets_list():
    from src.utils.redaction import redact_secrets
    result = redact_secrets([{"token": "abc"}, {"name": "ok"}])
    assert result[0]["token"] == "***REDACTED***"
    assert result[1]["name"] == "ok"


def test_redact_secrets_non_sensitive_unchanged():
    from src.utils.redaction import redact_secrets
    # Non-sensitive keys with non-OCID values pass through unchanged
    obj = {"region": "us-ashburn-1", "name": "my-instance"}
    assert redact_secrets(obj) == obj


def test_redact_secrets_ocid_values_masked():
    from src.utils.redaction import redact_secrets
    # OCID values are masked regardless of key name (last 20 chars replaced with ***)
    ocid = "ocid1.compartment.oc1..aaaaaaaakb3vun6pe7o6uhs2zgqrk4ltyjzdf7bsrqj53l5serk6ox2hgkka"
    result = redact_secrets({"compartment_id": ocid})
    assert result["compartment_id"].endswith("***")
    assert result["compartment_id"].startswith("ocid1.")
    assert ocid not in result["compartment_id"]
