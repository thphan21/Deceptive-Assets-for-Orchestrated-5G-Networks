#!/usr/bin/env python3
"""
plot-honeytypes-across-densities.py
===================================

Compare the honey-asset campaign results across deployment densities.

Reads the ``results-evaluation-summary.json`` of every run found under

    <campaigns>/density-<N>/run<M>/results-evaluation-summary.json

and writes into the output directory:

  - 01_discovery_rates_across_densities.png
        Discovery rate of every honey-asset type per density. The legend also
        states each type's average discovery rate over the plotted densities.
  - 02_honeyfile_rates_across_densities.png
        Honeyfile discovery / interaction / engagement rate per density, plus
        the honey-binary execution rate. The legend also states each rate's
        average over the plotted densities.
  - rates_across_densities.csv
        The plotted numbers as a table.

Rate definitions (recomputed from the raw counts in the summary files):

  discovery rate    = discovered / deployed
  interaction rate  = interacted / deployed
  engagement rate   = engaged    / discovered
  execution rate    = executed honey binaries / deployed honey binaries

If a density has several runs, the per-run rates are averaged.

Example usage (defaults match the experiments/ directory layout, so from
experiments/analysis-campaigns/ no arguments are needed):

    python3 plot-honeytypes-across-densities.py

    python3 plot-honeytypes-across-densities.py \
        --campaigns ~/experiments/campaigns_allTypes \
        --out ~/experiments/analysis-campaigns/all-Honeytypes-plots
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless / file output
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

# --------------------------------------------------------------------------- #
# Configuration / constants
# --------------------------------------------------------------------------- #

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CAMPAIGNS = SCRIPT_DIR.parent / "campaigns_allTypes"
DEFAULT_OUT = SCRIPT_DIR / "all-Honeytypes-plots"

SUMMARY_FILE = "results-evaluation-summary.json"
DENSITY_DIR_RE = re.compile(r"^density-(\d+)$")

# Asset types as named in the summary JSON, in plotting order.
ASSET_LABELS = {
    "honeyfile": "Honeyfiles",
    "env": "Honey ENVs",
    "binary": "Honey binaries",
    "process": "Honey processes",
}

# metric -> (numerator count, denominator count)
RATE_DEFINITIONS = {
    "discovery": ("discovered", "deployed"),
    "interaction": ("interacted", "deployed"),
    "engagement": ("engaged", "discovered"),
    "execution": ("executed", "deployed"),
}

# One style per line, used in order. Colour is never the only cue: marker
# shape and dash pattern differ too, and marker sizes shrink from first to
# last so that points lying exactly on top of each other all stay visible.
SERIES_STYLES = [
    {"color": "#2a78d6", "marker": "o", "markersize": 11, "linestyle": "-"},
    {"color": "#1baf7a", "marker": "s", "markersize": 11, "linestyle": (0, (6, 3))},
    {"color": "#eb6834", "marker": "D", "markersize": 9, "linestyle": (0, (4, 2, 1, 2))},
    {"color": "#4a3aa7", "marker": "^", "markersize": 7.5, "linestyle": (0, (1, 2))},
]

INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#d9d8d2"


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

@dataclass
class Series:
    """One line of a plot: a label and one value per density (NaN = no data)."""
    label: str
    values: list[float]


def load_campaign_summaries(campaign_dir: str | Path) -> dict[int, list[dict]]:
    """Read every run's evaluation summary.

    Returns {density: [summary_of_run1, summary_of_run2, ...]}, where each
    summary is the parsed ``results-evaluation-summary.json`` of one run.
    """
    campaign_dir = Path(campaign_dir)
    if not campaign_dir.is_dir():
        raise FileNotFoundError(f"Campaign directory not found: {campaign_dir}")

    summaries: dict[int, list[dict]] = {}
    for density_dir in sorted(campaign_dir.iterdir()):
        m = DENSITY_DIR_RE.match(density_dir.name)
        if not m or not density_dir.is_dir():
            continue
        for summary_path in sorted(density_dir.glob(f"run*/{SUMMARY_FILE}")):
            with open(summary_path, encoding="utf-8") as fh:
                summaries.setdefault(int(m.group(1)), []).append(json.load(fh))

    if not summaries:
        raise FileNotFoundError(
            f"No density-*/run*/{SUMMARY_FILE} found under {campaign_dir}")
    return summaries


def _rate(numerator: float, denominator: float) -> float:
    """numerator / denominator, or NaN when nothing could be counted."""
    return numerator / denominator if denominator else math.nan


def _mean(values: list[float]) -> float:
    """Mean of the values that are not NaN (NaN if there are none)."""
    valid = [v for v in values if not math.isnan(v)]
    return sum(valid) / len(valid) if valid else math.nan


def rate_for_density(runs: list[dict], asset: str, metric: str) -> float:
    """Rate of one asset type at one density, averaged over that density's runs."""
    num_key, den_key = RATE_DEFINITIONS[metric]
    per_run = []
    for run in runs:
        counts = run.get(asset, {})
        per_run.append(_rate(counts.get(num_key, 0), counts.get(den_key, 0)))
    return _mean(per_run)


def rate_series(summaries: dict[int, list[dict]], densities: list[int],
                asset: str, metric: str, label: str) -> Series:
    """Build the line for one asset type / metric across all densities."""
    return Series(label, [rate_for_density(summaries[d], asset, metric)
                          for d in densities])


# --------------------------------------------------------------------------- #
# Plot helpers shared by both plots
# --------------------------------------------------------------------------- #

def _format_pct(value: float) -> str:
    return "n/a" if math.isnan(value) else f"{value * 100:.1f}%"


def _draw_rate_lines(ax, series: list[Series], show_average: bool = False) -> None:
    """Draw one line per series over evenly spaced density positions.

    With ``show_average`` the legend label of each line also states the mean
    of its plotted values.
    """
    for z, (s, style) in enumerate(zip(series, SERIES_STYLES)):
        label = s.label
        if show_average:
            label = f"{s.label} (avg {_format_pct(_mean(s.values))})"
        ax.plot(range(len(s.values)), s.values, label=label, linewidth=2,
                markeredgecolor="white", markeredgewidth=1.5,
                zorder=3 + z, clip_on=False, **style)


def _style_rate_axes(ax, densities: list[int], title: str, legend_cols: int) -> None:
    """Shared look: percent y-axis from 0 to 100, densities on x, legend below."""
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=14)

    ax.set_xticks(range(len(densities)))
    ax.set_xticklabels([f"{d}%" for d in densities])
    ax.set_xlim(-0.15, len(densities) - 0.85)
    ax.set_xlabel("Honey asset density", color=INK_MUTED)

    ax.set_ylim(0, 1.04)  # headroom so markers at 100% are not cut off
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
    ax.set_ylabel("Rate", color=INK_MUTED)

    ax.grid(axis="y", color=GRID, linewidth=0.8, linestyle=(0, (4, 3)))
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", length=0, colors=INK_MUTED, labelsize=10)

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=legend_cols,
              frameon=False, fontsize=10, labelcolor=INK, handlelength=3.2,
              columnspacing=2.2)


def _save(fig, out_path: str | Path) -> None:
    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[+] wrote {out_path}")


# --------------------------------------------------------------------------- #
# Plot 1: discovery rate of every honey-asset type
# --------------------------------------------------------------------------- #

def plot_discovery_rates(summaries: dict[int, list[dict]], densities: list[int],
                         out_path: str | Path) -> None:
    series = [rate_series(summaries, densities, asset, "discovery", label)
              for asset, label in ASSET_LABELS.items()]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    _draw_rate_lines(ax, series, show_average=True)
    _style_rate_axes(ax, densities,
                     "Honey asset discovery rates across densities", legend_cols=2)
    _save(fig, out_path)


# --------------------------------------------------------------------------- #
# Plot 2: honeyfile discovery / interaction / engagement + binary execution
# --------------------------------------------------------------------------- #

def plot_honeyfile_rates(summaries: dict[int, list[dict]], densities: list[int],
                         out_path: str | Path) -> None:
    series = [
        rate_series(summaries, densities, "honeyfile", "discovery",
                    "Honeyfile discovery rate"),
        rate_series(summaries, densities, "honeyfile", "interaction",
                    "Honeyfile interaction rate"),
        rate_series(summaries, densities, "honeyfile", "engagement",
                    "Honeyfile engagement rate"),
        # executed honey binaries / deployed honey binaries
        rate_series(summaries, densities, "binary", "execution",
                    "Honey binary execution rate"),
    ]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    _draw_rate_lines(ax, series, show_average=True)
    _style_rate_axes(ax, densities,
                     "Honeyfile discovery, interaction, engagement and "
                     "execution rates", legend_cols=2)
    _save(fig, out_path)


# --------------------------------------------------------------------------- #
# Table output: the plotted numbers
# --------------------------------------------------------------------------- #

def write_rates_csv(summaries: dict[int, list[dict]], densities: list[int],
                    out_path: str | Path) -> None:
    """One row per density / asset type with every rate (blank = not applicable)."""
    def cell(value: float) -> str:
        return "" if math.isnan(value) else f"{value:.4f}"

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["density", "asset_type", "runs", *[f"{m}_rate" for m in RATE_DEFINITIONS]])
        for d in densities:
            for asset in ASSET_LABELS:
                rates = []
                for metric in RATE_DEFINITIONS:
                    # Execution only exists for honey binaries.
                    if metric == "execution" and asset != "binary":
                        rates.append(math.nan)
                    else:
                        rates.append(rate_for_density(summaries[d], asset, metric))
                writer.writerow([d, asset, len(summaries[d]), *[cell(r) for r in rates]])
    print(f"[+] wrote {out_path}")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--campaigns", default=str(DEFAULT_CAMPAIGNS),
                    help="directory holding the density-<N>/run<M>/ results "
                         f"(default: {DEFAULT_CAMPAIGNS})")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"output directory (default: {DEFAULT_OUT})")
    ap.add_argument("--include-baseline", action="store_true",
                    help="also plot density-0 (the baseline without honeyfiles), "
                         "which is left out by default")
    args = ap.parse_args()

    summaries = load_campaign_summaries(Path(args.campaigns).expanduser())
    densities = sorted(d for d in summaries if d > 0 or args.include_baseline)

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    # Plots — each callable on its own with the same `summaries` object.
    plot_discovery_rates(summaries, densities,
                         out / "01_discovery_rates_across_densities.png")
    plot_honeyfile_rates(summaries, densities,
                         out / "02_honeyfile_rates_across_densities.png")
    write_rates_csv(summaries, densities, out / "rates_across_densities.csv")

    print("[✓] done.")


if __name__ == "__main__":
    main()