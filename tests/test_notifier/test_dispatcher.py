"""Tests for NotificationDispatcher."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.notifier.base import ChannelResult, NotificationChannel
from src.notifier.dispatcher import NotificationDispatcher


# ── helpers ───────────────────────────────────────────────────────────────────

def _chan(name: str, enabled: bool, success: bool, partial: bool = False) -> NotificationChannel:
    ch = MagicMock(spec=NotificationChannel)
    ch.enabled = enabled
    ch.channel_name = name
    ch.send.return_value = ChannelResult(
        channel=name, success=success, partial=partial,
        message="ok" if success else "err",
    )
    return ch


def _run_result(run_id: str = "test0001"):
    r = MagicMock()
    r._run_id = run_id
    return r


# ── no active channels ────────────────────────────────────────────────────────

def test_no_active_channels_returns_success():
    d = NotificationDispatcher([_chan("email", enabled=False, success=True)])
    result = d.send(_run_result())
    assert result.success
    assert result.channel_results == []


# ── all succeed ───────────────────────────────────────────────────────────────

def test_all_channels_succeed():
    channels = [
        _chan("email", enabled=True, success=True),
        _chan("slack", enabled=True, success=True),
    ]
    d = NotificationDispatcher(channels)
    result = d.send(_run_result())
    assert result.success
    assert not result.all_failed
    assert len(result.channel_results) == 2


# ── one fails, one succeeds ───────────────────────────────────────────────────

def test_email_ok_slack_fail():
    channels = [
        _chan("email", enabled=True, success=True),
        _chan("slack", enabled=True, success=False),
    ]
    d = NotificationDispatcher(channels)
    result = d.send(_run_result())
    assert result.success
    assert not result.all_failed


# ── all fail → escalation writes critical file ────────────────────────────────

def test_all_fail_writes_critical_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    channels = [
        _chan("email", enabled=True, success=False),
        _chan("slack", enabled=True, success=False),
    ]
    d = NotificationDispatcher(channels)
    result = d.send(_run_result("failrun"))
    assert result.all_failed
    failure_file = tmp_path / "reports" / "CRITICAL_DELIVERY_FAILURE_failrun.json"
    assert failure_file.exists()
    data = json.loads(failure_file.read_text())
    assert data["run_id"] == "failrun"
    assert len(data["channel_results"]) == 2


# ── disabled channel is never called ─────────────────────────────────────────

def test_disabled_channel_not_sent():
    ch = _chan("teams", enabled=False, success=True)
    d = NotificationDispatcher([ch])
    d.send(_run_result())
    ch.send.assert_not_called()


# ── partial flag propagated ───────────────────────────────────────────────────

def test_partial_result_propagated():
    channels = [_chan("email", enabled=True, success=True, partial=True)]
    d = NotificationDispatcher(channels)
    result = d.send(_run_result())
    assert result.partial
    assert result.success
