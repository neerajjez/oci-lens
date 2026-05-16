"""
src/reporter/charts/base.py
===========================
Base chart utilities: DPI, styling, and shared rendering helpers.
All chart functions return BytesIO containing a PNG image.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.figure import Figure

from src.reporter.styles import (
    CHART_DPI,
    NEUTRAL_200_HEX,
    NEUTRAL_500_HEX,
    NEUTRAL_900_HEX,
    PRIMARY_HEX,
)

_FONT_FAMILY = "sans-serif"


def _apply_base_style(ax: Any) -> None:
    """Apply consistent minimal style to an axes object."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)
    ax.yaxis.grid(True, color=NEUTRAL_200_HEX, linewidth=0.5, linestyle="--")
    ax.xaxis.grid(False)
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)
    ax.set_facecolor("white")


def new_figure(width_in: float = 7.0, height_in: float = 3.5) -> tuple[Figure, Any]:
    """Create a new figure with base styling applied."""
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    _apply_base_style(ax)
    return fig, ax


def figure_to_bytes(fig: Figure) -> BytesIO:
    """Serialize a matplotlib figure to PNG bytes and close it."""
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def no_data_chart(title: str, width_in: float = 7.0, height_in: float = 3.5) -> BytesIO:
    """Return a placeholder chart PNG when data is unavailable."""
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor(NEUTRAL_200_HEX)
    ax.text(
        0.5, 0.5,
        f"{title}\n(No data available)",
        ha="center", va="center",
        fontsize=10, color=NEUTRAL_500_HEX,
        transform=ax.transAxes,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return figure_to_bytes(fig)


def add_chart_labels(ax: Any, title: str, xlabel: str = "", ylabel: str = "", caption: str = "") -> None:
    """Add title, axis labels, and optional caption to axes."""
    ax.set_title(title, fontsize=11, fontweight="bold", color=PRIMARY_HEX, pad=8, loc="left")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8, color=NEUTRAL_500_HEX)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8, color=NEUTRAL_500_HEX)
    if caption:
        ax.figure.text(
            0.01, -0.02, caption,
            fontsize=7, color=NEUTRAL_500_HEX, style="italic",
            transform=ax.transAxes,
        )
