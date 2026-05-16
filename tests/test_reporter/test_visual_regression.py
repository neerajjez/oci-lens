"""
Visual regression guard for the reporter.
Generates the PDF for SCENARIO_MIXED and saves it to tests/golden/sample_report.pdf.
Asserts page_count and file_size stay within expected bounds.
"""
from __future__ import annotations

from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent.parent / "golden"
GOLDEN_PDF = GOLDEN_DIR / "sample_report.pdf"


def test_generate_golden_sample_report(mixed_result, tmp_path):
    """Generate a golden sample PDF for visual review during PRs."""
    from src.reporter.builder import ReportBuilder

    out = tmp_path / "sample_report.pdf"
    meta = ReportBuilder().build(mixed_result, out, run_id="golden-test")

    assert meta.page_count >= 5
    assert 50_000 <= meta.file_size_bytes <= 5_000_000

    # Save to golden directory for manual review
    GOLDEN_DIR.mkdir(exist_ok=True)
    import shutil
    shutil.copy(out, GOLDEN_PDF)
    assert GOLDEN_PDF.exists()


def test_golden_pdf_has_expected_structure(mixed_result, tmp_path):
    """Verify the PDF structure didn't change unexpectedly."""
    from src.reporter.builder import ReportBuilder
    from pypdf import PdfReader

    out = tmp_path / "struct_check.pdf"
    meta = ReportBuilder().build(mixed_result, out, run_id="struct-test")

    reader = PdfReader(str(out))
    page_count = len(reader.pages)

    # Regression guard: must have at least 5 pages (cover, exec summary, cost, util, recs...)
    assert page_count >= 5

    # File size should be between 50 KB and 5 MB
    assert 50_000 <= out.stat().st_size <= 5_000_000
