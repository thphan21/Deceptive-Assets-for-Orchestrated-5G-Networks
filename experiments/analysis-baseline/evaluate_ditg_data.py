#!/usr/bin/env python3
"""
Dynamically evaluate D-ITG + Prometheus experiment folders and create plots.

Expected layout:
  ROOT/
    density25/
      100MB/
        run1/
          d-itg/raw/*.dat
          prometheus/csv/*.csv

Only canonical workload folders (10MB, 100MB, 1GB, 10GB) and runN folders
are used. Folders such as fail-run1, run1-test, run1-failed, 100MB-fail, etc.
are ignored automatically.

If several valid runs exist for one density/workload, they are aligned to a
common time grid and averaged before plotting.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

WORKLOADS = ["10MB", "100MB", "1GB", "10GB"]
DENSITY_RE = re.compile(r"^density(\d+)$")
RUN_RE = re.compile(r"^run(\d+)$")

# Fixed color mapping requested for the thesis figures.
DENSITY_COLORS = {
    0: "tab:blue",
    25: "tab:green",
    50: "tab:orange",
    75: "tab:purple",
    90: "tab:red",
}

PROM_METRICS = {
    "amf_cpu": ("amf_cpu_cores.csv", "AMF CPU Usage", "CPU [cores]"),
    "amf_memory": ("amf_memory_mib.csv", "AMF Memory Usage", "Memory [MiB]"),
    "smf_cpu": ("smf_cpu_cores.csv", "SMF CPU Usage", "CPU [cores]"),
    "smf_memory": ("smf_memory_mib.csv", "SMF Memory Usage", "Memory [MiB]"),
    "upf_cpu": ("upf_cpu_cores.csv", "UPF CPU Usage", "CPU [cores]"),
    "upf_memory": ("upf_memory_mib.csv", "UPF Memory Usage", "Memory [MiB]"),
    "udr_cpu": ("udr_cpu_cores.csv", "UDR CPU Usage", "CPU [cores]"),
    "udr_memory": ("udr_memory_mib.csv", "UDR Memory Usage", "Memory [MiB]"),
}

# These requested metrics are not present in the supplied sample run.
REQUESTED_BUT_UNAVAILABLE = {
    "AMF requests/s": "No AMF request-counter/rate CSV exists in prometheus/csv.",
    "SMF requests/s": "No SMF request-counter/rate CSV exists in prometheus/csv.",
    "UPF requests/s": "No UPF request-counter/rate CSV exists in prometheus/csv.",
    "AMF throughput": "No AMF network-throughput CSV exists in prometheus/csv.",
    "SMF throughput": "No SMF network-throughput CSV exists in prometheus/csv.",
    "UPF packets": "No UPF packet counter/rate CSV exists in prometheus/csv.",
}


def density_color(density: int):
    """Use requested colors for known densities, otherwise Matplotlib default."""
    return DENSITY_COLORS.get(density, None)


def discover(root: Path) -> Dict[str, Dict[int, List[Path]]]:
    """Return {workload: {density: [run_dirs]}} for valid canonical folders."""
    found: Dict[str, Dict[int, List[Path]]] = {w: {} for w in WORKLOADS}

    if not root.is_dir():
        raise FileNotFoundError(f"Experiment root does not exist: {root}")

    for density_dir in root.iterdir():
        if not density_dir.is_dir():
            continue
        m = DENSITY_RE.fullmatch(density_dir.name)
        if not m:
            continue
        density = int(m.group(1))

        for workload in WORKLOADS:
            workload_dir = density_dir / workload
            if not workload_dir.is_dir():
                continue

            runs = []
            for p in workload_dir.iterdir():
                if p.is_dir() and RUN_RE.fullmatch(p.name):
                    # Require at least one of the normal experiment data roots.
                    if (p / "d-itg" / "raw").is_dir() or (p / "prometheus" / "csv").is_dir():
                        runs.append(p)

            runs.sort(key=lambda p: int(RUN_RE.fullmatch(p.name).group(1)))
            if runs:
                found[workload][density] = runs

    return found


def read_prom_series(run_dir: Path, filename: str, duration: float) -> Optional[pd.DataFrame]:
    path = run_dir / "prometheus" / "csv" / filename
    if not path.is_file():
        return None

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f"WARNING: Could not read {path}: {exc}", file=sys.stderr)
        return None

    if "value" not in df.columns:
        return None

    values = pd.to_numeric(df["value"], errors="coerce")

    if "timestamp_epoch" in df.columns:
        ts = pd.to_numeric(df["timestamp_epoch"], errors="coerce")
        if ts.notna().any():
            t0 = ts.dropna().iloc[0]
            time_s = ts - t0
        else:
            time_s = pd.Series(np.arange(len(df), dtype=float))
    else:
        time_s = pd.Series(np.arange(len(df), dtype=float))

    out = pd.DataFrame({"time": time_s, "value": values}).dropna()
    out = out[(out["time"] >= 0) & (out["time"] <= duration)]
    return out if not out.empty else None


def read_ditg_matrix(run_dir: Path, direction: str, metric: str, duration: float) -> Optional[pd.DataFrame]:
    path = run_dir / "d-itg" / "raw" / f"{direction}-{metric}.dat"
    if not path.is_file():
        return None

    try:
        df = pd.read_csv(path, sep=r"\s+", engine="python")
    except Exception as exc:
        print(f"WARNING: Could not read {path}: {exc}", file=sys.stderr)
        return None

    if df.empty or "Time" not in df.columns:
        return None

    df["Time"] = pd.to_numeric(df["Time"], errors="coerce")
    df = df.dropna(subset=["Time"])
    df = df[(df["Time"] >= 0) & (df["Time"] <= duration)]
    if df.empty:
        return None

    return df


def per_time_flow_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute mean/min/max across individual D-ITG flow columns for every second.

    Aggregate-Flow is deliberately excluded because the sample D-ITG output's
    Aggregate-Flow column is an aggregate across flows, not the per-flow mean.
    Zero-valued flow samples are treated as missing/inactive for delay/jitter.
    """
    flow_cols = [c for c in df.columns if c not in ("Time", "Aggregate-Flow")]
    if not flow_cols:
        return pd.DataFrame(columns=["time", "mean", "min", "max"])

    vals = df[flow_cols].apply(pd.to_numeric, errors="coerce")
    vals = vals.mask(vals <= 0)  # inactive/no-sample values should not become min=0

    return pd.DataFrame({
        "time": df["Time"].astype(float),
        "mean": vals.mean(axis=1, skipna=True),
        "min": vals.min(axis=1, skipna=True),
        "max": vals.max(axis=1, skipna=True),
    }).dropna(how="all", subset=["mean", "min", "max"])


def per_time_flow_mean(df: pd.DataFrame) -> pd.DataFrame:
    flow_cols = [c for c in df.columns if c not in ("Time", "Aggregate-Flow")]
    if not flow_cols:
        return pd.DataFrame(columns=["time", "value"])
    vals = df[flow_cols].apply(pd.to_numeric, errors="coerce")
    vals = vals.mask(vals < 0)
    return pd.DataFrame({
        "time": df["Time"].astype(float),
        "value": vals.mean(axis=1, skipna=True),
    }).dropna()


def aggregate_scalar_series(series_list: List[pd.DataFrame], duration: float, step: float = 1.0) -> Optional[pd.DataFrame]:
    """Interpolate multiple runs to a common grid and average them."""
    series_list = [s for s in series_list if s is not None and not s.empty]
    if not series_list:
        return None

    grid = np.arange(0, duration + 1e-9, step)
    run_values = []

    for df in series_list:
        d = df.sort_values("time").drop_duplicates("time")
        x = d["time"].to_numpy(float)
        y = d["value"].to_numpy(float)
        valid = np.isfinite(x) & np.isfinite(y)
        x, y = x[valid], y[valid]
        if len(x) < 1:
            continue
        interp = np.interp(grid, x, y, left=np.nan, right=np.nan)
        interp[grid < x.min()] = np.nan
        interp[grid > x.max()] = np.nan
        run_values.append(interp)

    if not run_values:
        return None

    arr = np.vstack(run_values)
    return pd.DataFrame({"time": grid, "value": np.nanmean(arr, axis=0)}).dropna()


def aggregate_stats_series(series_list: List[pd.DataFrame], duration: float, step: float = 1.0) -> Optional[pd.DataFrame]:
    """Average per-run mean/min/max curves after alignment."""
    series_list = [s for s in series_list if s is not None and not s.empty]
    if not series_list:
        return None

    grid = np.arange(0, duration + 1e-9, step)
    result = {"time": grid}

    for col in ("mean", "min", "max"):
        runs = []
        for df in series_list:
            d = df.sort_values("time").drop_duplicates("time")
            x = d["time"].to_numpy(float)
            y = d[col].to_numpy(float)
            valid = np.isfinite(x) & np.isfinite(y)
            x, y = x[valid], y[valid]
            if len(x) < 1:
                continue
            interp = np.interp(grid, x, y, left=np.nan, right=np.nan)
            interp[grid < x.min()] = np.nan
            interp[grid > x.max()] = np.nan
            runs.append(interp)
        if runs:
            result[col] = np.nanmean(np.vstack(runs), axis=0)
        else:
            result[col] = np.full_like(grid, np.nan, dtype=float)

    return pd.DataFrame(result).dropna(how="all", subset=["mean", "min", "max"])


def finish_plot(ax, title: str, ylabel: str, duration: float):
    ax.set_title(title)
    ax.set_xlabel("Time [s]")
    ax.set_ylabel(ylabel)
    ax.set_xlim(0, duration)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)


def save_plot(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_prom_metric(workload: str, density_runs: Dict[int, List[Path]], metric_key: str,
                     out_dir: Path, duration: float) -> bool:
    filename, title, ylabel = PROM_METRICS[metric_key]
    fig, ax = plt.subplots(figsize=(10, 6))
    plotted = False

    for density in sorted(density_runs):
        runs = []
        for run_dir in density_runs[density]:
            s = read_prom_series(run_dir, filename, duration)
            if s is not None:
                runs.append(s)
        agg = aggregate_scalar_series(runs, duration)
        if agg is None:
            continue
        ax.plot(agg["time"], agg["value"],
                label=f"{density}% honey density",
                color=density_color(density), linewidth=1.8)
        plotted = True

    if not plotted:
        plt.close(fig)
        return False

    finish_plot(ax, f"{title} — {workload}", ylabel, duration)
    save_plot(fig, out_dir / workload / f"{metric_key}.png")
    return True


def plot_delay(workload: str, density_runs: Dict[int, List[Path]], direction: str,
               out_dir: Path, duration: float) -> bool:
    fig, ax = plt.subplots(figsize=(10, 6))
    plotted = False
    styles = {"mean": "-", "min": "--", "max": ":"}
    labels_once = set()

    for density in sorted(density_runs):
        run_stats = []
        for run_dir in density_runs[density]:
            df = read_ditg_matrix(run_dir, direction, "delay", duration)
            if df is not None:
                run_stats.append(per_time_flow_stats(df))
        agg = aggregate_stats_series(run_stats, duration)
        if agg is None:
            continue

        color = density_color(density)
        for stat in ("mean", "min", "max"):
            # Label each density+stat explicitly; clear and thesis-friendly.
            ax.plot(agg["time"], agg[stat], linestyle=styles[stat], color=color,
                    linewidth=1.7,
                    label=f"{density}% — {stat}")
        plotted = True

    if not plotted:
        plt.close(fig)
        return False

    finish_plot(ax,
                f"{direction.capitalize()} Delay (mean / min / max across flows) — {workload}",
                "Delay [s]", duration)
    save_plot(fig, out_dir / workload / f"{direction}_delay_mean_min_max.png")
    return True


def plot_ditg_mean_metric(workload: str, density_runs: Dict[int, List[Path]], direction: str,
                          metric: str, title: str, ylabel: str,
                          out_dir: Path, duration: float) -> bool:
    fig, ax = plt.subplots(figsize=(10, 6))
    plotted = False

    for density in sorted(density_runs):
        runs = []
        for run_dir in density_runs[density]:
            df = read_ditg_matrix(run_dir, direction, metric, duration)
            if df is not None:
                runs.append(per_time_flow_mean(df))
        agg = aggregate_scalar_series(runs, duration)
        if agg is None:
            continue
        ax.plot(agg["time"], agg["value"],
                label=f"{density}% honey density",
                color=density_color(density), linewidth=1.8)
        plotted = True

    if not plotted:
        plt.close(fig)
        return False

    finish_plot(ax, f"{direction.capitalize()} {title} — {workload}", ylabel, duration)
    save_plot(fig, out_dir / workload / f"{direction}_{metric}.png")
    return True


def plot_upf_throughput(workload: str, density_runs: Dict[int, List[Path]],
                        out_dir: Path, duration: float) -> bool:
    """Plot UPF RX solid and TX dashed, density distinguished by color."""
    fig, ax = plt.subplots(figsize=(10, 6))
    plotted = False

    for density in sorted(density_runs):
        color = density_color(density)
        for filename, direction_name, style in [
            ("upf_network_receive_mbps.csv", "RX", "-"),
            ("upf_network_transmit_mbps.csv", "TX", "--"),
        ]:
            runs = []
            for run_dir in density_runs[density]:
                s = read_prom_series(run_dir, filename, duration)
                if s is not None:
                    runs.append(s)
            agg = aggregate_scalar_series(runs, duration)
            if agg is None:
                continue
            ax.plot(agg["time"], agg["value"], linestyle=style, color=color,
                    linewidth=1.8, label=f"{density}% — {direction_name}")
            plotted = True

    if not plotted:
        plt.close(fig)
        return False

    finish_plot(ax, f"UPF Network Throughput — {workload}", "Throughput [Mbit/s]", duration)
    save_plot(fig, out_dir / workload / "upf_throughput_rx_tx.png")
    return True


def write_inventory(root: Path, discovered: Dict[str, Dict[int, List[Path]]], out_dir: Path):
    rows = []
    for workload in WORKLOADS:
        for density, runs in sorted(discovered[workload].items()):
            for run in runs:
                rows.append({
                    "workload": workload,
                    "density": density,
                    "run": run.name,
                    "path": str(run),
                })
    pd.DataFrame(rows).to_csv(out_dir / "experiment_inventory.csv", index=False)


def main():
    parser = argparse.ArgumentParser(
        description="Plot D-ITG and Prometheus experiment metrics across honey densities."
    )
    parser.add_argument("--root", required=True, type=Path,
                        help="Root, e.g. ~/experiments/baseline-mixed-workloads_10-ues")
    parser.add_argument("--output", required=True, type=Path,
                        help="Directory in which plots are written")
    parser.add_argument("--duration", type=float, default=120.0,
                        help="Plot window in seconds (default: 120)")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    out_dir = args.output.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    discovered = discover(root)
    write_inventory(root, discovered, out_dir)

    print("\nDiscovered experiments")
    print("----------------------")
    for workload in WORKLOADS:
        if not discovered[workload]:
            print(f"{workload}: none")
            continue
        desc = ", ".join(
            f"density{d} ({len(runs)} run{'s' if len(runs) != 1 else ''})"
            for d, runs in sorted(discovered[workload].items())
        )
        print(f"{workload}: {desc}")

    created = []
    skipped = []

    for workload in WORKLOADS:
        density_runs = discovered[workload]
        if not density_runs:
            continue

        # D-ITG delay, jitter, and application bitrate, separately by direction.
        for direction in ("uplink", "downlink"):
            if plot_delay(workload, density_runs, direction, out_dir, args.duration):
                created.append(f"{workload}/{direction}_delay_mean_min_max.png")
            else:
                skipped.append(f"{workload} {direction} delay")

            if plot_ditg_mean_metric(workload, density_runs, direction,
                                     "jitter", "Jitter (mean across flows)", "Jitter [s]",
                                     out_dir, args.duration):
                created.append(f"{workload}/{direction}_jitter.png")
            else:
                skipped.append(f"{workload} {direction} jitter")

            if plot_ditg_mean_metric(workload, density_runs, direction,
                                     "bitrate", "D-ITG Application Throughput", "Bitrate [Kbit/s]",
                                     out_dir, args.duration):
                created.append(f"{workload}/{direction}_bitrate.png")
            else:
                skipped.append(f"{workload} {direction} D-ITG bitrate")

        # NF CPU and memory.
        for metric_key in PROM_METRICS:
            if plot_prom_metric(workload, density_runs, metric_key, out_dir, args.duration):
                created.append(f"{workload}/{metric_key}.png")
            else:
                skipped.append(f"{workload} {metric_key}")

        # UPF throughput available in supplied Prometheus export.
        if plot_upf_throughput(workload, density_runs, out_dir, args.duration):
            created.append(f"{workload}/upf_throughput_rx_tx.png")
        else:
            skipped.append(f"{workload} UPF throughput")

    # Record exactly what could/couldn't be produced.
    report = out_dir / "plot_report.txt"
    with report.open("w", encoding="utf-8") as fh:
        fh.write(f"Experiment root: {root}\n")
        fh.write(f"Plot duration: {args.duration} s\n\n")
        fh.write("CREATED\n=======\n")
        for item in created:
            fh.write(f"{item}\n")
        fh.write("\nSKIPPED / NOT AVAILABLE\n=======================\n")
        for item in skipped:
            fh.write(f"{item}\n")
        fh.write("\nREQUESTED METRICS NOT PRESENT IN SAMPLE\n=======================================\n")
        for metric, reason in REQUESTED_BUT_UNAVAILABLE.items():
            fh.write(f"{metric}: {reason}\n")

    print(f"\nCreated {len(created)} plot(s) in: {out_dir}")
    print(f"Inventory: {out_dir / 'experiment_inventory.csv'}")
    print(f"Report:    {report}")

    if REQUESTED_BUT_UNAVAILABLE:
        print("\nRequested metrics not available in the supplied run:")
        for metric, reason in REQUESTED_BUT_UNAVAILABLE.items():
            print(f"  - {metric}: {reason}")

    # Important comparison warning for current tree.
    if 0 not in discovered.get("10MB", {}) and any(discovered[w] for w in WORKLOADS):
        print("\nNOTE: density0 is not plotted for 10MB/100MB/1GB/10GB unless those")
        print("      workload folders actually exist under density0. density0/0MB is")
        print("      intentionally NOT reused as a baseline for different workloads.")


if __name__ == "__main__":
    main()
