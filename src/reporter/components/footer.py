"""
src/reporter/components/footer.py
====================================
Canvas-level footer callback: "Page N of M | OCI Cost Optimizer | Run {run_id}".
"""
from __future__ import annotations

from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

from src.reporter.styles import NEUTRAL_500, NEUTRAL_200, MARGIN, PAGE_WIDTH


def draw_footer(canvas: Canvas, doc: object, run_id: str = "") -> None:
    """
    Called on every page via the onPage/onLaterPages hooks.
    Draws a thin rule + footer text at the bottom of the page.
    """
    canvas.saveState()

    footer_y = 0.45 * inch
    rule_y = footer_y + 0.15 * inch

    # Thin rule
    canvas.setStrokeColor(NEUTRAL_200)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, rule_y, PAGE_WIDTH - MARGIN, rule_y)

    # Footer text
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(NEUTRAL_500)

    # Left: run id
    if run_id:
        canvas.drawString(MARGIN, footer_y, f"Run ID: {run_id[:8]}")

    # Center: tool name
    center_text = "OCI Cloud Cost Optimizer"
    canvas.drawCentredString(PAGE_WIDTH / 2, footer_y, center_text)

    # Right: page number (ReportLab uses doc.page for current page)
    page_num = getattr(doc, "page", canvas.getPageNumber())
    canvas.drawRightString(PAGE_WIDTH - MARGIN, footer_y, f"Page {page_num}")

    canvas.restoreState()
