"""Tests for setup_schedule.py Windows/schtasks paths."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

import scripts.setup_schedule as sched

WORK_DIR = "/opt/oci_resource_report"
_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _schtasks_ok():
    r = MagicMock()
    r.returncode = 0
    r.stdout = "Task: OCICostOptimizer\nStatus: Ready"
    r.stderr = ""
    return r


def _schtasks_fail(stderr="ERROR: The system cannot find the file specified."):
    r = MagicMock()
    r.returncode = 1
    r.stdout = ""
    r.stderr = stderr
    return r


# ── XML generation ────────────────────────────────────────────────────────────

def test_xml_is_well_formed():
    xml_str = sched._windows_xml(sys.executable, "main.py", WORK_DIR)
    root = ET.fromstring(xml_str)
    assert root is not None


def test_xml_contains_task_name_in_exec():
    xml_str = sched._windows_xml(sys.executable, "main.py", WORK_DIR)
    root = ET.fromstring(xml_str)
    cmd = root.find(f".//{{{_NS}}}Command")
    assert cmd is not None
    assert cmd.text == sys.executable


def test_xml_contains_calendar_trigger():
    xml_str = sched._windows_xml(sys.executable, "main.py", WORK_DIR)
    root = ET.fromstring(xml_str)
    trigger = root.find(f".//{{{_NS}}}CalendarTrigger")
    assert trigger is not None


def test_xml_execution_time_limit():
    xml_str = sched._windows_xml(sys.executable, "main.py", WORK_DIR)
    root = ET.fromstring(xml_str)
    limit = root.find(f".//{{{_NS}}}ExecutionTimeLimit")
    assert limit is not None
    assert limit.text == "PT2H"


def test_xml_ignore_new_policy():
    xml_str = sched._windows_xml(sys.executable, "main.py", WORK_DIR)
    root = ET.fromstring(xml_str)
    policy = root.find(f".//{{{_NS}}}MultipleInstancesPolicy")
    assert policy is not None
    assert policy.text == "IgnoreNew"


def test_xml_working_directory():
    xml_str = sched._windows_xml(sys.executable, "main.py", WORK_DIR)
    root = ET.fromstring(xml_str)
    wd = root.find(f".//{{{_NS}}}WorkingDirectory")
    assert wd is not None
    assert wd.text == WORK_DIR


# ── install ───────────────────────────────────────────────────────────────────

def test_windows_install_calls_schtasks_create(tmp_path):
    with patch("subprocess.run", return_value=_schtasks_ok()) as mock_run, \
         patch("tempfile.NamedTemporaryFile") as mock_tmp:
        tmp_file = MagicMock()
        tmp_file.__enter__ = MagicMock(return_value=tmp_file)
        tmp_file.__exit__ = MagicMock(return_value=False)
        tmp_file.name = str(tmp_path / "task.xml")
        mock_tmp.return_value = tmp_file

        with patch("pathlib.Path.unlink"):
            sched._windows_install(sys.executable, "main.py", WORK_DIR, dry_run=False)

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "schtasks" in call_args
    assert "/Create" in call_args
    assert "/TN" in call_args
    assert sched._TASK_NAME in call_args


def test_windows_install_dry_run_prints_xml_no_schtasks(capsys):
    with patch("subprocess.run") as mock_run:
        sched._windows_install(sys.executable, "main.py", WORK_DIR, dry_run=True)

    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert sched._TASK_NAME in out


def test_windows_install_failure_exits_nonzero(tmp_path, capsys):
    with patch("subprocess.run", return_value=_schtasks_fail()) as mock_run, \
         patch("tempfile.NamedTemporaryFile") as mock_tmp:
        tmp_file = MagicMock()
        tmp_file.__enter__ = MagicMock(return_value=tmp_file)
        tmp_file.__exit__ = MagicMock(return_value=False)
        tmp_file.name = str(tmp_path / "task.xml")
        mock_tmp.return_value = tmp_file

        with patch("pathlib.Path.unlink"):
            with pytest.raises(SystemExit) as exc:
                sched._windows_install(sys.executable, "main.py", WORK_DIR, dry_run=False)

    assert exc.value.code != 0


# ── uninstall ─────────────────────────────────────────────────────────────────

def test_windows_uninstall_calls_schtasks_delete():
    with patch("subprocess.run", return_value=_schtasks_ok()) as mock_run:
        sched._windows_uninstall(dry_run=False)

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "/Delete" in call_args
    assert sched._TASK_NAME in call_args


def test_windows_uninstall_dry_run_no_call(capsys):
    with patch("subprocess.run") as mock_run:
        sched._windows_uninstall(dry_run=True)

    mock_run.assert_not_called()
    assert "dry-run" in capsys.readouterr().out.lower()


# ── status ────────────────────────────────────────────────────────────────────

def test_windows_status_installed(capsys):
    with patch("subprocess.run", return_value=_schtasks_ok()):
        sched._windows_status()

    out = capsys.readouterr().out
    assert "OCICostOptimizer" in out or "Ready" in out


def test_windows_status_not_installed(capsys):
    with patch("subprocess.run", return_value=_schtasks_fail()):
        sched._windows_status()

    assert "Not installed" in capsys.readouterr().out
