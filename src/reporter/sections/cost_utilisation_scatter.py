"""
src/reporter/sections/cost_utilisation_scatter.py
==================================================
Utilisation vs. Cost Analysis: summary table + scatter chart + cost bar chart.
"""
from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image, PageBreak, Paragraph, Spacer, Table, TableStyle

from src.reporter.charts.scatter import chart_cost_utilization_scatter
from src.reporter.components.data_table import styled_table
from src.reporter.styles import BODY, CAPTION, H2, H3, MARGIN, NEUTRAL_200, PAGE_WIDTH

if TYPE_CHECKING:
    from src.analytics.engine import AnalyticsResult


def _img(buf: BytesIO, width: float, height: float) -> Image:
    buf.seek(0)
    return Image(buf, width=width, height=height)


def _chart_cost_bar(instance_data: list[dict], width_in: float, height_in: float) -> BytesIO:
    """Horizontal bar chart of cost per instance, colored by recommendation type."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from src.reporter.styles import CHART_DPI

    COLOR_MAP = {
        "DOWNSIZE":             "#EF6C00",
        "TERMINATE":            "#C62828",
        "UPSIZE_OR_INVESTIGATE":"#1565C0",
        "MONITOR":              "#0288D1",
        "OPTIMAL":              "#2E7D32",
    }

    data = sorted(instance_data, key=lambda x: x.get("monthly_cost", 0), reverse=True)[:20]
    if not data:
        from src.reporter.charts.base import no_data_chart
        return no_data_chart("Cost per Instance", width_in, height_in)

    names  = [d["name"][:22] for d in data]
    costs  = [d.get("monthly_cost", 0) for d in data]
    rtypes = [d.get("rec_type", "MONITOR") for d in data]
    bar_colors = [COLOR_MAP.get(rt, "#757575") for rt in rtypes]

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    bars = ax.barh(range(len(names)), costs, color=bar_colors, height=0.65, edgecolor="white", linewidth=0.5)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Monthly Cost (USD)", fontsize=8, color="#6B6B6B")
    ax.set_title("Monthly Cost per Instance", fontsize=11, fontweight="bold",
                 color="#0F2D52", pad=8, loc="left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#E5E5E5")
    ax.spines["bottom"].set_color("#E5E5E5")
    ax.xaxis.grid(True, color="#E5E5E5", linewidth=0.5, linestyle="--")
    ax.yaxis.grid(False)
    ax.set_facecolor("white")
    ax.tick_params(colors="#6B6B6B", labelsize=7)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))

    for bar, cost in zip(bars, costs):
        if cost > 0:
            ax.text(bar.get_width() + max(costs) * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"${cost:,.0f}", va="center", ha="left", fontsize=6.5, color="#333333")

    # Legend
    from matplotlib.patches import Patch
    legend_items = [
        Patch(facecolor=COLOR_MAP["DOWNSIZE"],             label="Downsize"),
        Patch(facecolor=COLOR_MAP["OPTIMAL"],              label="Optimal"),
        Patch(facecolor=COLOR_MAP["MONITOR"],              label="Monitor"),
        Patch(facecolor=COLOR_MAP["TERMINATE"],            label="Review"),
        Patch(facecolor=COLOR_MAP["UPSIZE_OR_INVESTIGATE"],label="Investigate"),
    ]
    ax.legend(handles=legend_items, loc="lower right", fontsize=7,
              framealpha=0.9, edgecolor="#E5E5E5")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def build_cost_utilisation_scatter(result: "AnalyticsResult") -> list:
    flowables: list = []

    flowables.append(Paragraph("Utilisation vs. Cost Analysis", H2))
    flowables.append(HRFlowable(width="100%", thickness=0.5, color=NEUTRAL_200))
    flowables.append(Spacer(1, 0.1 * inch))

    instance_costs = getattr(result, "instance_costs", None) or []

    # Build score + rec_type lookup
    score_lookup: dict[str, float]  = {}
    rtype_lookup: dict[str, str]    = {}
    ocpu_lookup:  dict[str, int]    = {}
    for entry in (getattr(result.fleet_kpis, "top_5_wasteful", None) or []):
        name = entry.get("display_name", "")
        if name:
            score_lookup[name] = float(entry.get("composite_score") or 0.0)
    for entry in (getattr(result.fleet_kpis, "top_5_efficient", None) or []):
        name = entry.get("display_name", "")
        if name:
            score_lookup[name] = float(entry.get("composite_score") or 0.0)
    for rec in (result.recommendations or []):
        rtype_lookup[rec.instance_name] = rec.recommendation_type.value
        cfg = getattr(rec, "current_config", None)
        if cfg:
            ocpu_lookup[rec.instance_name] = int(getattr(cfg, "ocpu", 0) or 0)

    # ── Summary table ──────────────────────────────────────────────────────
    table_rows = []
    for c in instance_costs:
        score  = score_lookup.get(c.display_name, 0.0)
        rtype  = rtype_lookup.get(c.display_name, "—")
        ocpu   = ocpu_lookup.get(c.display_name, 0)
        label_map = {
            "DOWNSIZE": "Downsize",
            "TERMINATE": "Review",
            "UPSIZE_OR_INVESTIGATE": "Investigate",
            "MONITOR": "Monitor",
            "OPTIMAL": "Optimal",
        }
        action = label_map.get(rtype, rtype)
        util_str  = f"{score * 100:.0f}%" if score > 0 else "—"
        ocpu_str  = str(ocpu) if ocpu else "—"
        table_rows.append([
            c.display_name[:26],
            ocpu_str,
            util_str,
            f"${c.compute_cost:,.2f}",
            f"${c.storage_cost:,.2f}",
            f"${c.total_cost:,.2f}",
            action,
        ])

    if table_rows:
        headers = ["Instance", "OCPU", "Util%", "Compute/mo", "Storage/mo", "Total/mo", "Action"]
        col_widths = [
            1.70 * inch,
            0.55 * inch,
            0.55 * inch,
            0.90 * inch,
            0.90 * inch,
            0.90 * inch,
            0.80 * inch,
        ]
        flowables.append(Paragraph("Cost & Resource Utilisation Summary", H3))
        flowables.append(Spacer(1, 0.06 * inch))
        flowables.append(styled_table(headers, table_rows, col_widths=col_widths, font_size=7))
        flowables.append(Spacer(1, 0.06 * inch))
        flowables.append(Paragraph(
            "Util% = composite utilisation score (CPU 45% + Memory 35% + I/O 20%).",
            CAPTION,
        ))
    else:
        flowables.append(Paragraph(
            "Per-instance cost data not yet available for this period.", BODY,
        ))

    flowables.append(Spacer(1, 0.2 * inch))

    # ── 2 Charts ──────────────────────────────────────────────────────────
    chart_w  = PAGE_WIDTH - 2 * MARGIN
    half_w   = (chart_w - 0.15 * inch) / 2
    half_h   = half_w * 0.75

    billed = [c for c in instance_costs if not c.no_billing_data and c.total_cost > 0]
    instance_data = [
        {
            "name":            c.display_name,
            "composite_score": score_lookup.get(c.display_name, 0.0),
            "monthly_cost":    c.total_cost,
            "rec_type":        rtype_lookup.get(c.display_name, "MONITOR"),
            "vcpu_count":      1,
        }
        for c in billed
    ]

    if instance_data:
        flowables.append(Paragraph("Cost vs. Utilisation Charts", H3))
        flowables.append(Spacer(1, 0.06 * inch))

        try:
            scatter_buf = chart_cost_utilization_scatter(instance_data, width_in=3.8, height_in=3.2)
            bar_buf     = _chart_cost_bar(instance_data, width_in=3.8, height_in=3.2)

            chart_row = [[
                _img(scatter_buf, half_w, half_h),
                _img(bar_buf,     half_w, half_h),
            ]]
            chart_tbl = Table(chart_row, colWidths=[half_w, half_w])
            chart_tbl.setStyle(TableStyle([
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ]))
            flowables.append(chart_tbl)
            flowables.append(Spacer(1, 0.06 * inch))
            flowables.append(Paragraph(
                "Left: Cost vs. Utilisation quadrant — top-left = high cost, low utilisation (priority targets). "
                "Right: Monthly cost by instance — color indicates recommendation type.",
                CAPTION,
            ))
        except Exception:
            flowables.append(Paragraph("(Charts temporarily unavailable)", BODY))

    flowables.append(PageBreak())
    return flowables
