"""
src/reporter/sections/instance_cost_breakdown.py
=================================================
Per-instance cost breakdown table: OCPU, Memory, Compute, Storage, Total.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer

from src.reporter.components.data_table import styled_table
from src.reporter.styles import BODY, CAPTION, H2, NEUTRAL_200

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult

_ROWS_PER_PAGE = 25


def build_instance_cost_breakdown(result: "AnalyticsResult") -> list:
    flowables: list = []

    costs = getattr(result, "instance_costs", None) or []

    # Build OCPU/memory lookup from recommendations
    shape_info: dict[str, tuple[int, float]] = {}  # display_name → (ocpu, ram_gb)
    for rec in (result.recommendations or []):
        cfg = getattr(rec, "current_config", None)
        if cfg:
            shape_info[rec.instance_name] = (
                int(getattr(cfg, "ocpu", 0) or 0),
                float(getattr(cfg, "ram_gb", 0) or 0),
            )

    # Show all instances (billing or no billing)
    rows_data = []
    for c in costs:
        ocpu, ram = shape_info.get(c.display_name, (0, 0.0))
        rows_data.append({
            "name": c.display_name,
            "shape": c.shape or "—",
            "ocpu": ocpu,
            "ram": ram,
            "compute": c.compute_cost,
            "storage": c.storage_cost,
            "total": c.total_cost,
            "daily": c.daily_cost_avg,
            "no_data": c.no_billing_data,
        })

    if not rows_data:
        flowables.append(Paragraph("Instance Cost Breakdown", H2))
        flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
        flowables.append(Spacer(1, 0.1 * inch))
        flowables.append(Paragraph("No instance data available for this reporting period.", BODY))
        flowables.append(PageBreak())
        return flowables

    fleet_compute = sum(r["compute"] for r in rows_data)
    fleet_storage = sum(r["storage"] for r in rows_data)
    fleet_total   = sum(r["total"]   for r in rows_data)
    fleet_daily   = sum(r["daily"]   for r in rows_data)
    no_data_count = sum(1 for r in rows_data if r["no_data"])

    total_pages = max(1, (len(rows_data) + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE)

    headers = ["Instance", "Shape", "OCPU", "Mem (GB)", "Compute/mo", "Storage/mo", "Total/mo", "Daily"]
    col_widths = [
        1.55 * inch,  # Instance
        1.10 * inch,  # Shape
        0.55 * inch,  # OCPU
        0.65 * inch,  # Mem
        0.80 * inch,  # Compute
        0.80 * inch,  # Storage
        0.80 * inch,  # Total
        0.65 * inch,  # Daily
    ]

    for page_idx in range(total_pages):
        chunk = rows_data[page_idx * _ROWS_PER_PAGE: (page_idx + 1) * _ROWS_PER_PAGE]

        flowables.append(Paragraph("Instance Cost Breakdown", H2))
        if total_pages > 1:
            flowables.append(Paragraph(f"Page {page_idx + 1} of {total_pages}", CAPTION))
        flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
        flowables.append(Spacer(1, 0.1 * inch))

        if page_idx == 0:
            note = f"Fleet total: <b>${fleet_total:,.2f}/mo</b>  —  compute ${fleet_compute:,.2f}  +  storage ${fleet_storage:,.2f}"
            if no_data_count:
                note += f"  |  {no_data_count} instance(s) with no billing data shown as $0.00"
            flowables.append(Paragraph(note, BODY))
            flowables.append(Spacer(1, 0.08 * inch))

        rows = []
        for r in chunk:
            ocpu_str = str(r["ocpu"]) if r["ocpu"] else "—"
            ram_str  = f"{r['ram']:.0f}" if r["ram"] else "—"
            name = r["name"] if r["name"] and not r["name"].startswith("ocid1.") else "Unknown"
            rows.append([
                name[:26],
                r["shape"][:18],
                ocpu_str,
                ram_str,
                f"${r['compute']:,.2f}",
                f"${r['storage']:,.2f}",
                f"${r['total']:,.2f}",
                f"${r['daily']:,.2f}",
            ])

        if page_idx == total_pages - 1:
            rows.append([
                "TOTAL", "",
                "", "",
                f"${fleet_compute:,.2f}",
                f"${fleet_storage:,.2f}",
                f"${fleet_total:,.2f}",
                f"${fleet_daily:,.2f}",
            ])

        tbl = styled_table(headers, rows, col_widths=col_widths, font_size=7, max_col_chars=30)
        flowables.append(tbl)
        flowables.append(Spacer(1, 0.08 * inch))
        flowables.append(Paragraph(
            "Compute = OCI billing matched to instance OCID. "
            "Storage = boot + attached block volume billing attributed at instance level.",
            CAPTION,
        ))
        flowables.append(PageBreak())

    return flowables
