"""Tests for setup_schedule.py Linux/cron paths."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

import scripts.setup_schedule as sched


# ── helpers ───────────────────────────────────────────────────────────────────

def _crontab_result(lines: list[str] | None = None, returncode: int = 0, stderr: str = ""):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = ("\n".join(lines) + "\n") if lines else ""
    r.stderr = stderr
    return r


def _empty_crontab(args, **kwargs):
    return _crontab_result(returncode=1, stderr="no crontab for user")


def _write_success(args, **kwargs):
    return _crontab_result()


WORK_DIR = "/opt/oci_resource_report"


# ── install — empty crontab ───────────────────────────────────────────────────

def test_install_adds_line_to_empty_crontab():
    calls = [_empty_crontab(None), _write_success(None)]
    with patch("subprocess.run", side_effect=calls) as mock_run:
        sched._cron_install(sys.executable, "main.py", WORK_DIR, dry_run=False)

    write_call = mock_run.call_args_list[1]
    written = write_call.kwargs.get("input", "") or ""
    tag = sched._install_tag(WORK_DIR)
    assert tag in written


# ── install — replaces existing tagged line (idempotent) ─────────────────────

def test_install_replaces_existing_tagged_line():
    tag = sched._install_tag(WORK_DIR)
    existing = f"0 6 */15 * * old_command  # {tag}"

    def side_effect(args, **kwargs):
        if args == ["crontab", "-l"]:
            return _crontab_result([existing])
        return _write_success(args)

    with patch("subprocess.run", side_effect=side_effect) as mock_run:
        sched._cron_install(sys.executable, "main.py", WORK_DIR, dry_run=False)

    write_call = mock_run.call_args_list[1]
    written = write_call.kwargs.get("input", "") or ""
    assert tag in written
    assert "old_command" not in written
    assert written.count(tag) == 1


# ── install — dry-run ─────────────────────────────────────────────────────────

def test_install_dry_run_does_not_call_crontab(capsys):
    with patch("subprocess.run") as mock_run:
        sched._cron_install(sys.executable, "main.py", WORK_DIR, dry_run=True)

    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert sched._install_tag(WORK_DIR) in out


# ── uninstall — removes only tagged line ─────────────────────────────────────

def test_uninstall_removes_tagged_line():
    tag = sched._install_tag(WORK_DIR)
    unrelated = "# unrelated job"
    tagged_line = f"0 8 */15 * * main.py run  # {tag}"

    def side_effect(args, **kwargs):
        if args == ["crontab", "-l"]:
            return _crontab_result([unrelated, tagged_line])
        return _write_success(args)

    with patch("subprocess.run", side_effect=side_effect) as mock_run:
        sched._cron_uninstall(WORK_DIR, dry_run=False)

    write_call = mock_run.call_args_list[1]
    written = write_call.kwargs.get("input", "") or ""
    assert tag not in written
    assert unrelated in written


# ── uninstall — no-op when tag not present ───────────────────────────────────

def test_uninstall_noop_when_tag_absent():
    def side_effect(args, **kwargs):
        return _crontab_result(["# unrelated"])

    with patch("subprocess.run", side_effect=side_effect) as mock_run:
        sched._cron_uninstall(WORK_DIR, dry_run=False)

    assert mock_run.call_count == 1  # only crontab -l, no write


# ── status — installed ────────────────────────────────────────────────────────

def test_status_prints_installed_line(capsys):
    tag = sched._install_tag(WORK_DIR)
    line = f"0 8 */15 * * main.py run  # {tag}"

    with patch("subprocess.run", return_value=_crontab_result([line])):
        sched._cron_status(WORK_DIR)

    assert "Installed" in capsys.readouterr().out


# ── status — not installed ────────────────────────────────────────────────────

def test_status_not_installed(capsys):
    with patch("subprocess.run", return_value=_crontab_result(["# unrelated"])):
        sched._cron_status(WORK_DIR)

    assert "Not installed" in capsys.readouterr().out


# ── install — permission denied → manual instructions ────────────────────────

def test_install_permission_denied_exits_nonzero(capsys):
    with patch("subprocess.run", side_effect=PermissionError("denied")):
        with pytest.raises(SystemExit) as exc:
            sched._cron_install(sys.executable, "main.py", WORK_DIR, dry_run=False)

    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert any(kw in out.lower() for kw in ("crontab", "manual", "permission", "add"))
