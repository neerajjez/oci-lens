"""Tests for src/notifier/slack_channel.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.notifier.slack_channel import SlackChannel


def _run_result(savings: float = 1000.0, anomaly_count: int = 0, run_id: str = "test001"):
    rr = MagicMock()
    rr._run_id = run_id
    rr.fleet_kpis.total_potential_monthly_savings = savings
    rr.fleet_kpis.total_fleet_cost_monthly_run_rate = 5000.0
    rr.anomalies = [MagicMock()] * anomaly_count
    rr.recommendations = []
    return rr


def _resp(status: int = 200) -> MagicMock:
    r = MagicMock()
    r.__enter__ = MagicMock(return_value=r)
    r.__exit__ = MagicMock(return_value=False)
    r.status = status
    r.read.return_value = b"ok"
    return r


# ── enabled / disabled ────────────────────────────────────────────────────────

def test_disabled_when_no_webhook():
    ch = SlackChannel({"slack": {"enabled": True, "webhook_url": ""}})
    assert not ch.enabled


def test_disabled_when_flag_false():
    ch = SlackChannel({"slack": {"enabled": False, "webhook_url": "https://hooks.slack.com/x"}})
    assert not ch.enabled


def test_enabled_with_webhook():
    ch = SlackChannel({"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}})
    assert ch.enabled


def test_enabled_via_env(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/env")
    ch = SlackChannel({"slack": {"enabled": True}})
    assert ch.enabled


# ── channel_name ──────────────────────────────────────────────────────────────

def test_channel_name():
    assert SlackChannel({}).channel_name == "slack"


# ── send when disabled ────────────────────────────────────────────────────────

def test_send_disabled_is_success():
    result = SlackChannel({}).send(_run_result())
    assert result.success
    assert result.channel == "slack"


# ── send success ──────────────────────────────────────────────────────────────

def test_send_posts_to_webhook():
    ch = SlackChannel({"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}})
    with patch("urllib.request.urlopen", return_value=_resp(200)) as mock_open:
        result = ch.send(_run_result())
    mock_open.assert_called_once()
    assert result.success


def test_send_non_200_fails():
    ch = SlackChannel({"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}})
    with patch("urllib.request.urlopen", return_value=_resp(500)):
        result = ch.send(_run_result())
    assert not result.success


def test_send_exception_fails():
    ch = SlackChannel({"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}})
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        result = ch.send(_run_result())
    assert not result.success
    assert "timeout" in result.message


def test_payload_contains_run_id():
    ch = SlackChannel({"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/x"}})
    captured = []

    def capture(req, timeout):
        captured.append(req.data.decode())
        return _resp(200)

    with patch("urllib.request.urlopen", side_effect=capture):
        ch.send(_run_result(run_id="abc999"))

    assert "abc999" in captured[0]
