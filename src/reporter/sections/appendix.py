"""
src/reporter/sections/appendix.py
====================================
Appendix: run metadata + sanitized config snapshot.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer

from src.reporter.styles import BODY, BODY_SMALL, CAPTION, H2, H3, MARGIN, NEUTRAL_200

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult

_SECRET_KEYS = {
    "password", "token", "api_key", "secret", "auth",
    "credential", "smtp_pass", "smtp_password",
}


def _redact(obj, depth: int = 0) -> object:
    """Recursively redact known sensitive keys from a dict."""
    if depth > 10:
        return obj
    if isinstance(obj, dict):
        return {
            k: "***REDACTED***" if any(s in k.lower() for s in _SECRET_KEYS) else _redact(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(i, depth + 1) for i in obj]
    return obj


def build_appendix(result: "AnalyticsResult", run_id: str, config: dict | None = None) -> list:
    """Returns flowables for the Appendix page."""
    flowables: list = []

    flowables.append(Paragraph("Appendix: Run Metadata", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    generated = result.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC") if result.generated_at else "—"
    period_str = (
        f"{result.period_start.date()} to {result.period_end.date()}"
        if result.period_start else "—"
    )

    meta_items = [
        ("Run ID", run_id),
        ("Generated At", generated),
        ("Analysis Period", period_str),
        ("Schema Version", result.schema_version),
        ("Raw Input", result.raw_input_path),
        ("Validation", result.validation_report.summary() if result.validation_report else "—"),
        ("Recommendations", str(len(result.recommendations))),
        ("Anomalies", str(len(result.anomalies))),
    ]

    for key, val in meta_items:
        flowables.append(Paragraph(f"<b>{key}:</b> {val}", BODY_SMALL))
    flowables.append(Spacer(1, 0.15 * inch))

    # ── Sanitized config ───────────────────────────────────────────────────
    if config:
        flowables.append(Paragraph("Configuration Snapshot (secrets redacted)", H3))
        safe_cfg = _redact(config)
        import json
        cfg_str = json.dumps(safe_cfg, indent=2, default=str)
        for line in cfg_str.split("\n")[:40]:  # cap at 40 lines
            flowables.append(Paragraph(line.replace(" ", "&nbsp;").replace("<", "&lt;"), CAPTION))
        if cfg_str.count("\n") > 40:
            flowables.append(Paragraph("(truncated — see config.yaml for full configuration)", CAPTION))

    flowables.append(PageBreak())
    return flowables
