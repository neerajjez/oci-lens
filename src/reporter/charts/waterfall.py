"""
src/reporter/charts/waterfall.py
=================================
Savings waterfall: current cost → savings by category → projected new cost.
"""
from __future__ import annotations

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from src.reporter.charts.base import figure_to_bytes, no_data_chart, CHART_DPI
from src.reporter.styles import (
    ACCENT_HEX, DANGER_HEX, NEUTRAL_200_HEX, NEUTRAL_500_HEX,
    PRIMARY_HEX, SUCCESS_HEX, WARNING_HEX,
)


def chart_savings_waterfall(
    current_monthly_cost: float,
    downsize_savings: float,
    terminate_savings: float,
    orphaned_savings: float,
    width_in: float = 7.0,
    height_in: float = 3.5,
) -> BytesIO:
    """
    Waterfall chart showing cost decomposition and savings potential.
    """
    if current_monthly_cost <= 0:
        return no_data_chart("Monthly Savings Waterfall", width_in, height_in)

    total_savings = downsize_savings + terminate_savings + orphaned_savings
    new_cost = max(0.0, current_monthly_cost - total_savings)

    categories = ["Current\nMonthly Cost", "Downsize\nSavings", "Terminate\nSavings",
                  "Orphaned\nResources", "Projected\nNew Cost"]
    values = [current_monthly_cost, -downsize_savings, -terminate_savings,
              -orphaned_savings, new_cost]
    colors = [PRIMARY_HEX, SUCCESS_HEX, ACCENT_HEX, WARNING_HEX, DANGER_HEX]

    # Running totals for waterfall positioning
    running = 0.0
    bottoms = []
    heights = []
    bar_colors = []

    for i, (cat, val, col) in enumerate(zip(categories, values, colors)):
        if i == 0 or i == len(categories) - 1:
            bottoms.append(0)
            heights.append(val)
        else:
            running += val
            if val < 0:
                bottoms.append(current_monthly_cost + running)
                heights.append(-val)
            else:
                bottoms.append(running)
                heights.append(val)
        bar_colors.append(col)

    # Recalculate for standard waterfall
    bottoms = []
    heights = []
    cumulative = current_monthly_cost
    for i, (cat, val) in enumerate(zip(categories, values)):
        if i == 0:
            bottoms.append(0)
            heights.append(current_monthly_cost)
        elif i == len(categories) - 1:
            bottoms.append(0)
            heights.append(new_cost)
        else:
            savings = abs(val)
            bottoms.append(cumulative - savings)
            heights.append(savings)
            cumulative -= savings

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bars = ax.bar(range(len(categories)), heights, bottom=bottoms, color=bar_colors,
                  alpha=0.80, width=0.55, edgecolor="white", linewidth=0.5)

    # Value labels on bars
    for bar, bottom, height in zip(bars, bottoms, heights):
        if height > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bottom + height / 2,
                f"${height:,.0f}",
                ha="center", va="center", fontsize=7, color="white", fontweight="bold",
            )

    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories, fontsize=7)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)
    ax.yaxis.grid(True, color=NEUTRAL_200_HEX, linewidth=0.5, linestyle="--")

    ax.set_title(
        "Monthly Savings Waterfall",
        fontsize=11, fontweight="bold", color=PRIMARY_HEX, pad=8, loc="left",
    )

    pct = (total_savings / current_monthly_cost * 100) if current_monthly_cost > 0 else 0
    fig.text(
        0.01, 0.01,
        f"Total recoverable: ${total_savings:,.0f}/month ({pct:.1f}%)",
        fontsize=7, color=NEUTRAL_500_HEX, style="italic",
    )

    return figure_to_bytes(fig)
