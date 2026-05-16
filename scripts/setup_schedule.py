#!/usr/bin/env python3
"""
scripts/setup_schedule.py
==========================
Cross-platform scheduler installer.
  Linux/macOS : cron
  Windows     : Task Scheduler XML

Commands: install [--dry-run]  uninstall  status  test
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

_TASK_NAME = "OCICostOptimizer"
_TAG_PREFIX = "OCI_COST_OPTIMIZER_TAG="
_CRON_SCHEDULE = "0 8 */15 * *"
_LOG_DIR = "logs"
_LOG_FILE = "scheduled_run.log"


def _install_tag(install_dir: str) -> str:
    h = hashlib.sha1(install_dir.encode()).hexdigest()[:12]
    return f"{_TAG_PREFIX}{h}"


def _cron_line(python: str, main: str, work_dir: str) -> str:
    log = Path(work_dir) / _LOG_DIR / _LOG_FILE
    tag = _install_tag(work_dir)
    return (
        f"{_CRON_SCHEDULE} cd {work_dir} && {python} {main} run "
        f">> {log} 2>&1  # {tag}"
    )


# ── Linux / macOS ─────────────────────────────────────────────────────────────

def _read_crontab() -> list[str]:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.splitlines()
    if "no crontab for" in result.stderr.lower():
        return []
    raise RuntimeError(f"crontab -l failed: {result.stderr.strip()}")


def _write_crontab(lines: list[str]) -> None:
    content = "\n".join(lines) + "\n"
    proc = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"crontab write failed: {proc.stderr.strip()}")


def _cron_install(python: str, main: str, work_dir: str, dry_run: bool) -> None:
    line = _cron_line(python, main, work_dir)
    tag = _install_tag(work_dir)

    if dry_run:
        print(f"[dry-run] Would install cron line:\n  {line}")
        return

    try:
        existing = _read_crontab()
    except PermissionError:
        _print_manual_install(line)
        sys.exit(1)

    replaced = False
    new_lines = []
    for l in existing:
        if tag in l:
            new_lines.append(line)
            replaced = True
        else:
            new_lines.append(l)

    if not replaced:
        new_lines.append(line)

    _write_crontab(new_lines)
    action = "updated" if replaced else "installed"
    print(f"Cron job {action}.")
    print(f"  {line}")


def _cron_uninstall(work_dir: str, dry_run: bool) -> None:
    tag = _install_tag(work_dir)
    try:
        existing = _read_crontab()
    except Exception as exc:
        print(f"Error reading crontab: {exc}", file=sys.stderr)
        sys.exit(1)

    new_lines = [l for l in existing if tag not in l]
    if len(new_lines) == len(existing):
        print("No OCI Cost Optimizer cron entry found.")
        return

    if dry_run:
        print("[dry-run] Would remove cron entry.")
        return

    _write_crontab(new_lines)
    print("Cron job removed.")


def _cron_status(work_dir: str) -> None:
    tag = _install_tag(work_dir)
    try:
        existing = _read_crontab()
    except Exception as exc:
        print(f"Error reading crontab: {exc}", file=sys.stderr)
        return

    for line in existing:
        if tag in line:
            print(f"Installed: {line}")
            return
    print("Not installed.")


def _print_manual_install(line: str) -> None:
    print("Permission denied. Add this line to your crontab manually:")
    print("  crontab -e")
    print(f"  {line}")


# ── Windows ───────────────────────────────────────────────────────────────────

def _windows_xml(python: str, main: str, work_dir: str) -> str:
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)

    root = ET.Element(f"{{{ns}}}Task", attrib={"version": "1.4"})

    reg = ET.SubElement(root, f"{{{ns}}}RegistrationInfo")
    ET.SubElement(reg, f"{{{ns}}}Description").text = "OCI Cloud Cost Optimizer scheduled run"

    triggers = ET.SubElement(root, f"{{{ns}}}Triggers")
    cal = ET.SubElement(triggers, f"{{{ns}}}CalendarTrigger")
    ET.SubElement(cal, f"{{{ns}}}StartBoundary").text = "2026-01-01T08:00:00"
    ET.SubElement(cal, f"{{{ns}}}Enabled").text = "true"
    sched = ET.SubElement(cal, f"{{{ns}}}ScheduleByDay")
    ET.SubElement(sched, f"{{{ns}}}DaysInterval").text = "15"

    settings = ET.SubElement(root, f"{{{ns}}}Settings")
    ET.SubElement(settings, f"{{{ns}}}MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, f"{{{ns}}}StartWhenAvailable").text = "true"
    ET.SubElement(settings, f"{{{ns}}}ExecutionTimeLimit").text = "PT2H"
    ET.SubElement(settings, f"{{{ns}}}Enabled").text = "true"

    actions = ET.SubElement(root, f"{{{ns}}}Actions", attrib={"Context": "Author"})
    exec_ = ET.SubElement(actions, f"{{{ns}}}Exec")
    ET.SubElement(exec_, f"{{{ns}}}Command").text = python
    ET.SubElement(exec_, f"{{{ns}}}Arguments").text = f"{main} run"
    ET.SubElement(exec_, f"{{{ns}}}WorkingDirectory").text = work_dir

    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def _windows_install(python: str, main: str, work_dir: str, dry_run: bool) -> None:
    xml_content = _windows_xml(python, main, work_dir)
    if dry_run:
        print(f"[dry-run] Would create Task Scheduler task '{_TASK_NAME}'")
        print(xml_content)
        return

    with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False) as f:
        f.write(xml_content)
        xml_path = f.name

    try:
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", _TASK_NAME, "/XML", xml_path, "/F"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"schtasks failed: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        print(f"Task Scheduler task '{_TASK_NAME}' installed.")
    finally:
        Path(xml_path).unlink(missing_ok=True)


def _windows_uninstall(dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] Would delete Task Scheduler task '{_TASK_NAME}'")
        return
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"schtasks delete failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    print(f"Task '{_TASK_NAME}' removed.")


def _windows_status() -> None:
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", _TASK_NAME, "/V", "/FO", "LIST"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Not installed.")
    else:
        print(result.stdout)


# ── dispatch ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="OCI Cost Optimizer scheduler setup")
    parser.add_argument("command", choices=["install", "uninstall", "status", "test"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    work_dir = str(Path(__file__).resolve().parent.parent)
    python = sys.executable
    main_py = str(Path(work_dir) / "main.py")
    is_windows = platform.system() == "Windows"

    if args.command == "install":
        if is_windows:
            _windows_install(python, main_py, work_dir, args.dry_run)
        else:
            _cron_install(python, main_py, work_dir, args.dry_run)

    elif args.command == "uninstall":
        if is_windows:
            _windows_uninstall(args.dry_run)
        else:
            _cron_uninstall(work_dir, args.dry_run)

    elif args.command == "status":
        if is_windows:
            _windows_status()
        else:
            _cron_status(work_dir)

    elif args.command == "test":
        print("Running pipeline test (dry-run, skip-notify)...")
        result = subprocess.run(
            [python, main_py, "run", "--dry-run", "--skip-notify"],
            cwd=work_dir,
        )
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
