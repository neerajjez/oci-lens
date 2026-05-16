"""
src/reporter/resource_report/charts.py
========================================
Chart functions for the resource-utilization report.
All functions return BytesIO PNG. No cost data.
"""
from __future__ import annotations

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from src.reporter.charts.base import figure_to_bytes, no_data_chart
from src.reporter.resource_report.data import (
    FleetStats, InstanceStats, SIZING_COLOR,
)
from src.reporter.styles import NEUTRAL_200_HEX, NEUTRAL_500_HEX, NEUTRAL_900_HEX

# ---------------------------------------------------------------------------
# Rich 20-color palette — one distinct color per instance
# ---------------------------------------------------------------------------
_PALETTE = [
    "#1565C0",  # dark blue
    "#2E7D32",  # dark green
    "#F57F17",  # amber
    "#6A1B9A",  # purple
    "#00838F",  # teal
    "#C62828",  # red
    "#0277BD",  # light blue
    "#558B2F",  # olive green
    "#EF6C00",  # orange
    "#4527A0",  # deep purple
    "#00695C",  # dark teal
    "#AD1457",  # pink
    "#283593",  # indigo
    "#827717",  # dark lime
    "#4E342E",  # brown
    "#37474F",  # blue grey
    "#0D47A1",  # royal blue
    "#1B5E20",  # forest green
    "#BF360C",  # deep orange
    "#880E4F",  # dark pink
]


def _pct(val: float | None) -> float:
    return val if val is not None else 0.0


def _to_rgba(hex_color: str, alpha: float) -> tuple:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16)/255, int(h[2:4], 16)/255, int(h[4:6], 16)/255
    return (r, g, b, alpha)


# ---------------------------------------------------------------------------
# Fleet-level charts
# ---------------------------------------------------------------------------

def chart_fleet_cpu(fleet: FleetStats, width_in: float = 7.2, height_in: float = 3.6) -> BytesIO:
    """Horizontal grouped bar: Avg / p95 / Peak CPU%, distinct color per instance, legend at bottom."""
    instances = fleet.instances
    if not instances:
        return no_data_chart("Fleet CPU Utilisation", width_in, height_in)

    names  = [i.name for i in instances]
    avgs   = [_pct(i.cpu_avg)  for i in instances]
    p95s   = [_pct(i.cpu_p95)  for i in instances]
    peaks  = [_pct(i.cpu_peak) for i in instances]
    n      = len(instances)

    y  = np.arange(n)
    bh = 0.26

    fig_h = max(height_in, n * 0.64 + 1.6)
    fig, ax = plt.subplots(figsize=(width_in, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")

    for i in range(n):
        col    = _PALETTE[i % len(_PALETTE)]
        ax.barh(y[i] + bh, avgs[i],  bh, color=_to_rgba(col, 0.35), edgecolor="white", lw=0.5)
        ax.barh(y[i],      p95s[i],  bh, color=_to_rgba(col, 0.88), edgecolor="white", lw=0.5)
        ax.barh(y[i] - bh, peaks[i], bh, color=_to_rgba(col, 0.62), edgecolor="white", lw=0.5,
                hatch="///", zorder=3)
        if peaks[i] > 1:
            ax.text(peaks[i] + 0.4, y[i] - bh, f"{peaks[i]:.1f}%",
                    va="center", fontsize=6, color=NEUTRAL_900_HEX, fontweight="bold")

    ax.axvline(20, color="#EF6C00", lw=1.0, ls="--", alpha=0.8, zorder=2)
    ax.axvline(80, color="#C62828", lw=1.0, ls="--", alpha=0.8, zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("CPU Utilisation (%)", fontsize=8, color=NEUTRAL_500_HEX)
    ax.set_title("Fleet CPU — Avg / p95 / Peak", fontsize=10, fontweight="bold",
                 color=NEUTRAL_900_HEX, pad=8)
    ax.set_xlim(left=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)
    ax.xaxis.grid(True, color=NEUTRAL_200_HEX, lw=0.5, ls="--", zorder=0)
    ax.yaxis.grid(False)

    legend_handles = [
        mpatches.Patch(facecolor=_to_rgba("#555555", 0.35), label="Avg"),
        mpatches.Patch(facecolor=_to_rgba("#555555", 0.88), label="p95"),
        mpatches.Patch(facecolor=_to_rgba("#555555", 0.62), hatch="///", label="Peak"),
        plt.Line2D([0], [0], color="#EF6C00", lw=1.2, ls="--", label="20 % over-prov"),
        plt.Line2D([0], [0], color="#C62828", lw=1.2, ls="--", label="80 % under-prov"),
    ]
    ax.legend(handles=legend_handles, loc="upper center",
              bbox_to_anchor=(0.5, -0.07), ncol=5,
              fontsize=7.5, framealpha=0.95, edgecolor=NEUTRAL_200_HEX)
    fig.tight_layout(rect=[0, 0.11, 1, 1])
    return figure_to_bytes(fig)


def chart_fleet_memory(fleet: FleetStats, width_in: float = 7.2, height_in: float = 3.6) -> BytesIO:
    """Horizontal grouped bar: Avg / p95 / Peak Memory%, distinct color per instance, legend at bottom."""
    instances = fleet.instances
    if not instances:
        return no_data_chart("Fleet Memory Utilisation", width_in, height_in)

    names  = [i.name for i in instances]
    avgs   = [_pct(i.mem_avg)  for i in instances]
    p95s   = [_pct(i.mem_p95)  for i in instances]
    peaks  = [_pct(i.mem_peak) for i in instances]
    n      = len(instances)

    y  = np.arange(n)
    bh = 0.26

    fig_h = max(height_in, n * 0.64 + 1.6)
    fig, ax = plt.subplots(figsize=(width_in, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")

    for i in range(n):
        col = _PALETTE[i % len(_PALETTE)]
        ax.barh(y[i] + bh, avgs[i],  bh, color=_to_rgba(col, 0.35), edgecolor="white", lw=0.5)
        ax.barh(y[i],      p95s[i],  bh, color=_to_rgba(col, 0.88), edgecolor="white", lw=0.5)
        ax.barh(y[i] - bh, peaks[i], bh, color=_to_rgba(col, 0.62), edgecolor="white", lw=0.5,
                hatch="///", zorder=3)
        if peaks[i] > 1:
            ax.text(peaks[i] + 0.4, y[i] - bh, f"{peaks[i]:.1f}%",
                    va="center", fontsize=6, color=NEUTRAL_900_HEX, fontweight="bold")

    max_peak = max(peaks) if any(p > 0 for p in peaks) else 0
    ax.axvline(50, color="#EF6C00", lw=1.0, ls="--", alpha=0.8, zorder=2)
    ax.axvline(85, color="#C62828", lw=1.0, ls="--", alpha=0.8, zorder=2)
    ax.set_xlim(left=0, right=max(100.0, max_peak * 1.15))
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("Memory Utilisation (%)", fontsize=8, color=NEUTRAL_500_HEX)
    ax.set_title("Fleet Memory — Avg / p95 / Peak", fontsize=10, fontweight="bold",
                 color=NEUTRAL_900_HEX, pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)
    ax.xaxis.grid(True, color=NEUTRAL_200_HEX, lw=0.5, ls="--", zorder=0)
    ax.yaxis.grid(False)

    legend_handles = [
        mpatches.Patch(facecolor=_to_rgba("#555555", 0.35), label="Avg"),
        mpatches.Patch(facecolor=_to_rgba("#555555", 0.88), label="p95"),
        mpatches.Patch(facecolor=_to_rgba("#555555", 0.62), hatch="///", label="Peak"),
        plt.Line2D([0], [0], color="#EF6C00", lw=1.2, ls="--", label="50 % threshold"),
        plt.Line2D([0], [0], color="#C62828", lw=1.2, ls="--", label="85 % threshold"),
    ]
    ax.legend(handles=legend_handles, loc="upper center",
              bbox_to_anchor=(0.5, -0.07), ncol=5,
              fontsize=7.5, framealpha=0.95, edgecolor=NEUTRAL_200_HEX)
    fig.tight_layout(rect=[0, 0.11, 1, 1])
    return figure_to_bytes(fig)


def chart_sizing_donut(fleet: FleetStats, width_in: float = 3.2, height_in: float = 3.2) -> BytesIO:
    """Donut: sizing label distribution. Legend at bottom."""
    counts = fleet.sizing_counts
    if not counts:
        return no_data_chart("Sizing Distribution", width_in, height_in)

    labels = list(counts.keys())
    sizes  = [counts[lb] for lb in labels]
    colors = [SIZING_COLOR.get(lb, "#9A9A9A") for lb in labels]

    fig, ax = plt.subplots(figsize=(width_in, height_in))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    wedges, _, autotexts = ax.pie(
        sizes, colors=colors, startangle=90,
        autopct="%1.0f%%", pctdistance=0.72,
        wedgeprops={"width": 0.54, "edgecolor": "white", "linewidth": 2.0},
    )
    for at in autotexts:
        at.set_fontsize(9)
        at.set_color("white")
        at.set_fontweight("bold")

    ax.legend(wedges, [f"{lb} ({counts[lb]})" for lb in labels],
              loc="upper center", bbox_to_anchor=(0.5, -0.05),
              fontsize=7.5, framealpha=0.95, edgecolor=NEUTRAL_200_HEX, ncol=2)
    ax.set_title("Sizing Distribution", fontsize=9, fontweight="bold",
                 color=NEUTRAL_900_HEX, pad=8)
    fig.tight_layout(rect=[0, 0.20, 1, 1])
    return figure_to_bytes(fig)


# ---------------------------------------------------------------------------
# Per-instance chart
# ---------------------------------------------------------------------------

def chart_instance_metrics(
    inst: InstanceStats, width_in: float = 6.8, height_in: float = 2.0
) -> BytesIO:
    """Grouped bar: CPU and Memory (Avg / p95 / Peak). Legend at bottom, % labels above bars."""
    has_cpu = inst.cpu_avg is not None
    has_mem = inst.mem_avg is not None
    if not has_cpu and not has_mem:
        return no_data_chart(f"{inst.name} — No Metrics", width_in, height_in)

    categories: list[str] = []
    avgs:  list[float] = []
    p95s:  list[float] = []
    peaks: list[float] = []

    if has_cpu:
        categories.append("CPU")
        avgs.append(_pct(inst.cpu_avg))
        p95s.append(_pct(inst.cpu_p95))
        peaks.append(_pct(inst.cpu_peak))
    if has_mem:
        categories.append("Memory")
        avgs.append(_pct(inst.mem_avg))
        p95s.append(_pct(inst.mem_p95))
        peaks.append(_pct(inst.mem_peak))

    x   = np.arange(len(categories))
    w   = 0.24
    col = SIZING_COLOR.get(inst.sizing, "#9A9A9A")

    fig, ax = plt.subplots(figsize=(width_in, height_in))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")

    ax.bar(x - w, avgs,  w, color=_to_rgba(col, 0.40), edgecolor="white", lw=0.5, label="Avg")
    ax.bar(x,     p95s,  w, color=_to_rgba(col, 0.90), edgecolor="white", lw=0.5, label="p95")
    ax.bar(x + w, peaks, w, color=_to_rgba(col, 0.65), edgecolor="white", lw=0.5,
           hatch="///", label="Peak")

    top = max(peaks, default=10)
    for xi, pv in zip(x + w, peaks):
        if pv > 0:
            ax.text(xi, pv + top * 0.04, f"{pv:.1f}%",
                    ha="center", va="bottom", fontsize=7.5,
                    fontweight="bold", color=NEUTRAL_900_HEX)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=9)
    ax.set_ylabel("Utilisation (%)", fontsize=8, color=NEUTRAL_500_HEX)
    ax.set_ylim(bottom=0, top=max(top * 1.30, 12))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)
    ax.yaxis.grid(True, color=NEUTRAL_200_HEX, lw=0.5, ls="--", zorder=0)
    ax.xaxis.grid(False)

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16),
              ncol=3, fontsize=7.5, framealpha=0.95, edgecolor=NEUTRAL_200_HEX)
    fig.tight_layout(rect=[0, 0.16, 1, 1])
    return figure_to_bytes(fig)
