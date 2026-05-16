"""
Tests for src/reporter/builder.py (ReportBuilder)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.reporter.builder import ReportBuilder, ReportMeta


def _pdf_is_valid(path: Path) -> bool:
    """Check that the file starts with the PDF magic bytes."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as f:
        return f.read(5) == b"%PDF-"


# ── Basic builds ─────────────────────────────────────────────────────────────

def test_builder_healthy_fleet_produces_pdf(healthy_result, tmp_path):
    out = tmp_path / "report.pdf"
    meta = ReportBuilder().build(healthy_result, out)
    assert _pdf_is_valid(out)
    assert meta.page_count >= 5
    assert 50_000 <= meta.file_size_bytes <= 5_000_000


def test_builder_wasteful_fleet_produces_pdf(wasteful_result, tmp_path):
    out = tmp_path / "report.pdf"
    meta = ReportBuilder().build(wasteful_result, out)
    assert _pdf_is_valid(out)
    assert meta.page_count >= 5


def test_builder_mixed_fleet_produces_pdf(mixed_result, tmp_path):
    out = tmp_path / "report.pdf"
    meta = ReportBuilder().build(mixed_result, out)
    assert _pdf_is_valid(out)
    assert meta.page_count >= 5


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_builder_empty_fleet_returns_report(tmp_path):
    out = tmp_path / "empty.pdf"
    meta = ReportBuilder().build(None, out, run_id="test001")
    assert _pdf_is_valid(out)
    assert meta.page_count >= 1
    assert meta.run_id == "test001"


def test_builder_single_anomaly(tmp_path):
    from tests.test_reporter.conftest import _kpis, _base_result, _anomaly
    from src.analytics.anomaly import AnomalySeverity
    kpis = _kpis(overprov=0, rightsz=5, underprov=0, idle=0)
    result = _base_result(kpis, [], [_anomaly("zombie", AnomalySeverity.CRITICAL)])
    out = tmp_path / "single_anomaly.pdf"
    meta = ReportBuilder().build(result, out)
    assert _pdf_is_valid(out)


def test_builder_letter_page_size(mixed_result, tmp_path):
    out = tmp_path / "letter.pdf"
    meta = ReportBuilder().build(mixed_result, out, page_size="Letter")
    assert _pdf_is_valid(out)
    assert meta.page_count >= 1


def test_builder_sets_run_id_in_meta(mixed_result, tmp_path):
    out = tmp_path / "r.pdf"
    meta = ReportBuilder().build(mixed_result, out, run_id="abc12345")
    assert meta.run_id == "abc12345"


# ── Large fleet pagination ────────────────────────────────────────────────────

def test_builder_100_instances_paginates(tmp_path):
    from tests.test_reporter.conftest import _kpis, _base_result, _rec
    from src.analytics.right_sizer import RecommendationType
    kpis = _kpis(overprov=50, rightsz=30, underprov=10, idle=10)
    recs = [_rec(i, RecommendationType.DOWNSIZE, savings=100.0) for i in range(100)]
    result = _base_result(kpis, recs, [])
    out = tmp_path / "large.pdf"
    meta = ReportBuilder().build(result, out)
    assert _pdf_is_valid(out)
    # 100 instances at 25/page = at least 4 detail pages + other sections
    assert meta.page_count >= 8


# ── File size bounds ──────────────────────────────────────────────────────────

def test_builder_file_size_reasonable(wasteful_result, tmp_path):
    out = tmp_path / "size_check.pdf"
    meta = ReportBuilder().build(wasteful_result, out)
    # 50 KB to 5 MB
    assert 50_000 <= meta.file_size_bytes <= 5_000_000


# ── Report metadata ───────────────────────────────────────────────────────────

def test_builder_pdf_metadata_set(mixed_result, tmp_path):
    out = tmp_path / "meta.pdf"
    ReportBuilder().build(mixed_result, out)
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(out))
        metadata = reader.metadata
        assert metadata is not None
    except ImportError:
        pytest.skip("pypdf not available")
