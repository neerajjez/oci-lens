"""
src/reporter/sections/object_storage_costs.py
==============================================
Object Storage Costs section: buckets table with size, object count, and cost.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer, Table, TableStyle

from src.reporter.components.data_table import styled_table
from src.reporter.styles import (
    BODY, CAPTION, H2, NEUTRAL_200, NEUTRAL_50, PRIMARY, WHITE,
)

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def build_object_storage_costs(result: "AnalyticsResult") -> list:
    """Returns flowables for the Object Storage Costs section."""
    flowables: list = []

    flowables.append(Paragraph("Object Storage Costs", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    buckets = getattr(result, "buckets", None) or []
    cost_map: dict[str, float] = getattr(result, "object_storage_costs", None) or {}

    if not buckets and not cost_map:
        flowables.append(Paragraph(
            "No object storage (bucket) data collected for this reporting period. "
            "Ensure the OCI Object Storage collector is enabled in config.yaml.",
            BODY,
        ))
        flowables.append(PageBreak())
        return flowables

    # Merge bucket inventory with cost map
    bucket_rows_data: list[tuple] = []
    seen_names: set[str] = set()
    for b in buckets:
        name = str(b.get("name", ""))
        seen_names.add(name)
        cost = cost_map.get(name, 0.0)
        size_gb = float(b.get("approximate_size_gb", 0.0) or 0.0)
        count = int(b.get("approximate_count", 0) or 0)
        bucket_rows_data.append((name, str(b.get("storage_tier", "Standard")), size_gb, count, cost))

    # Add cost-only entries (billing records matched by name but no inventory entry)
    for bname, cost in cost_map.items():
        if bname not in seen_names:
            bucket_rows_data.append((bname, "—", 0.0, 0, cost))

    bucket_rows_data.sort(key=lambda x: x[4], reverse=True)

    total_cost = sum(r[4] for r in bucket_rows_data)
    total_size_gb = sum(r[2] for r in bucket_rows_data)
    total_objects = sum(r[3] for r in bucket_rows_data)

    # ── Summary KPI row ───────────────────────────────────────────────────────
    kpi_data = [
        ["Total Buckets", "Total Objects (approx)", "Total Size (approx)", "Total Monthly Cost"],
        [
            str(len(bucket_rows_data)),
            f"{total_objects:,}",
            _fmt_size(total_size_gb),
            f"${total_cost:,.2f}",
        ],
    ]
    cw4 = 1.65 * inch
    flowables.append(Table(kpi_data, colWidths=[cw4] * 4, style=TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 1), (-1, 1), 13),
        ("TEXTCOLOR",     (0, 1), (-1, 1), PRIMARY),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID",          (0, 0), (-1, -1), 0.5, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, 1), [NEUTRAL_50]),
    ])))
    flowables.append(Spacer(1, 0.15 * inch))

    # ── Bucket detail table ───────────────────────────────────────────────────
    headers = ["Bucket Name", "Storage Tier", "Objects (approx)", "Size (approx)", "Monthly Cost"]
    col_widths = [2.4 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch]
    rows = []
    for name, tier, size_gb, count, cost in bucket_rows_data:
        rows.append([
            name[:36],
            tier,
            f"{count:,}" if count else "—",
            _fmt_size(size_gb) if size_gb > 0 else "—",
            f"${cost:,.2f}" if cost > 0 else "—",
        ])

    flowables.append(styled_table(headers, rows, col_widths=col_widths, font_size=7.5))
    flowables.append(Spacer(1, 0.1 * inch))
    flowables.append(Paragraph(
        "Object storage costs are attributed by matching OCI Usage API billing records "
        "to bucket names. Buckets shown with '—' cost have inventory data but no matching "
        "billing record for this period.",
        CAPTION,
    ))
    flowables.append(PageBreak())
    return flowables


def _fmt_size(size_gb: float) -> str:
    if size_gb >= 1024:
        return f"{size_gb / 1024:.2f} TB"
    return f"{size_gb:.1f} GB"
