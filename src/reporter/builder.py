"""
src/reporter/builder.py
========================
ReportBuilder: orchestrates all sections into a complete PDF.
Uses ReportLab's SimpleDocTemplate with a custom canvas for footers.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from src.reporter.components.footer import draw_footer
from src.reporter.sections.cost_analysis import build_cost_analysis
from src.reporter.sections.cover import build_cover
from src.reporter.sections.cost_utilisation_scatter import build_cost_utilisation_scatter
from src.reporter.sections.instance_cost_breakdown import build_instance_cost_breakdown
from src.reporter.sections.storage_costs import build_storage_costs
from src.reporter.sections.object_storage_costs import build_object_storage_costs
from src.reporter.sections.recommendations import build_recommendations
from src.reporter.styles import MARGIN, PAGE_HEIGHT, PAGE_WIDTH
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult

log = get_logger(__name__)


@dataclass
class ReportMeta:
    path: Path
    page_count: int
    file_size_bytes: int
    run_id: str


class _FooterCanvas:
    """Mixin that injects footer drawing into ReportLab canvas calls."""


def _make_page_templates(doc: BaseDocTemplate, run_id: str) -> list:
    """Build page templates with footer callbacks."""
    frame = Frame(
        MARGIN,
        0.7 * inch,
        PAGE_WIDTH - 2 * MARGIN,
        PAGE_HEIGHT - MARGIN - 0.7 * inch,
        id="main",
        showBoundary=0,
    )

    def _on_page(canvas, doc_ref):
        draw_footer(canvas, doc_ref, run_id=run_id)

    return [PageTemplate(id="main", frames=[frame], onPage=_on_page)]


class ReportBuilder:
    """
    Builds a multi-page PDF report from an AnalyticsResult.
    Each section is wrapped in try/except; failures insert a placeholder page
    so the report is always deliverable.
    """

    def build(
        self,
        result: "AnalyticsResult",
        output_path: Path,
        page_size: str = "A4",
        config: Optional[dict] = None,
        run_id: Optional[str] = None,
    ) -> ReportMeta:
        if result is None:
            return self._empty_report(output_path, run_id or str(uuid.uuid4())[:8])

        run_id = run_id or str(uuid.uuid4())[:8]
        psize = LETTER if page_size.upper() == "LETTER" else A4

        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = BaseDocTemplate(
            str(output_path),
            pagesize=psize,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=0.7 * inch,
        )
        doc.addPageTemplates(_make_page_templates(doc, run_id))

        flowables = self._build_flowables(result, run_id, config or {})

        try:
            doc.build(flowables)
        except Exception as exc:
            log.error("report_build_failed", error=str(exc))
            raise

        # Set PDF metadata
        self._set_metadata(output_path, result, run_id)

        file_size = output_path.stat().st_size
        page_count = self._count_pages(output_path)

        log.info("report_built", path=str(output_path), pages=page_count, size_bytes=file_size)
        return ReportMeta(
            path=output_path,
            page_count=page_count,
            file_size_bytes=file_size,
            run_id=run_id,
        )

    def _build_flowables(self, result: "AnalyticsResult", run_id: str, config: dict) -> list:
        flowables: list = []
        sections = [
            ("Cover",                    lambda: build_cover(result, run_id)),
            ("Instance Cost Breakdown",  lambda: build_instance_cost_breakdown(result)),
            ("Storage Costs",            lambda: build_storage_costs(result)),
            ("Object Storage Costs",     lambda: build_object_storage_costs(result)),
            ("Cost Analysis",            lambda: build_cost_analysis(result)),
            ("Utilisation vs. Cost",     lambda: build_cost_utilisation_scatter(result)),
            ("Recommendations",          lambda: build_recommendations(result)),
        ]

        for section_name, builder_fn in sections:
            try:
                section_flowables = builder_fn()
                flowables.extend(section_flowables)
            except Exception as exc:
                log.error("section_build_failed", section=section_name, error=str(exc))
                flowables.extend(self._placeholder_section(section_name, run_id, str(exc)))

        return flowables

    def _placeholder_section(self, name: str, run_id: str, error: str) -> list:
        from src.reporter.styles import BODY, H2, DANGER
        from reportlab.lib.styles import ParagraphStyle
        err_style = ParagraphStyle("err", fontSize=9, textColor=DANGER, fontName="Helvetica-Oblique")
        return [
            Paragraph(f"{name} — Temporarily Unavailable", H2),
            Paragraph(f"Section could not be rendered for run {run_id}.", BODY),
            Paragraph(f"Error: {error[:200]}", err_style),
            PageBreak(),
        ]

    def _empty_report(self, output_path: Path, run_id: str) -> ReportMeta:
        """Generate a minimal single-page 'no data' report."""
        from src.reporter.styles import BODY, H2, NEUTRAL_200
        from reportlab.platypus import HRFlowable

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(str(output_path), pagesize=A4)
        flowables = [
            Paragraph("OCI Cloud Cost Optimization", H2),
            HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200),
            Spacer(1, 0.2 * inch),
            Paragraph("No data available for this reporting period.", BODY),
            Paragraph(f"Run ID: {run_id}", BODY),
        ]
        doc.build(flowables)
        file_size = output_path.stat().st_size
        return ReportMeta(path=output_path, page_count=1, file_size_bytes=file_size, run_id=run_id)

    def _set_metadata(self, output_path: Path, result: "AnalyticsResult", run_id: str) -> None:
        """Set PDF metadata (Title, Author, Subject, Keywords) via pypdf."""
        try:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(str(output_path))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.add_metadata({
                "/Title": "OCI Cloud Cost Optimization Report",
                "/Author": "OCI Cost Optimizer v1.0",
                "/Subject": f"Cost analysis {result.period_start.date()} to {result.period_end.date()}",
                "/Keywords": "OCI, FinOps, cost optimization, cloud",
                "/Creator": "OCI Cost Optimizer",
                "/Producer": "OCI Cost Optimizer v1.0",
            })
            with output_path.open("wb") as fh:
                writer.write(fh)
        except Exception as exc:
            log.warning("metadata_set_failed", error=str(exc))

    def _count_pages(self, output_path: Path) -> int:
        try:
            from pypdf import PdfReader
            return len(PdfReader(str(output_path)).pages)
        except Exception:
            return 0
