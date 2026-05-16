"""
src/reporter/resource_report/builder.py
=========================================
Builds a resource-utilization-only PDF from FleetStats.
No cost data. No business jargon. Pure technical metrics with sizing hints.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

from src.reporter.components.footer import draw_footer
from src.reporter.resource_report.charts import (
    chart_fleet_cpu, chart_fleet_memory, chart_sizing_donut, chart_instance_metrics,
)
from src.reporter.resource_report.data import (
    FleetStats, InstanceStats, SIZING_COLOR, SIZING_BG,
    SIZING_IDLE, SIZING_OVER, SIZING_RIGHT, SIZING_UNDER, SIZING_STOPPED, SIZING_NO_DATA,
)
from src.reporter.styles import (
    BODY_SMALL, CAPTION, CONTENT_WIDTH, H2, H3,
    MARGIN, NEUTRAL_200, NEUTRAL_50, PAGE_HEIGHT, PAGE_WIDTH,
    PRIMARY, PRIMARY_LIGHT, WHITE,
)
from reportlab.lib.styles import ParagraphStyle as _PS
from src.utils.logger import get_logger

log = get_logger(__name__)

_CHART_W = (CONTENT_WIDTH - 12) / inch  # subtract Frame's 6pt padding each side

# Paragraph styles for table cell word-wrap
_CS  = _PS("tc",  fontSize=7, leading=9,  spaceAfter=0, spaceBefore=0)
_CSB = _PS("tcb", fontSize=7, leading=9,  spaceAfter=0, spaceBefore=0, fontName="Helvetica-Bold")
_CS8 = _PS("tc8", fontSize=8, leading=10, spaceAfter=0, spaceBefore=0)


def _c(text: str, bold: bool = False, size8: bool = False) -> Paragraph:
    """Wrap string in Paragraph so long text word-wraps inside table cells."""
    style = _CSB if bold else (_CS8 if size8 else _CS)
    return Paragraph(str(text), style)


@dataclass
class ResourceReportMeta:
    path: Path
    page_count: int
    file_size_bytes: int
    run_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(val: Optional[float], decimals: int = 1, suffix: str = "%") -> str:
    if val is None:
        return "—"
    return f"{val:.{decimals}f}{suffix}"


def _fmt_size(val: Optional[float]) -> str:
    if val is None:
        return "—"
    if val >= 1024:
        return f"{val/1024:.1f} TB"
    return f"{val:.1f} GB"


def _fmt_bytes(mb_val: Optional[float]) -> str:
    """Auto-scale a value in MB to the most readable unit."""
    if mb_val is None:
        return "—"
    v = abs(mb_val)
    if v >= 1_048_576:
        return f"{mb_val/1_048_576:.2f} TB"
    if v >= 1_024:
        return f"{mb_val/1_024:.1f} GB"
    if v >= 1:
        return f"{mb_val:.0f} MB"
    return f"{mb_val*1024:.0f} KB"


def _img(buf: BytesIO, width_in: float, max_height_in: float = 4.5) -> Image:
    buf.seek(0)
    img = Image(buf)
    if img.imageWidth and img.imageHeight:
        aspect = img.imageHeight / img.imageWidth
        w = width_in * inch
        h = w * aspect
        if h > max_height_in * inch:
            h = max_height_in * inch
            w = h / aspect
        img.drawWidth  = w
        img.drawHeight = h
    else:
        img.drawWidth = width_in * inch
    return img


def _rule() -> Table:
    return Table(
        [[""]],
        colWidths=[CONTENT_WIDTH],
        style=TableStyle([
            ("LINEBELOW",     (0, 0), (-1, -1), 0.5, NEUTRAL_200),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
    )


def _make_page_templates(doc: BaseDocTemplate, run_id: str) -> list:
    frame = Frame(
        MARGIN, 0.65 * inch,
        PAGE_WIDTH - 2 * MARGIN,
        PAGE_HEIGHT - MARGIN - 0.65 * inch,
        id="main", showBoundary=0,
    )

    def _on_page(canvas, doc_ref):
        draw_footer(canvas, doc_ref, run_id=run_id)

    return [PageTemplate(id="main", frames=[frame], onPage=_on_page)]


# ---------------------------------------------------------------------------
# Cover
# ---------------------------------------------------------------------------

def _build_cover(fleet: FleetStats, run_id: str) -> list:
    title_s = _PS("res_t", fontSize=24, leading=30,
                              textColor=WHITE, fontName="Helvetica-Bold")
    sub_s   = _PS("res_s", fontSize=12, leading=17,
                              textColor=colors.HexColor("#90CAF9"), fontName="Helvetica")
    note_s  = _PS("res_n", fontSize=9,  leading=13,
                              textColor=colors.HexColor("#B0BEC5"), fontName="Helvetica")

    cover_rows = [
        [Paragraph("OCI Resource Utilisation Report", title_s)],
        [Spacer(1, 0.12 * inch)],
    ]
    if fleet.tenancy_name:
        cover_rows.append([Paragraph(
            f"Tenancy: {fleet.tenancy_name}"
            + (f" &nbsp;|&nbsp; Compartment: {fleet.compartment_name}" if fleet.compartment_name else ""),
            sub_s,
        )])
        cover_rows.append([Spacer(1, 0.08 * inch)])
    cover_rows += [
        [Paragraph(
            f"Period: {fleet.period_start} → {fleet.period_end} &nbsp;|&nbsp; "
            f"{fleet.collection_days}-day window &nbsp;|&nbsp; "
            f"{len(fleet.instances)} instances",
            sub_s,
        )],
        [Spacer(1, 0.12 * inch)],
        [Paragraph(
            f"Boot volumes: {len(fleet.boot_volumes)} &nbsp;|&nbsp; "
            f"Block volumes: {len(fleet.block_volumes)} &nbsp;|&nbsp; "
            f"Object storage buckets: {len(fleet.object_storage)}",
            sub_s,
        )],
        [Spacer(1, 0.2 * inch)],
        [Paragraph(
            "Resource utilisation report",
            note_s,
        )],
        [Spacer(1, 0.10 * inch)],
        [Paragraph(f"Run ID: {run_id}", note_s)],
    ]

    tbl = Table(
        cover_rows,
        colWidths=[CONTENT_WIDTH],
        style=TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#0F2D52")),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (-1, -1), 22),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 22),
        ]),
    )
    return [tbl, Spacer(1, 0.28 * inch)]


# ---------------------------------------------------------------------------
# Terminology / definitions section
# ---------------------------------------------------------------------------

def _build_definitions() -> list:
    elems: list = []
    elems.append(Paragraph("Metric Definitions", H3))

    definitions = [
        ("Avg (Average)",
         "The mean value across all data points in the collection period. "
         "Useful for typical load but can be skewed by brief spikes."),
        ("p95 (95th Percentile)",
         "95% of all measurements were below this value. "
         "Primary signal for sizing decisions — captures sustained peaks "
         "while ignoring the top 5% of outlier spikes."),
        ("p99 (99th Percentile)",
         "99% of measurements were below this value. "
         "Highlights near-worst-case spikes. Relevant for latency-sensitive workloads."),
        ("Peak (Maximum)",
         "The single highest value recorded in the period. "
         "Can be a one-time event; weight alongside p95 rather than in isolation."),
        ("oCPU",
         "Oracle CPU — one oCPU equals two vCPUs on Intel/AMD hardware. "
         "OCI Flex shapes let you configure oCPU count independently of memory."),
        ("vCPU",
         "Virtual CPU thread visible to the OS — typically 2× the oCPU count on x86 hardware."),
    ]

    rows = [["Term", "Definition"]]
    ts: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME",      (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
    ]
    for term, defn in definitions:
        rows.append([term, _c(defn)])

    elems.append(Table(
        rows,
        colWidths=[CONTENT_WIDTH * 0.22, CONTENT_WIDTH * 0.78],
        style=TableStyle(ts),
    ))
    elems.append(Spacer(1, 0.18 * inch))

    elems.append(Paragraph("Sizing Labels", H3))
    sizing_defs = [
        (SIZING_IDLE,
         "CPU p95 < 2% — instance is running but effectively idle. "
         "Review whether it should be stopped."),
        (SIZING_OVER,
         "CPU p95 2–20% (and memory p95 < 40%) — provisioned significantly above demand. "
         "Consider a smaller shape."),
        (SIZING_RIGHT,
         "CPU p95 20–80% — utilisation is in the healthy operating range. No action needed."),
        (SIZING_UNDER,
         "CPU p95 > 80% — demand is near the resource ceiling. "
         "Consider a larger shape or redistributing load."),
        (SIZING_STOPPED,
         "Instance is not in RUNNING state — no metric data was collected."),
        (SIZING_NO_DATA,
         "Instance is RUNNING but the monitoring agent returned no data points."),
    ]
    sz_rows = [["Label", "Meaning"]]
    sz_ts: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
    ]
    for i, (label, meaning) in enumerate(sizing_defs, start=1):
        sz_rows.append([label, _c(meaning)])
        hex_c = SIZING_COLOR.get(label, "#9A9A9A")
        sz_ts += [
            ("TEXTCOLOR", (0, i), (0, i), colors.HexColor(hex_c)),
            ("FONTNAME",  (0, i), (0, i), "Helvetica-Bold"),
        ]

    elems.append(Table(
        sz_rows,
        colWidths=[CONTENT_WIDTH * 0.22, CONTENT_WIDTH * 0.78],
        style=TableStyle(sz_ts),
    ))
    return elems


# ---------------------------------------------------------------------------
# Fleet summary
# ---------------------------------------------------------------------------

def _build_fleet_summary(fleet: FleetStats) -> list:
    elems: list = []
    elems.append(Paragraph("Fleet Overview", H2))
    elems.append(_rule())
    elems.append(Spacer(1, 0.1 * inch))

    cpu_p95 = fleet.fleet_cpu_p95_avg()
    mem_p95 = fleet.fleet_mem_p95_avg()

    kpi_data = [
        ["Total", "Running", "Stopped", "Fleet CPU p95 (avg)", "Fleet Mem p95 (avg)"],
        [str(len(fleet.instances)), str(len(fleet.running)), str(len(fleet.stopped)),
         _fmt(cpu_p95), _fmt(mem_p95)],
    ]
    cw = CONTENT_WIDTH / 5
    elems.append(Table(kpi_data, colWidths=[cw] * 5, style=TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 1), (-1, 1), 15),
        ("TEXTCOLOR",     (0, 1), (-1, 1), PRIMARY),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("GRID",          (0, 0), (-1, -1), 0.5, NEUTRAL_200),
    ])))
    elems.append(Spacer(1, 0.2 * inch))

    # All-instances table
    # Cols: Name | Shape | State | oCPU | vCPU | Mem GiB | CPU p95 | CPU peak | Mem p95 | Mem peak | Sizing
    elems.append(Paragraph("All Instances", H3))
    headers = ["Instance", "Shape", "State", "oCPU", "vCPU", "Mem\nGiB",
               "CPU\np95", "CPU\npeak", "Mem\np95", "Mem\npeak", "Sizing"]
    rows2 = [headers]
    ts2: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("ALIGN",         (3, 0), (9, -1),  "RIGHT"),
        ("ALIGN",         (0, 0), (2, -1),  "LEFT"),
        ("ALIGN",         (10, 0), (10, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
    ]
    for ri, inst in enumerate(fleet.instances, start=1):
        sz = inst.sizing
        shape_short = (inst.shape
                       .replace("VM.Standard.", "")
                       .replace("VM.Optimized", "Opt")
                       .replace(".Flex", " Flex"))
        rows2.append([
            _c(inst.name),
            _c(shape_short),
            inst.lifecycle_state,
            _fmt(inst.ocpus, 1, ""),
            str(inst.vcpus) if inst.vcpus is not None else "—",
            _fmt(inst.memory_in_gbs, 0, ""),
            _fmt(inst.cpu_p95),
            _fmt(inst.cpu_peak),
            _fmt(inst.mem_p95),
            _fmt(inst.mem_peak),
            sz,
        ])
        hex_c = SIZING_COLOR.get(sz, "#9A9A9A")
        ts2 += [
            ("TEXTCOLOR", (10, ri), (10, ri), colors.HexColor(hex_c)),
            ("FONTNAME",  (10, ri), (10, ri), "Helvetica-Bold"),
            ("FONTNAME",  (7,  ri), (7,  ri), "Helvetica-Bold"),
            ("FONTNAME",  (9,  ri), (9,  ri), "Helvetica-Bold"),
        ]

    # Widths sum to 1.0 — state col wide enough for "RUNNING"/"STOPPED"
    col_w = [
        CONTENT_WIDTH * 0.17,   # name
        CONTENT_WIDTH * 0.10,   # shape
        CONTENT_WIDTH * 0.09,   # state
        CONTENT_WIDTH * 0.055,  # oCPU
        CONTENT_WIDTH * 0.05,   # vCPU
        CONTENT_WIDTH * 0.055,  # Mem GiB
        CONTENT_WIDTH * 0.065,  # CPU p95
        CONTENT_WIDTH * 0.065,  # CPU peak
        CONTENT_WIDTH * 0.065,  # Mem p95
        CONTENT_WIDTH * 0.065,  # Mem peak
        CONTENT_WIDTH * 0.14,   # Sizing
    ]
    elems.append(Table(rows2, colWidths=col_w, style=TableStyle(ts2), repeatRows=1))
    elems.append(Spacer(1, 0.2 * inch))

    # Sizing guidance table
    elems.append(Paragraph("Sizing Guidance", H3))
    _GUIDANCE = {
        SIZING_IDLE:    "Review for shutdown. If still needed, reduce to smallest available shape.",
        SIZING_OVER:    "Consider halving oCPU (e.g. 4 → 2 oCPU).",
        SIZING_RIGHT:   "No change — utilisation is healthy.",
        SIZING_UNDER:   "Consider increasing oCPU or redistributing load.",
        SIZING_STOPPED: "Verify whether instance is still needed.",
        SIZING_NO_DATA: "Check monitoring agent is installed and running.",
    }
    sg_rows = [["Instance", "oCPU", "vCPU", "Label", "Guidance"]]
    sg_ts: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("ALIGN",         (1, 0), (2, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
    ]
    for ri, inst in enumerate(fleet.instances, start=1):
        sz = inst.sizing
        hex_c = SIZING_COLOR.get(sz, "#9A9A9A")
        sg_rows.append([
            _c(inst.name),
            _fmt(inst.ocpus, 1, ""),
            str(inst.vcpus) if inst.vcpus is not None else "—",
            sz,
            _c(_GUIDANCE.get(sz, "")),
        ])
        sg_ts += [
            ("TEXTCOLOR", (3, ri), (3, ri), colors.HexColor(hex_c)),
            ("FONTNAME",  (3, ri), (3, ri), "Helvetica-Bold"),
        ]

    elems.append(Table(
        sg_rows,
        colWidths=[
            CONTENT_WIDTH * 0.22,
            CONTENT_WIDTH * 0.09,
            CONTENT_WIDTH * 0.09,
            CONTENT_WIDTH * 0.16,
            CONTENT_WIDTH * 0.44,
        ],
        style=TableStyle(sg_ts),
        repeatRows=1,
    ))

    # Compact sizing donut — inline at bottom of fleet summary
    elems.append(Spacer(1, 0.18 * inch))
    donut = _img(chart_sizing_donut(fleet, 3.2, 3.2), 3.2, 3.4)
    elems.append(Table([[donut]], colWidths=[CONTENT_WIDTH],
                       style=TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")])))
    return elems


# ---------------------------------------------------------------------------
# Fleet charts
# ---------------------------------------------------------------------------

def _build_fleet_charts(fleet: FleetStats) -> list:
    elems: list = []

    # CPU — full page
    elems.append(PageBreak())
    elems.append(Paragraph("Fleet CPU Utilisation", H2))
    elems.append(_rule())
    elems.append(Spacer(1, 0.10 * inch))
    elems.append(_img(chart_fleet_cpu(fleet, _CHART_W, 9.0), _CHART_W, 9.5))

    # Memory — full page
    elems.append(PageBreak())
    elems.append(Paragraph("Fleet Memory Utilisation", H2))
    elems.append(_rule())
    elems.append(Spacer(1, 0.10 * inch))
    elems.append(_img(chart_fleet_memory(fleet, _CHART_W, 9.0), _CHART_W, 9.5))

    return elems


# ---------------------------------------------------------------------------
# Storage tables
# ---------------------------------------------------------------------------

def _build_boot_volumes_table(fleet: FleetStats) -> list:
    elems: list = []
    elems.append(Paragraph("Boot Volumes", H3))

    if not fleet.boot_volumes:
        elems.append(Paragraph("No boot volume data collected.", BODY_SMALL))
        elems.append(Spacer(1, 0.1 * inch))
        return elems

    rows = [["Volume Name", "State", "Size", "VPU/GB", "Attached Instance"]]
    ts: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ALIGN",         (2, 0), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
    ]
    for bv in fleet.boot_volumes:
        rows.append([
            _c(bv.name),
            bv.lifecycle_state,
            f"{bv.size_gb} GB",
            str(bv.vpu_per_gb),
            _c(bv.attached_instance or "—"),
        ])

    elems.append(Table(
        rows,
        colWidths=[
            CONTENT_WIDTH * 0.30,
            CONTENT_WIDTH * 0.12,
            CONTENT_WIDTH * 0.10,
            CONTENT_WIDTH * 0.08,
            CONTENT_WIDTH * 0.40,
        ],
        style=TableStyle(ts),
        repeatRows=1,
    ))
    elems.append(Spacer(1, 0.2 * inch))
    return elems


def _build_block_volumes_table(fleet: FleetStats) -> list:
    elems: list = []
    elems.append(Paragraph("Block (Data) Volumes", H3))

    if not fleet.block_volumes:
        elems.append(Paragraph("No block volume data collected.", BODY_SMALL))
        elems.append(Spacer(1, 0.1 * inch))
        return elems

    rows = [["Volume Name", "State", "Size", "VPU/\nGB",
             "Rd IOPS\n(avg)", "Wr IOPS\n(avg)", "Attached Instance(s)"]]
    ts: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ALIGN",         (2, 0), (5, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
    ]
    for ri, vol in enumerate(fleet.block_volumes, start=1):
        att_str = ", ".join(vol.attached_instances) if vol.attached_instances else "Unattached"
        rows.append([
            _c(vol.name),
            vol.lifecycle_state,
            f"{vol.size_gb} GB",
            str(vol.vpu_per_gb),
            _fmt(vol.read_iops_avg, 1, ""),
            _fmt(vol.write_iops_avg, 1, ""),
            _c(att_str),
        ])
        if not vol.attached_instances:
            ts += [("TEXTCOLOR", (6, ri), (6, ri), colors.HexColor("#9A9A9A"))]

    elems.append(Table(
        rows,
        colWidths=[
            CONTENT_WIDTH * 0.22,
            CONTENT_WIDTH * 0.10,
            CONTENT_WIDTH * 0.08,
            CONTENT_WIDTH * 0.07,
            CONTENT_WIDTH * 0.09,
            CONTENT_WIDTH * 0.09,
            CONTENT_WIDTH * 0.35,
        ],
        style=TableStyle(ts),
        repeatRows=1,
    ))
    elems.append(Spacer(1, 0.2 * inch))
    return elems


def _build_object_storage_table(fleet: FleetStats) -> list:
    elems: list = []
    elems.append(Paragraph("Object Storage (S3-equivalent) Buckets", H3))

    if not fleet.object_storage:
        elems.append(Paragraph("No object storage data collected.", BODY_SMALL))
        elems.append(Spacer(1, 0.1 * inch))
        return elems

    total_objects  = sum(b.approximate_count or 0 for b in fleet.object_storage)
    total_size_gb  = sum(b.approximate_size_gb or 0.0 for b in fleet.object_storage)
    kpi_data = [
        ["Total Buckets", "Total Objects (approx)", "Total Size (approx)"],
        [str(len(fleet.object_storage)), f"{total_objects:,}", _fmt_size(total_size_gb)],
    ]
    cw3 = CONTENT_WIDTH / 3
    elems.append(Table(kpi_data, colWidths=[cw3] * 3, style=TableStyle([
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
    ])))
    elems.append(Spacer(1, 0.12 * inch))

    rows = [["Bucket Name", "Storage Tier", "Objects\n(approx)", "Size\n(approx)"]]
    ts: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ALIGN",         (2, 0), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
    ]
    for bucket in fleet.object_storage:
        cnt = f"{bucket.approximate_count:,}" if bucket.approximate_count is not None else "—"
        rows.append([
            bucket.name,
            bucket.storage_tier,
            cnt,
            _fmt_size(bucket.approximate_size_gb),
        ])

    elems.append(Table(
        rows,
        colWidths=[
            CONTENT_WIDTH * 0.50,
            CONTENT_WIDTH * 0.18,
            CONTENT_WIDTH * 0.16,
            CONTENT_WIDTH * 0.16,
        ],
        style=TableStyle(ts),
        repeatRows=1,
    ))
    return elems


# ---------------------------------------------------------------------------
# Per-instance detail
# ---------------------------------------------------------------------------

def _build_instance_detail(inst: InstanceStats) -> list:
    elems: list = []
    sz     = inst.sizing
    sz_hex = SIZING_COLOR.get(sz, "#9A9A9A")
    sz_bg  = SIZING_BG.get(sz, "#F5F5F5")

    elems.append(Table(
        [[inst.name, inst.shape, inst.lifecycle_state, f"▶  {sz}"]],
        colWidths=[
            CONTENT_WIDTH * 0.28, CONTENT_WIDTH * 0.37,
            CONTENT_WIDTH * 0.13, CONTENT_WIDTH * 0.22,
        ],
        style=TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor(sz_bg)),
            ("FONTNAME",      (0, 0), (0,  0),  "Helvetica-Bold"),
            ("FONTNAME",      (3, 0), (3,  0),  "Helvetica-Bold"),
            ("TEXTCOLOR",     (3, 0), (3,  0),  colors.HexColor(sz_hex)),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("ALIGN",         (3, 0), (3,  0),  "RIGHT"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 7),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
            ("LINEBELOW",     (0, 0), (-1, -1), 1.2, colors.HexColor(sz_hex)),
        ]),
    ))
    elems.append(Spacer(1, 0.05 * inch))

    # Provisioned capacity line
    cap_parts = []
    if inst.ocpus is not None:
        cap_parts.append(f"oCPU: {inst.ocpus:.1f}")
    if inst.vcpus is not None:
        cap_parts.append(f"vCPU: {inst.vcpus}")
    if inst.memory_in_gbs is not None:
        cap_parts.append(f"Memory: {inst.memory_in_gbs:.0f} GiB")
    if cap_parts:
        cap_s = _PS("cap", fontSize=8, leading=11,
                               textColor=colors.HexColor("#555555"), fontName="Helvetica")
        elems.append(Paragraph("  Provisioned — " + "  |  ".join(cap_parts), cap_s))
        elems.append(Spacer(1, 0.04 * inch))

    if inst.lifecycle_state.upper() != "RUNNING":
        elems.append(Paragraph(
            f"Instance is {inst.lifecycle_state} — no utilisation metrics available.",
            BODY_SMALL,
        ))
        elems.append(Spacer(1, 0.14 * inch))
        return elems

    chart_buf = chart_instance_metrics(inst, width_in=_CHART_W * 0.60, height_in=2.1)

    detail_rows: list[list] = [["Metric", "Avg", "p50", "p95", "p99", "Peak"]]
    ts_detail: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), PRIMARY_LIGHT),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME",      (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ("GRID",          (0, 0), (-1, -1), 0.4, NEUTRAL_200),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, NEUTRAL_50]),
        ("FONTNAME",      (5, 1), (5, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",     (5, 1), (5, -1), colors.HexColor(sz_hex)),
    ]

    def _mrow(label: str, avg, p50, p95, p99, peak) -> list:
        return [label, _fmt(avg), _fmt(p50), _fmt(p95), _fmt(p99), _fmt(peak)]

    if inst.cpu_avg is not None:
        detail_rows.append(_mrow("CPU (%)",
            inst.cpu_avg, inst.cpu_p50, inst.cpu_p95, inst.cpu_p99, inst.cpu_peak))
    if inst.mem_avg is not None:
        detail_rows.append(_mrow("Memory (%)",
            inst.mem_avg, inst.mem_p50, inst.mem_p95, inst.mem_p99, inst.mem_peak))
    if inst.net_in_avg_mb is not None:
        detail_rows.append(["Net In",
            _fmt_bytes(inst.net_in_avg_mb), "—", "—", "—",
            _fmt_bytes(inst.net_in_peak_mb)])
    if inst.net_out_avg_mb is not None:
        detail_rows.append(["Net Out",
            _fmt_bytes(inst.net_out_avg_mb), "—", "—", "—",
            _fmt_bytes(inst.net_out_peak_mb)])
    if inst.disk_read_ops_avg is not None:
        detail_rows.append(["Disk Rd (ops/s)",
            _fmt(inst.disk_read_ops_avg, 1, ""), "—", "—", "—", "—"])
    if inst.disk_write_ops_avg is not None:
        detail_rows.append(["Disk Wr (ops/s)",
            _fmt(inst.disk_write_ops_avg, 1, ""), "—", "—", "—", "—"])

    rw = CONTENT_WIDTH * 0.40 / 6
    detail_tbl = Table(
        detail_rows,
        colWidths=[rw * 2.2] + [rw * 0.76] * 5,
        style=TableStyle(ts_detail),
    )

    elems.append(Table(
        [[_img(chart_buf, _CHART_W * 0.60, 2.3), detail_tbl]],
        colWidths=[CONTENT_WIDTH * 0.60, CONTENT_WIDTH * 0.40],
        style=TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (1, 0), (1, 0),   6),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]),
    ))
    elems.append(Spacer(1, 0.18 * inch))
    return elems


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_resource_report(fleet: FleetStats, out_path: Path) -> ResourceReportMeta:
    """Build a resource-utilisation PDF. Returns metadata about the file."""
    run_id = uuid.uuid4().hex[:8]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(out_path),
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=0.65 * inch,
    )
    doc.addPageTemplates(_make_page_templates(doc, run_id))

    story: list = []

    # Cover
    story.extend(_build_cover(fleet, run_id))

    # Definitions (terminology + sizing labels) — on same page as cover
    story.append(Spacer(1, 0.1 * inch))
    story.extend(_build_definitions())

    # Fleet summary: KPIs + all-instances table + sizing guidance
    story.append(PageBreak())
    story.extend(_build_fleet_summary(fleet))

    # Fleet charts
    story.extend(_build_fleet_charts(fleet))

    # Storage inventory
    story.append(PageBreak())
    story.append(Paragraph("Storage Inventory", H2))
    story.append(_rule())
    story.append(Spacer(1, 0.12 * inch))
    story.extend(_build_boot_volumes_table(fleet))
    story.extend(_build_block_volumes_table(fleet))
    story.extend(_build_object_storage_table(fleet))

    # Per-instance detail
    story.append(PageBreak())
    story.append(Paragraph("Instance Detail", H2))
    story.append(_rule())
    story.append(Spacer(1, 0.1 * inch))

    for inst in fleet.instances:
        try:
            story.extend(_build_instance_detail(inst))
        except Exception as exc:
            log.warning("instance_section_failed", name=inst.name, error=str(exc))
            story.append(Paragraph(f"[{inst.name}: render error — {exc}]", BODY_SMALL))

    doc.build(story)
    size = out_path.stat().st_size
    log.info("resource_report_built", path=str(out_path),
             size_bytes=size, instances=len(fleet.instances), run_id=run_id)

    return ResourceReportMeta(
        path=out_path,
        page_count=doc.page,
        file_size_bytes=size,
        run_id=run_id,
    )
