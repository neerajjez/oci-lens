"""
src/reporter/charts/heatmap.py
================================
Utilization heatmap: instance × metric type.
"""
from __future__ import annotations

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from src.reporter.charts.base import figure_to_bytes, no_data_chart, CHART_DPI
from src.reporter.styles import NEUTRAL_500_HEX, PRIMARY_HEX


def chart_utilization_heatmap(
    instance_metrics: list[dict],
    max_instances: int = 30,
    width_in: float = 7.5,
    height_in: float = 5.0,
) -> BytesIO:
    """
    Heatmap of utilization metrics per instance.

    instance_metrics: list of dicts with:
        name (str), cpu_p95 (float), memory_p95 (float|None),
        network_in_p95 (float), disk_read_iops_p95 (float)
    """
    if not instance_metrics:
        return no_data_chart("Utilization Heatmap", width_in, height_in)

    data = instance_metrics[:max_instances]
    labels_y = [d.get("name", "")[:20] for d in data]
    labels_x = ["CPU p95 %", "Memory p95 %", "Net In p95\n(kbps/1000)", "Disk IOPS p95\n(/100)"]

    def _norm(v, divisor=1.0):
        return min(100.0, (v or 0.0) / divisor)

    matrix = np.array([
        [
            _norm(d.get("cpu_p95")),
            _norm(d.get("memory_p95")) if d.get("memory_p95") is not None else np.nan,
            _norm(d.get("network_in_p95"), 1000.0),
            _norm(d.get("disk_read_iops_p95"), 100.0),
        ]
        for d in data
    ])

    fig, ax = plt.subplots(figsize=(width_in, max(3.0, len(data) * 0.25 + 1.5)), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")

    masked = np.ma.masked_invalid(matrix)
    im = ax.imshow(masked, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=100)

    ax.set_xticks(range(len(labels_x)))
    ax.set_xticklabels(labels_x, fontsize=7)
    ax.set_yticks(range(len(labels_y)))
    ax.set_yticklabels(labels_y, fontsize=6)

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("Utilization %", fontsize=7, color=NEUTRAL_500_HEX)
    cbar.ax.tick_params(labelsize=6)

    ax.set_title(
        "Instance Utilization Heatmap",
        fontsize=11, fontweight="bold", color=PRIMARY_HEX, pad=8, loc="left",
    )

    for spine in ax.spines.values():
        spine.set_visible(False)

    return figure_to_bytes(fig)
