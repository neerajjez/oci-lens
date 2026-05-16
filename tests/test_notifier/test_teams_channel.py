"""Tests for src/notifier/teams_channel.py."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.notifier.teams_channel import TeamsChannel


def _run_result(savings: float = 1000.0, anomaly_count: int = 0,
                run_id: str = "test001", recs=None):
    rr = MagicMock()
    rr._run_id = run_id
    rr.fleet_kpis.total_potential_monthly_savings = savings
    rr.fleet_kpis.total_fleet_cost_monthly_run_rate = 5000.0
    rr.anomalies = [MagicMock()] * anomaly_count
    rr.recommendations = recs or []
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
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": ""}})
    assert not ch.enabled


def test_disabled_when_flag_false():
    ch = TeamsChannel({"teams": {"enabled": False, "webhook_url": "https://outlook.office.com/x"}})
    assert not ch.enabled


def test_enabled_with_webhook():
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/x"}})
    assert ch.enabled


def test_enabled_via_env(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/env")
    ch = TeamsChannel({"teams": {"enabled": True}})
    assert ch.enabled


# ── channel_name ──────────────────────────────────────────────────────────────

def test_channel_name():
    assert TeamsChannel({}).channel_name == "teams"


# ── send when disabled ────────────────────────────────────────────────────────

def test_send_disabled_is_success():
    result = TeamsChannel({}).send(_run_result())
    assert result.success
    assert result.channel == "teams"


# ── send success / failure ────────────────────────────────────────────────────

def test_send_posts_to_webhook():
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/x"}})
    with patch("urllib.request.urlopen", return_value=_resp(200)) as mock_open:
        result = ch.send(_run_result())
    mock_open.assert_called_once()
    assert result.success


def test_send_non_200_fails():
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/x"}})
    with patch("urllib.request.urlopen", return_value=_resp(400)):
        result = ch.send(_run_result())
    assert not result.success


def test_send_exception_fails():
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/x"}})
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        result = ch.send(_run_result())
    assert not result.success
    assert "timeout" in result.message


# ── payload content ───────────────────────────────────────────────────────────

def test_payload_contains_run_id():
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/x"}})
    captured = []

    def capture(req, timeout):
        captured.append(req.data.decode())
        return _resp(200)

    with patch("urllib.request.urlopen", side_effect=capture):
        ch.send(_run_result(run_id="xyz999"))

    assert "xyz999" in captured[0]


def test_payload_includes_anomaly_warning():
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/x"}})
    captured = []

    def capture(req, timeout):
        captured.append(req.data.decode())
        return _resp(200)

    with patch("urllib.request.urlopen", side_effect=capture):
        ch.send(_run_result(anomaly_count=3))

    payload = json.loads(captured[0])
    body_texts = [
        b.get("text", "") for att in payload.get("attachments", [])
        for b in att.get("content", {}).get("body", [])
    ]
    assert any("anomal" in t.lower() for t in body_texts)


def test_payload_includes_top_recommendations():
    from src.analytics.right_sizer import RecommendationType
    rec = MagicMock()
    rec.recommendation_type = RecommendationType.DOWNSIZE
    rec.estimated_monthly_savings = 500.0
    rec.instance_name = "my-instance"
    ch = TeamsChannel({"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/x"}})
    captured = []

    def capture(req, timeout):
        captured.append(req.data.decode())
        return _resp(200)

    with patch("urllib.request.urlopen", side_effect=capture):
        ch.send(_run_result(recs=[rec]))

    assert "my-instance" in captured[0]
