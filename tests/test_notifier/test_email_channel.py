"""Tests for SMTPEmailChannel."""
from __future__ import annotations

import smtplib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.notifier.email_channel import SMTPEmailChannel
from src.notifier.base import ChannelResult


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_result():
    from datetime import datetime, timezone
    from tests.test_reporter.conftest import _base_result, _kpis, _rec, _anomaly
    from src.analytics.right_sizer import RecommendationType
    from src.analytics.anomaly import AnomalySeverity
    result = _base_result(
        kpis=_kpis(savings=1500.0),
        recs=[_rec(i) for i in range(3)],
        anomalies=[_anomaly("zombie", AnomalySeverity.CRITICAL)],
    )
    result._run_id = "test0001"
    result._pdf_path = None
    result._pdf_filename = "OCI_Cost_Report.pdf"
    result._csv_filename = None
    return result


def _cfg(extra: dict | None = None) -> dict:
    base = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "encryption": "starttls",
        "auth_method": "login",
        "smtp_user": "user@example.com",
        "from_address": "noreply@example.com",
        "from_name": "OCI Optimizer",
        "to_addresses": ["admin@example.com"],
        "cc_addresses": [],
        "bcc_addresses": [],
        "attach_csv": False,
    }
    if extra:
        base.update(extra)
    return {"email": base}


def _mock_smtp(sendmail_return=None):
    inst = MagicMock()
    inst.sendmail.return_value = sendmail_return or {}
    inst.__enter__ = lambda s: s
    inst.__exit__ = MagicMock(return_value=False)
    return inst


# ── enabled / disabled ────────────────────────────────────────────────────────

def test_disabled_channel_returns_success_without_sending():
    ch = SMTPEmailChannel({"email": {"enabled": False}})
    result = ch.send(MagicMock())
    assert result.success
    assert result.message == "disabled"


def test_enabled_requires_smtp_host():
    ch = SMTPEmailChannel({"email": {"enabled": True}})
    assert not ch.enabled


# ── test mode ─────────────────────────────────────────────────────────────────

def test_test_mode_writes_eml_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EMAIL_TEST_MODE", "1")

    result = _run_result()
    result._run_id = "eml0001"

    ch = SMTPEmailChannel(_cfg())
    cr = ch.send(result)

    assert cr.success
    assert "test mode" in cr.message
    eml_path = tmp_path / "reports" / "email_drafts" / "eml0001.eml"
    assert eml_path.exists()
    content = eml_path.read_bytes()
    assert b"multipart" in content
    assert b"OCI" in content


def test_test_mode_eml_has_html_and_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EMAIL_TEST_MODE", "1")

    result = _run_result()
    result._run_id = "struct1"

    ch = SMTPEmailChannel(_cfg())
    ch.send(result)

    content = (tmp_path / "reports" / "email_drafts" / "struct1.eml").read_text()
    assert "text/html" in content
    assert "text/plain" in content
    assert "X-OCI-Run-ID" in content


# ── STARTTLS path ─────────────────────────────────────────────────────────────

def test_starttls_send_success():
    inst = _mock_smtp()
    with patch("smtplib.SMTP", return_value=inst):
        ch = SMTPEmailChannel(_cfg())
        cr = ch.send(_run_result())

    assert cr.success
    inst.starttls.assert_called_once()
    inst.login.assert_called_once()


# ── SSL path ──────────────────────────────────────────────────────────────────

def test_ssl_send_success():
    inst = _mock_smtp()
    with patch("smtplib.SMTP_SSL", return_value=inst):
        ch = SMTPEmailChannel(_cfg({"encryption": "ssl", "smtp_port": 465}))
        cr = ch.send(_run_result())

    assert cr.success
    inst.starttls.assert_not_called()


# ── auth=none ─────────────────────────────────────────────────────────────────

def test_auth_none_skips_login():
    inst = _mock_smtp()
    with patch("smtplib.SMTP", return_value=inst):
        ch = SMTPEmailChannel(_cfg({"auth_method": "none"}))
        cr = ch.send(_run_result())

    assert cr.success
    inst.login.assert_not_called()


# ── auth failure — permanent, no retry ───────────────────────────────────────

def test_auth_failure_is_permanent():
    inst = _mock_smtp()
    inst.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")
    with patch("smtplib.SMTP", return_value=inst) as mock_cls:
        ch = SMTPEmailChannel(_cfg())
        cr = ch.send(_run_result())

    assert not cr.success
    assert "authentication failed" in cr.message
    assert mock_cls.call_count == 1


# ── per-recipient partial failure ─────────────────────────────────────────────

def test_partial_recipient_failure():
    inst = _mock_smtp(sendmail_return={"bad@example.com": (550, b"User unknown")})
    cfg = _cfg({"to_addresses": ["ok@example.com", "bad@example.com"]})
    with patch("smtplib.SMTP", return_value=inst):
        ch = SMTPEmailChannel(cfg)
        cr = ch.send(_run_result())

    assert cr.partial
    assert "bad@example.com" in cr.failed_recipients


# ── subject variants ──────────────────────────────────────────────────────────

def test_subject_anomaly_variant():
    from src.analytics.right_sizer import RecommendationType
    from src.analytics.anomaly import AnomalySeverity
    from tests.test_reporter.conftest import _base_result, _kpis, _rec, _anomaly
    result = _base_result(
        kpis=_kpis(savings=500.0),
        recs=[_rec(0)],
        anomalies=[_anomaly("zombie", AnomalySeverity.CRITICAL)],
    )
    result._run_id = "subj01"
    result._pdf_path = None
    result._pdf_filename = "r.pdf"
    result._csv_filename = None

    ch = SMTPEmailChannel(_cfg())
    msg, _ = ch._build_message(result)
    assert "WARN" in msg["Subject"]


def test_subject_no_savings_variant():
    from tests.test_reporter.conftest import _base_result, _kpis, _rec
    from src.analytics.right_sizer import RecommendationType
    result = _base_result(
        kpis=_kpis(savings=0.0),
        recs=[_rec(0, RecommendationType.OPTIMAL, savings=0)],
        anomalies=[],
    )
    result._run_id = "subj02"
    result._pdf_path = None
    result._pdf_filename = "r.pdf"
    result._csv_filename = None

    ch = SMTPEmailChannel(_cfg())
    msg, _ = ch._build_message(result)
    assert "healthy" in msg["Subject"].lower()
