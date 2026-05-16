"""
src/reporter/charts/treemap.py
==============================
Cost treemap: boxes sized by total_cost, colored by composite_score (red→green).
Answers: "Where is the money going?"
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

from src.reporter.charts.base import figure_to_bytes, no_data_chart, CHART_DPI
from src.reporter.styles import NEUTRAL_500_HEX, NEUTRAL_900_HEX, PRIMARY_HEX

try:
    import squarify
    _HAS_SQUARIFY = True
except ImportError:
    _HAS_SQUARIFY = False


def chart_cost_treemap(
    instance_costs: list[dict],
    width_in: float = 7.5,
    height_in: float = 4.5,
) -> BytesIO:
    """
    Treemap where each rectangle = one instance.
    Area proportional to total_cost, color = composite_score (red→green).

    instance_costs: list of dicts with keys:
        name (str), total_cost (float), composite_score (float)
    """
    if not instance_costs or not _HAS_SQUARIFY:
        return no_data_chart("Cost Distribution by Instance", width_in, height_in)

    data = [d for d in instance_costs if (d.get("total_cost") or 0) > 0]
    if not data:
        return no_data_chart("Cost Distribution by Instance", width_in, height_in)

    data.sort(key=lambda x: x["total_cost"], reverse=True)
    data = data[:40]  # cap at 40 boxes for readability

    sizes = [d["total_cost"] for d in data]
    scores = [min(1.0, max(0.0, d.get("composite_score") or 0.0)) for d in data]
    labels = [
        f"{d['name'][:18]}\n${d['total_cost']:,.0f}"
        for d in data
    ]

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "score_cmap", ["#C62828", "#FFA726", "#2E7D32"]
    )
    face_colors = [cmap(s) for s in scores]

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    squarify.plot(
        sizes=sizes,
        label=labels,
        color=face_colors,
        alpha=0.85,
        ax=ax,
        text_kwargs={"fontsize": 6, "color": "white", "fontweight": "bold"},
        pad=True,
    )

    ax.set_title(
        "Cost Distribution by Instance",
        fontsize=11, fontweight="bold", color=PRIMARY_HEX, pad=8, loc="left",
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Color scale legend
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=mcolors.Normalize(vmin=0, vmax=1))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.03, pad=0.02, shrink=0.4)
    cbar.set_label("Composite Utilization Score", fontsize=7, color=NEUTRAL_500_HEX)
    cbar.ax.tick_params(labelsize=6)

    fig.text(
        0.01, 0.01,
        "Area ∝ monthly cost  |  Color: red = under-utilized, green = well-utilized",
        fontsize=6, color=NEUTRAL_500_HEX, style="italic",
    )

    return figure_to_bytes(fig)
