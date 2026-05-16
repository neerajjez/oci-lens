"""Tests for email Jinja2 templates."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parents[2] / "src" / "notifier" / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _ctx(anomaly_count: int = 0, top_recs: int = 3, top_anoms: int = 0) -> dict:
    return {
        "period_start": "Apr 01, 2026",
        "period_end": "Apr 15, 2026",
        "generated_at": "2026-04-15 08:00 UTC",
        "run_id": "abc12345",
        "total_cost": "10,000",
        "savings": "2,500",
        "composite_score": "0.42",
        "anomaly_count": anomaly_count,
        "pdf_filename": "OCI_Cost_Report.pdf",
        "csv_filename": "recommendations_abc12345.csv",
        "top_recommendations": [
            {"name": f"instance-{i:02d}", "action": "DOWNSIZE", "savings": "300", "confidence": "high"}
            for i in range(top_recs)
        ],
        "top_anomalies": [
            {
                "severity": "CRITICAL",
                "signal": "zombie",
                "description": "CPU p95 < 5% for entire period",
                "action": "Verify traffic then terminate",
                "recoverable": "150",
            }
            for _ in range(top_anoms)
        ],
    }


# ── HTML template ─────────────────────────────────────────────────────────────

def test_html_renders_without_error():
    html = _env().get_template("email_html.j2").render(**_ctx())
    assert "<html" in html


def test_html_no_unfilled_placeholders():
    html = _env().get_template("email_html.j2").render(**_ctx())
    assert not re.search(r"\{\{[^}]+\}\}", html)


def test_html_contains_kpi_values():
    html = _env().get_template("email_html.j2").render(**_ctx())
    assert "10,000" in html
    assert "2,500" in html
    assert "0.42" in html


def test_html_recommendations_table_present():
    html = _env().get_template("email_html.j2").render(**_ctx(top_recs=3))
    assert "instance-00" in html
    assert "DOWNSIZE" in html


def test_html_zero_recommendations_no_table():
    html = _env().get_template("email_html.j2").render(**_ctx(top_recs=0))
    assert "instance-00" not in html


def test_html_anomaly_section_shown_when_present():
    html = _env().get_template("email_html.j2").render(**_ctx(anomaly_count=1, top_anoms=1))
    assert "zombie" in html


def test_html_no_anomaly_section_when_empty():
    html = _env().get_template("email_html.j2").render(**_ctx(anomaly_count=0, top_anoms=0))
    assert "Anomalies Detected" not in html


def test_html_anomaly_count_red_when_nonzero():
    html = _env().get_template("email_html.j2").render(**_ctx(anomaly_count=2))
    assert "#C62828" in html


def test_html_anomaly_count_green_when_zero():
    html = _env().get_template("email_html.j2").render(**_ctx(anomaly_count=0))
    assert "#2E7D32" in html


# ── text template ─────────────────────────────────────────────────────────────

def test_text_renders_without_error():
    text = _env().get_template("email_text.j2").render(**_ctx())
    assert "OCI Cloud Cost" in text


def test_text_no_unfilled_placeholders():
    text = _env().get_template("email_text.j2").render(**_ctx())
    assert not re.search(r"\{\{[^}]+\}\}", text)


def test_text_contains_period():
    text = _env().get_template("email_text.j2").render(**_ctx())
    assert "Apr 01, 2026" in text
    assert "Apr 15, 2026" in text


def test_text_zero_anomalies_graceful():
    text = _env().get_template("email_text.j2").render(**_ctx(anomaly_count=0, top_anoms=0))
    assert "ANOMALIES" not in text


def test_text_recommendations_listed():
    text = _env().get_template("email_text.j2").render(**_ctx(top_recs=2))
    assert "instance-00" in text
    assert "DOWNSIZE" in text
