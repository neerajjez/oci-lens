"""Health check subsystem for python main.py health."""
from __future__ import annotations

import json
import shutil
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CheckResult:
    name: str
    status: str          # ok | warn | fail
    latency_ms: float
    details: str


def _check(name: str, fn) -> CheckResult:
    t0 = time.perf_counter()
    try:
        status, details = fn()
    except Exception as exc:
        status, details = "fail", str(exc)
    latency_ms = (time.perf_counter() - t0) * 1000
    return CheckResult(name=name, status=status, latency_ms=latency_ms, details=details)


# ── individual checks ─────────────────────────────────────────────────────────

def check_python_version() -> tuple[str, str]:
    vi = sys.version_info
    if vi >= (3, 9):
        return "ok", f"Python {vi.major}.{vi.minor}.{vi.micro}"
    return "fail", f"Python {vi.major}.{vi.minor} < 3.9"


def check_filesystem_writable(output_dir: Path) -> tuple[str, str]:
    dirs = [output_dir, output_dir / "logs", output_dir / "reports" / "state"]
    problems = []
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".health_probe"
            probe.write_text("ok")
            probe.unlink()
        except Exception as exc:
            problems.append(f"{d}: {exc}")
    if problems:
        return "fail", "; ".join(problems)
    return "ok", f"writable: {', '.join(str(d) for d in dirs)}"


def check_disk_space(output_dir: Path, warn_gb: float = 1.0) -> tuple[str, str]:
    try:
        usage = shutil.disk_usage(str(output_dir))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < warn_gb:
            return "warn", f"{free_gb:.1f} GB free (threshold {warn_gb} GB)"
        return "ok", f"{free_gb:.1f} GB free"
    except Exception as exc:
        return "warn", str(exc)


def check_last_run_status(work_dir: Path) -> tuple[str, str]:
    log_path = work_dir / "reports" / "run_log.jsonl"
    if not log_path.exists():
        return "warn", "run_log.jsonl not found — no runs yet"
    try:
        lines = log_path.read_text().strip().splitlines()
        if not lines:
            return "warn", "run_log.jsonl is empty"
        last = json.loads(lines[-1])
        status = last.get("status", "unknown")
        run_id = last.get("run_id", "?")
        if status == "success":
            return "ok", f"last run {run_id} succeeded"
        return "warn", f"last run {run_id} status={status}"
    except Exception as exc:
        return "warn", str(exc)


def check_oci_config(home: Optional[Path] = None) -> tuple[str, str]:
    cfg = (home or Path.home()) / ".oci" / "config"
    if cfg.exists() and cfg.stat().st_size > 0:
        return "ok", str(cfg)
    return "warn", f"OCI config not found at {cfg}"


def check_smtp_connection(host: str, port: int = 587, timeout: float = 3.0) -> tuple[str, str]:
    if not host:
        return "warn", "SMTP host not configured"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "ok", f"{host}:{port} reachable"
    except Exception as exc:
        return "warn", f"{host}:{port} unreachable: {exc}"


# ── orchestrator ──────────────────────────────────────────────────────────────

def run_health_checks(
    work_dir: Path,
    smtp_host: str = "",
    smtp_port: int = 587,
) -> list[CheckResult]:
    results = [
        _check("python_version", check_python_version),
        _check("filesystem_writable", lambda: check_filesystem_writable(work_dir)),
        _check("disk_space", lambda: check_disk_space(work_dir)),
        _check("last_run_status", lambda: check_last_run_status(work_dir)),
        _check("oci_credentials", check_oci_config),
    ]
    if smtp_host:
        results.append(_check("smtp_connection", lambda: check_smtp_connection(smtp_host, smtp_port)))
    return results


def overall_exit_code(results: list[CheckResult]) -> int:
    statuses = {r.status for r in results}
    if "fail" in statuses:
        return 2
    if "warn" in statuses:
        return 1
    return 0
