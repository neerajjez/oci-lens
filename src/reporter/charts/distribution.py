"""
src/reporter/charts/distribution.py
=====================================
Composite score distribution histogram with four zone bands.
"""
from __future__ import annotations

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from src.reporter.charts.base import (
    add_chart_labels, figure_to_bytes, no_data_chart, CHART_DPI,
)
from src.reporter.styles import (
    NEUTRAL_200_HEX, NEUTRAL_500_HEX, PRIMARY_HEX,
    ZONE_IDLE, ZONE_OVERPROV, ZONE_RIGHTSZ, ZONE_UNDERPROV,
)


def chart_score_distribution(
    composite_scores: list[float],
    width_in: float = 7.0,
    height_in: float = 3.5,
) -> BytesIO:
    """
    Histogram of composite_score values with 4 shaded zones:
    Over-provisioned (< 0.30), Right-sized (0.30–0.70),
    Under-provisioned (> 0.70), plus idle count shown as annotation.
    """
    if not composite_scores:
        return no_data_chart("Composite Score Distribution", width_in, height_in)

    scores = np.array([s for s in composite_scores if s is not None], dtype=float)
    if len(scores) == 0:
        return no_data_chart("Composite Score Distribution", width_in, height_in)

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Zone backgrounds
    ax.axvspan(0.0, 0.30, alpha=0.12, color=ZONE_OVERPROV, zorder=0)
    ax.axvspan(0.30, 0.70, alpha=0.10, color=ZONE_RIGHTSZ, zorder=0)
    ax.axvspan(0.70, 1.01, alpha=0.12, color=ZONE_UNDERPROV, zorder=0)

    # Histogram
    n_bins = min(20, max(5, len(scores) // 2))
    ax.hist(scores, bins=np.linspace(0, 1, n_bins + 1), color=PRIMARY_HEX, alpha=0.75, edgecolor="white")

    # Zone labels
    y_top = ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1
    ax.text(0.15, y_top * 0.92, "Over-\nprovisioned", fontsize=7,
            color=ZONE_OVERPROV, ha="center", fontweight="bold")
    ax.text(0.50, y_top * 0.92, "Right-sized", fontsize=7,
            color="#795548", ha="center", fontweight="bold")
    ax.text(0.85, y_top * 0.92, "Under-\nprovisioned", fontsize=7,
            color=ZONE_UNDERPROV, ha="center", fontweight="bold")

    # Zone dividers
    for xv in (0.30, 0.70):
        ax.axvline(x=xv, color=NEUTRAL_200_HEX, linestyle="--", linewidth=0.8)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)
    ax.yaxis.grid(True, color=NEUTRAL_200_HEX, linewidth=0.5, linestyle="--")
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)

    add_chart_labels(
        ax,
        "Composite Utilization Score Distribution",
        xlabel="Composite Score (0 = wasted, 1 = fully utilized)",
        ylabel="Instance Count",
        caption="Score = 0.45×CPU + 0.35×Memory + 0.20×I/O  |  Target: 0.70",
    )

    return figure_to_bytes(fig)
