"""
src/reporter/charts/trend.py
============================
Daily fleet cost trend line with 7-day moving average and anomaly markers.
"""
from __future__ import annotations

from io import BytesIO
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from src.reporter.charts.base import (
    add_chart_labels, figure_to_bytes, no_data_chart, CHART_DPI,
)
from src.reporter.styles import (
    ACCENT_HEX, DANGER_HEX, NEUTRAL_200_HEX, NEUTRAL_500_HEX,
    PRIMARY_HEX, WARNING_HEX,
)


def chart_daily_cost_trend(
    daily_costs: list[dict],
    anomaly_dates: list[str] | None = None,
    width_in: float = 7.5,
    height_in: float = 3.5,
) -> BytesIO:
    """
    Line chart of daily fleet cost with a 7-day moving average.

    daily_costs: list of dicts with keys: date (str ISO), cost (float)
    anomaly_dates: list of date strings where cost anomalies were detected
    """
    if not daily_costs or len(daily_costs) < 2:
        return no_data_chart("Daily Fleet Cost Trend", width_in, height_in)

    dates = [d["date"] for d in daily_costs]
    costs = [float(d.get("cost") or 0.0) for d in daily_costs]

    x = np.arange(len(dates))
    costs_arr = np.array(costs)

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=CHART_DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(NEUTRAL_200_HEX)
    ax.spines["bottom"].set_color(NEUTRAL_200_HEX)

    # Main line
    ax.plot(x, costs_arr, color=PRIMARY_HEX, linewidth=1.5, alpha=0.8, label="Daily cost")
    ax.fill_between(x, costs_arr, alpha=0.08, color=PRIMARY_HEX)

    # 7-day moving average
    if len(costs_arr) >= 7:
        ma = np.convolve(costs_arr, np.ones(7) / 7, mode="valid")
        ma_x = np.arange(6, len(costs_arr))
        ax.plot(ma_x, ma, color=ACCENT_HEX, linewidth=1.5, linestyle="--",
                alpha=0.9, label="7-day avg")

    # Anomaly markers
    if anomaly_dates:
        anom_set = set(anomaly_dates)
        for i, d in enumerate(dates):
            if d in anom_set:
                ax.axvline(x=i, color=DANGER_HEX, linewidth=0.8, linestyle=":", alpha=0.7)
                ax.plot(i, costs_arr[i], "^", color=DANGER_HEX, markersize=6, zorder=5)

    # X tick labels — show every N-th date
    n = max(1, len(dates) // 6)
    tick_positions = list(range(0, len(dates), n))
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(
        [dates[i][:10] for i in tick_positions],
        rotation=30, ha="right", fontsize=7,
    )

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.tick_params(colors=NEUTRAL_500_HEX, labelsize=8)
    ax.yaxis.grid(True, color=NEUTRAL_200_HEX, linewidth=0.5, linestyle="--")

    ax.legend(fontsize=7, loc="upper left", framealpha=0.6)

    add_chart_labels(
        ax,
        "Daily Fleet Cost Trend",
        xlabel="",
        ylabel="Daily Cost (USD)",
        caption="▲ = cost anomaly detected  |  Dashed = 7-day moving average",
    )

    return figure_to_bytes(fig)
