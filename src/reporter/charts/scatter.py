"""
src/reporter/charts/scatter.py
===============================
Cost vs. Utilization scatter: x=composite_score, y=monthly_cost, bubble=vcpu_count.
Four quadrant labels: Sweet spot / Money pit / Strapped / Healthy.
"""
from __future__ import annotations

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.reporter.charts.base import (
    add_chart_labels, figure_to_bytes, no_data_chart, CHART_DPI,
)
from src.reporter.styles import (
    ACCENT_HEX, DANGER_HEX, NEUTRAL_200_HEX, NEUTRAL_500_HEX,
    NEUTRAL_900_HEX, PRIMARY_HEX, WARNING_HEX,
)


def chart_cost_utilization_scatter(
    instance_data: list[dict],
    width_in: float = 7.5,
    height_in: float = 4.5,
) -> BytesIO:
    """
    Scatter plot: composite_score (x) vs monthly_cost (y).
    Bubble size proportional to vcpu_count.
    Four quadrants labeled.

    instance_data: list of dicts with:
        name, composite_score (float 0-1), monthly_cost (float), vcpu_count (int)
    """
    if not instance_data:
        return no_data_chart("Cost vs. Utilization", width_in, height_in)

    scores = np.array([d.get("composite_score") or 0.0 for d in instance_data])
    costs = np.array([d.get("monthly_cost") or 0.0 for d in instance_data])
    vcpus = np.array([max(1, d.get("vcpu_count") or 1) for d in instance_data])

    bubble_sizes = np.clip(vcpus * 12, 20, 400)

    # Color by quadrant
    colors = []
    for s, c in zip(scores, costs):
        if s < 0.40 and c > np.median(costs):
            colors.append(DANGER_HEX)      # Money pit
        elif s >= 0.40 and c > np.median(costs):
            colors.append(ACCENT_HEX)      # Sweet spot
        elif s >= 0.40 and c <= np.median(costs):
            colors.append(PRIMARY_HEX)     # Healthy
        else:
            colors.append(WARNING_HEX)     # Strapped

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)

    ax.scatter(scores, costs, s=bubble_sizes, c=colors, alpha=0.65, edgecolors="white", linewidths=0.5)

    # Quadrant dividers
    mid_score = 0.40
    mid_cost = float(np.median(costs)) if len(costs) > 0 else 1.0
    ax.axvline(x=mid_score, color=NEUTRAL_200_HEX, linestyle="--", linewidth=0.8)
    ax.axhline(y=mid_cost, color=NEUTRAL_200_HEX, linestyle="--", linewidth=0.8)

    # Quadrant labels
    x_lo, x_hi = ax.get_xlim() if ax.get_xlim() != (0, 1) else (0.0, 1.05)
    y_lo, y_hi = ax.get_ylim()

    def _label(x, y, text, color):
        ax.text(
            x, y, text,
            fontsize=7, color=color, alpha=0.7, fontstyle="italic",
            ha="center", va="center",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.6, edgecolor="none"),
        )

    y_range = max(y_hi - y_lo, 1.0)
    _label(mid_score * 0.5, mid_cost + y_range * 0.15, "Healthy\n(low cost, low util)", PRIMARY_HEX)
    _label(mid_score * 0.5, mid_cost - y_range * 0.15, "Strapped\n(high cost, low util)", WARNING_HEX)
    _label(mid_score + (1.0 - mid_score) * 0.5, mid_cost + y_range * 0.15, "Sweet spot\n(high cost, good util)", ACCENT_HEX)
    _label(mid_score + (1.0 - mid_score) * 0.5, mid_cost - y_range * 0.15, "Money pit\n(low cost, under-used)", DANGER_HEX)

    add_chart_labels(
        ax,
        "Cost vs. Utilization",
        xlabel="Composite Utilization Score",
        ylabel="Monthly Cost (USD)",
        caption="Bubble size ∝ vCPU count  |  Dashed lines at fleet medians",
    )
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)

    return figure_to_bytes(fig)


import matplotlib.ticker as mticker  # noqa: E402 (needed for formatter references above)
