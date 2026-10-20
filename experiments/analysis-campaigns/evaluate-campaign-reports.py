#!/usr/bin/env python3

import argparse
import json
import os
import re
import textwrap

from datetime import datetime
from pathlib import Path
from statistics import median

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator


# ===================================================================
# Configuration
# ===================================================================

DISCOVERY_BINARIES = {
    "find",
    "ls",
    "locate",
    "which",
    "whereis",
    "ps",
    "pgrep",
    "env",
    "printenv",
}


# ===================================================================
# Arguments
# ===================================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description="Visualize Caldera honey-asset campaign results."
    )

    parser.add_argument(
        "--root",
        required=True,
        help="Root directory containing density-* directories",
    )

    parser.add_argument(
        "--output",
        required=True,
        help="Directory for generated graphs",
    )

    return parser.parse_args()


# ===================================================================
# General helpers
# ===================================================================

def safe_int(value):

    if value is None:
        return 0

    try:
        if pd.isna(value):
            return 0
    except TypeError:
        pass

    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def basename(path):

    return os.path.basename(
        str(path).rstrip("/")
    )


def truncate(text, length=100):

    text = str(text)

    return textwrap.shorten(
        text,
        width=length,
        placeholder="...",
    )


# ===================================================================
# Time helpers
# ===================================================================

def parse_timestamp(value):
    """
    Parse:
        2026-09-04T22:22:00Z
        2026-09-04T22:30:53.222949089Z

    Nanoseconds are truncated to microseconds.
    """

    value = str(value).strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    value = re.sub(
        r"(\.\d{6})\d+(?=[+-]\d\d:\d\d$)",
        r"\1",
        value,
    )

    return datetime.fromisoformat(value)


def read_timestamp_file(path):

    return parse_timestamp(
        Path(path)
        .read_text(encoding="utf-8")
        .strip()
    )


def relative_minutes(timestamp, campaign_start):

    return (
        timestamp - campaign_start
    ).total_seconds() / 60.0


def campaign_duration_minutes(
    campaign_start,
    campaign_end,
):

    return (
        campaign_end
        - campaign_start
    ).total_seconds() / 60.0


def configure_time_axis(
    ax,
    duration_minutes,
):
    """
    Major ticks: every 1 minute
    Minor ticks: every 10 seconds = 1/6 minute
    """

    ax.set_xlim(
        0,
        max(duration_minutes, 0.1),
    )

    ax.xaxis.set_major_locator(
        MultipleLocator(1)
    )

    ax.xaxis.set_minor_locator(
        MultipleLocator(1 / 6)
    )

    ax.grid(
        axis="x",
        which="major",
        alpha=0.40,
        linewidth=0.8,
    )

    ax.grid(
        axis="x",
        which="minor",
        alpha=0.15,
        linewidth=0.5,
    )

    ax.set_xlabel(
        "Time since campaign start "
        "(minutes; minor grid = 10 seconds)"
    )


# ===================================================================
# Find campaigns
# ===================================================================

def find_campaigns(root):
    """
    Include only:

        density-N/run1

    Ignore:
        run1-fail
        run1-forDITG*
    """

    campaigns = []

    for density_dir in Path(root).glob(
        "density-*"
    ):

        match = re.fullmatch(
            r"density-(\d+)",
            density_dir.name,
        )

        if not match:
            continue

        density = int(
            match.group(1)
        )

        run_dir = (
            density_dir
            / "run1"
        )

        if not run_dir.is_dir():
            continue

        campaigns.append(
            (
                density,
                run_dir,
            )
        )

    return sorted(
        campaigns,
        key=lambda item: item[0],
    )


# ===================================================================
# Find Caldera event log
# ===================================================================

def find_caldera_event_log(run_dir):

    matches = sorted(
        run_dir.glob(
            "*event-logs.json"
        )
    )

    if not matches:
        return None

    return matches[0]


# ===================================================================
# Evaluated honey assets
# ===================================================================

def read_evaluated_assets(run_dir):

    path = (
        run_dir
        / "results-honeytypes-evaluated.csv"
    )

    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)

    # Avoid accidental double-counting if a manifest contains the
    # same asset more than once.
    required = {
        "asset_type",
        "name",
        "path",
    }

    if required.issubset(df.columns):

        df = df.drop_duplicates(
            subset=[
                "asset_type",
                "name",
                "path",
            ],
            keep="first",
        )

    return df.reset_index(
        drop=True
    )


# ===================================================================
# Infer original normal-file count
# ===================================================================

def infer_normal_file_count(campaigns):
    """
    density = honey / (normal + honey)

    Therefore:

        normal =
            honey * (100 - density) / density

    Estimates the original normal file count for all usable
    non-zero densities and takes the median.
    """

    estimates = []

    for density, run_dir in campaigns:

        if (
            density <= 0
            or density >= 100
        ):
            continue

        path = (
            run_dir
            / "honeyfiles.csv"
        )

        if not path.exists():
            continue

        df = pd.read_csv(path)

        if df.empty:
            continue

        # Only density-generated honeyfiles.
        if "density_requested" in df.columns:

            density_values = pd.to_numeric(
                df["density_requested"],
                errors="coerce",
            )

            regular = df[
                density_values.notna()
            ]

        else:
            regular = df

        honey_count = len(
            regular
        )

        if honey_count == 0:
            continue

        normal_estimate = (
            honey_count
            * (100 - density)
            / density
        )

        estimates.append(
            round(normal_estimate)
        )

    if not estimates:
        return 0

    return int(
        round(
            median(estimates)
        )
    )


# ===================================================================
# Asset-count helpers
# ===================================================================

def count_asset_group(
    df,
    asset_types,
):

    if df.empty:

        return {
            "deployed": 0,
            "discovered": 0,
            "interacted": 0,
            "engaged": 0,
        }

    subset = df[
        df["asset_type"].isin(
            asset_types
        )
    ]

    deployed = len(
        subset
    )

    discovered = sum(
        safe_int(value)
        for value
        in subset["discovered"]
    )

    interacted = sum(
    safe_int(value)
    for value in subset["interacted"]
    )

    engaged = sum(
        safe_int(value)
        for value in subset["engaged"]
    )

    return {
        "deployed": deployed,
        "discovered": discovered,
        "interacted": interacted,
        "engaged": engaged,
    }


def build_asset_summary(df):

    honeyfiles = count_asset_group(
        df,
        ["honeyfile"],
    )

    envs = count_asset_group(
        df,
        ["env"],
    )

    binary_process = count_asset_group(
        df,
        [
            "binary",
            "process",
        ],
    )

    total = {
        "deployed": (
            honeyfiles["deployed"]
            + envs["deployed"]
            + binary_process["deployed"]
        ),

        "discovered": (
            honeyfiles["discovered"]
            + envs["discovered"]
            + binary_process["discovered"]
        ),

        "interacted": (
            honeyfiles["interacted"]
            + envs["interacted"]
            + binary_process["interacted"]
        ),
        "engaged": (
            honeyfiles["engaged"]
            + envs["engaged"]
            + binary_process["engaged"]
        ),
    }

    return {
        "Total honey assets":
            total,

        "Honey files":
            honeyfiles,

        "Honey ENVs":
            envs,

        "Honey binaries/\nprocesses":
            binary_process,
    }


# ===================================================================
# Bar labels
# ===================================================================

def add_segment_numbers(
    ax,
    container,
    values,
):

    for rectangle, value in zip(
        container,
        values,
    ):

        value = int(value)

        if value <= 0:
            continue

        x = (
            rectangle.get_x()
            + rectangle.get_width() / 2
        )

        y = (
            rectangle.get_y()
            + rectangle.get_height() / 2
        )

        ax.text(
            x,
            y,
            str(value),
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
        )


# ===================================================================
# Plot 1 + 2
#
# Stacked honey asset bars
# ===================================================================

def plot_asset_bars(
    summary,
    density,
    output_path,
    normal_files=None,
):

    labels = list(
        summary.keys()
    )

    deployed = np.array([
        summary[label]["deployed"]
        for label in labels
    ])

    discovered = np.array([
        summary[label]["discovered"]
        for label in labels
    ])

    interacted = np.array([
        summary[label]["interacted"]
        for label in labels
    ])

    engaged = np.array([
        summary[label]["engaged"]
        for label in labels
    ])

    # ---------------------------------------------
    # Mutually exclusive graph segments:
    #
    # Engaged
    # Discovered only
    # Interacted only
    # Neither
    # ------------------------
    discovered_only = np.maximum(
        discovered - engaged,
        0,
    )

    interacted_only = np.maximum(
        interacted - engaged,
        0,
    )

    neither = np.maximum(
        deployed
        - engaged
        - discovered_only
        - interacted_only,
        0,
    )

    if normal_files is not None:

        labels = [
            "Normal files",
            *labels,
        ]

        deployed = np.insert(
            deployed,
            0,
            normal_files,
        )

        engaged = np.insert(
            engaged,
            0,
            0,
        )

        discovered_only = np.insert(
            discovered_only,
            0,
            0,
        )

        interacted_only = np.insert(
            interacted_only,
            0,
            0,
        )

        neither = np.insert(
            neither,
            0,
            normal_files,
        )

    x = np.arange(
        len(labels)
    )

    fig, ax = plt.subplots(
        figsize=(12, 7)
    )

    # ---------------------------------------------
    # Stacked bars
    # ---------------------------------------------


    discovered_bars = ax.bar(
        x,
        discovered_only,
        bottom=engaged,
        label="Discovered only",
    )

    interacted_bars = ax.bar(
        x,
        interacted_only,
        bottom=(
            engaged
            + discovered_only
        ),
        label="Interacted only",
    )

    engaged_bars = ax.bar(
        x,
        engaged,
        label="Engaged",
    )

    neither_bars = ax.bar(
        x,
        neither,
        bottom=(
            engaged
            + discovered_only
            + interacted_only
        ),
        label="Neither",
    )

    # ---------------------------------------------
    # Numbers INSIDE every segment
    # ---------------------------------------------

    add_segment_numbers(
        ax,
        engaged_bars,
        engaged,
    )

    add_segment_numbers(
        ax,
        discovered_bars,
        discovered_only,
    )

    add_segment_numbers(
        ax,
        interacted_bars,
        interacted_only,
    )

    add_segment_numbers(
        ax,
        neither_bars,
        neither,
    )
    # ---------------------------------------------
    # Total above each complete bar
    # ---------------------------------------------

    max_value = max(
        deployed
    ) if len(deployed) else 0

    offset = max(
        max_value * 0.02,
        0.3,
    )

    for position, total in zip(
        x,
        deployed,
    ):

        ax.text(
            position,
            total + offset,
            f"Total: {int(total)}",
            ha="center",
            va="bottom",
            fontweight="bold",
        )

    ax.set_xticks(
        x
    )

    ax.set_xticklabels(
        labels
    )

    ax.set_ylabel(
        "Number of entities"
    )

    ax.set_title(
        f"Honey Asset Results — Density {density}%"
    )

    ax.legend()

    ax.grid(
        axis="y",
        alpha=0.25,
    )

    ax.set_ylim(
        0,
        max_value * 1.15 + 1
    )

    fig.tight_layout()

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


# ===================================================================
# Tetragon parsing
# ===================================================================

def parse_tetragon_log(path):

    events = []

    if not path.exists():
        return events

    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:

        for raw_line in handle:

            line = raw_line.strip()

            if not line:
                continue

            parts = [
                part.strip()
                for part
                in line.split("|")
            ]

            if len(parts) < 5:
                continue

            try:

                timestamp = parse_timestamp(
                    parts[0]
                )

            except ValueError:

                continue

            event_type = parts[1]

            if event_type == "EXEC":

                if len(parts) < 6:
                    continue

                events.append({
                    "timestamp":
                        timestamp,

                    "type":
                        "EXEC",

                    "binary":
                        parts[4],

                    "arguments":
                        "|".join(
                            parts[5:]
                        ).strip(),

                    "path":
                        "",
                })

            else:

                events.append({
                    "timestamp":
                        timestamp,

                    "type":
                        event_type,

                    "binary":
                        parts[3],

                    "arguments":
                        "",

                    "path":
                        "|".join(
                            parts[4:]
                        ).strip(),
                })

    return events


# ===================================================================
# Tetragon event helpers
# ===================================================================

def tetragon_command(event):

    if event["type"] == "EXEC":

        return (
            f'{event["binary"]} '
            f'{event["arguments"]}'
        ).strip()

    return (
        f'{event["binary"]} '
        f'{event["path"]}'
    ).strip()


def is_read_event(event_type):

    if event_type == "READ":
        return True

    match = re.fullmatch(
        r"ACCESS\((\d+)\)",
        event_type,
    )

    if match:

        return bool(
            int(
                match.group(1)
            )
            & 4
        )

    return False


# ===================================================================
# Read honey assets
# ===================================================================

def load_assets(run_dir):

    df = read_evaluated_assets(
        run_dir
    )

    assets = []

    for _, row in df.iterrows():

        asset_type = str(
            row.get(
                "asset_type",
                "",
            )
        )


        interacted = safe_int(
            row.get(
                "interacted",
                0,
            )
        )

        assets.append({
            "asset_type":
                asset_type,

            "name":
                str(
                    row.get(
                        "name",
                        "",
                    )
                ),

            "path":
                str(
                    row.get(
                        "path",
                        "",
                    )
                ),

            "discovered":
                bool(
                    safe_int(
                        row.get(
                            "discovered",
                            0,
                        )
                    )
                ),

            "interacted":
                bool(
                    interacted
                ),

            "executed":
                bool(
                    safe_int(
                        row.get(
                            "executed",
                            0,
                        )
                    )
                ),
        })

    return assets


# ===================================================================
# Observation helpers
# ===================================================================

def observation(
    timestamp,
    command,
):

    return {
        "timestamp": timestamp,
        "command": command,
    }


def earlier_observation(
    current,
    candidate,
):

    if candidate is None:
        return current

    if current is None:
        return candidate

    if (
        candidate["timestamp"]
        < current["timestamp"]
    ):
        return candidate

    return current


# ===================================================================
# Asset event reconstruction
# ===================================================================

def find_asset_events(
    assets,
    tetragon_events,
    campaign_start,
    campaign_end,
):

    results = []

    for asset in assets:

        asset_type = asset[
            "asset_type"
        ]

        name = asset[
            "name"
        ]

        path = asset[
            "path"
        ]

        first_discovery = None
        first_interaction = None
        first_execution = None

        for event in tetragon_events:

            timestamp = event[
                "timestamp"
            ]

            if (
                timestamp
                < campaign_start
                or timestamp
                > campaign_end
            ):
                continue

            binary_name = basename(
                event["binary"]
            )

            command = tetragon_command(
                event
            )

            arguments = event.get(
                "arguments",
                "",
            )

            # =======================================================
            # HONEYFILE
            # =======================================================

            if asset_type == "honeyfile":

                # Exact find/list observation.
                if (
                    event["path"] == path
                    and binary_name
                    in {
                        "find",
                        "ls",
                    }
                ):

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_discovery = (
                        earlier_observation(
                            first_discovery,
                            candidate,
                        )
                    )

                # Broad find command under /opt/open5gs.
                if (
                    event["type"] == "EXEC"
                    and binary_name == "find"
                    and "/opt/open5gs"
                    in arguments
                    and path.startswith(
                        "/opt/open5gs/"
                    )
                ):

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_discovery = (
                        earlier_observation(
                            first_discovery,
                            candidate,
                        )
                    )

                # Actual file read.
                if (
                    event["path"] == path
                    and is_read_event(
                        event["type"]
                    )
                    and binary_name
                    not in {
                        "find",
                        "ls",
                    }
                ):

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_interaction = (
                        earlier_observation(
                            first_interaction,
                            candidate,
                        )
                    )

            # =======================================================
            # ENV
            # =======================================================

            elif asset_type == "env":

                # Broad ENV enumeration discovers every ENV.
                if (
                    event["type"] == "EXEC"
                    and binary_name
                    in {
                        "env",
                        "printenv",
                    }
                ):

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_discovery = (
                        earlier_observation(
                            first_discovery,
                            candidate,
                        )
                    )

                if event["type"] == "EXEC":

                    patterns = [
                        f"${name}",
                        f"${{{name}}}",
                        f"printenv {name}",
                    ]

                    if any(
                        pattern in command
                        for pattern
                        in patterns
                    ):

                        candidate = observation(
                            timestamp,
                            command,
                        )

                        first_interaction = (
                            earlier_observation(
                                first_interaction,
                                candidate,
                            )
                        )

                        first_discovery = (
                            earlier_observation(
                                first_discovery,
                                candidate,
                            )
                        )

            # =======================================================
            # BINARY
            # =======================================================

            elif asset_type == "binary":

                if event["type"] == "EXEC":

                    # -----------------------------------------------
                    # Discovery
                    # -----------------------------------------------

                    if (
                        binary_name
                        in {
                            "find",
                            "ls",
                            "which",
                            "whereis",
                            "locate",
                        }
                    ):

                        found = False

                        if (
                            name in arguments
                            or path in arguments
                        ):
                            found = True

                        # Listing the exact directory containing
                        # the honey binary.
                        parent = os.path.dirname(
                            path
                        )

                        if (
                            binary_name == "ls"
                            and parent
                            and parent
                            in arguments
                        ):
                            found = True

                        if found:

                            candidate = observation(
                                timestamp,
                                command,
                            )

                            first_discovery = (
                                earlier_observation(
                                    first_discovery,
                                    candidate,
                                )
                            )

                    # -----------------------------------------------
                    # Execution
                    # -----------------------------------------------

                    direct_exec = (
                        event["binary"]
                        == path
                    )

                    shell_exec = (
                        binary_name
                        in {
                            "sh",
                            "bash",
                        }
                        and (
                            path in arguments
                            or re.search(
                                rf"(^|\s)"
                                rf"{re.escape(name)}"
                                rf"(\s|$)",
                                arguments,
                            )
                        )
                    )

                    if (
                        direct_exec
                        or shell_exec
                    ):

                        # Deployment-created process startup is not
                        # attacker interaction.
                        if "--worker" not in arguments:

                            candidate = observation(
                                timestamp,
                                command,
                            )

                            first_execution = (
                                earlier_observation(
                                    first_execution,
                                    candidate,
                                )
                            )

                            first_interaction = (
                                earlier_observation(
                                    first_interaction,
                                    candidate,
                                )
                            )

                            first_discovery = (
                                earlier_observation(
                                    first_discovery,
                                    candidate,
                                )
                            )

                    # -----------------------------------------------
                    # Access / interaction
                    # -----------------------------------------------

                    elif (
                        path in arguments
                        or re.search(
                            rf"(^|\s)"
                            rf"{re.escape(name)}"
                            rf"(\s|$)",
                            arguments,
                        )
                    ):

                        if (
                            binary_name
                            not in DISCOVERY_BINARIES
                        ):

                            candidate = observation(
                                timestamp,
                                command,
                            )

                            first_interaction = (
                                earlier_observation(
                                    first_interaction,
                                    candidate,
                                )
                            )

                            first_discovery = (
                                earlier_observation(
                                    first_discovery,
                                    candidate,
                                )
                            )

                # File-level access to executable.
                if (
                    event["path"] == path
                    and is_read_event(
                        event["type"]
                    )
                    and binary_name
                    not in {
                        "find",
                        "ls",
                    }
                ):

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_interaction = (
                        earlier_observation(
                            first_interaction,
                            candidate,
                        )
                    )

                    first_discovery = (
                        earlier_observation(
                            first_discovery,
                            candidate,
                        )
                    )

            # =======================================================
            # PROCESS
            # =======================================================

            elif asset_type == "process":

                if event["type"] != "EXEC":
                    continue

                # Broad process discovery.
                if binary_name == "ps":

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_discovery = (
                        earlier_observation(
                            first_discovery,
                            candidate,
                        )
                    )

                # Targeted pgrep.
                if (
                    binary_name == "pgrep"
                    and (
                        name in arguments
                        or path in arguments
                    )
                ):

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_discovery = (
                        earlier_observation(
                            first_discovery,
                            candidate,
                        )
                    )

                # Direct execution of process binary.
                if (
                    event["binary"] == path
                    and "--worker"
                    not in arguments
                ):

                    candidate = observation(
                        timestamp,
                        command,
                    )

                    first_execution = (
                        earlier_observation(
                            first_execution,
                            candidate,
                        )
                    )

                    first_interaction = (
                        earlier_observation(
                            first_interaction,
                            candidate,
                        )
                    )

                    first_discovery = (
                        earlier_observation(
                            first_discovery,
                            candidate,
                        )
                    )

                # Explicit reference to honey process.
                elif (
                    name in command
                    or path in command
                ):

                    if (
                        "--worker"
                        not in command
                    ):

                        if (
                            binary_name
                            != "pgrep"
                        ):

                            candidate = observation(
                                timestamp,
                                command,
                            )

                            first_interaction = (
                                earlier_observation(
                                    first_interaction,
                                    candidate,
                                )
                            )

                            first_discovery = (
                                earlier_observation(
                                    first_discovery,
                                    candidate,
                                )
                            )

        # ===========================================================
        # Respect final evaluator result.
        # ===========================================================

        if not asset["discovered"]:
            first_discovery = None

        if not asset["interacted"]:
            first_interaction = None

        results.append({
            **asset,

            "discovery":
                first_discovery,

            "interacted":
                first_interaction,

            "execution":
                first_execution,
        })

    return results


# ===================================================================
# Plot 3
#
# Campaign duration
# ===================================================================

def plot_campaign_timeline(
    campaign_start,
    campaign_end,
    density,
    output_path,
):

    duration = campaign_duration_minutes(
        campaign_start,
        campaign_end,
    )

    fig, ax = plt.subplots(
        figsize=(13, 3.5)
    )

    ax.barh(
        ["Campaign"],
        [duration],
        left=[0],
        height=0.35,
    )

    ax.axvline(
        0,
        linestyle="--",
        alpha=0.8,
    )

    ax.axvline(
        duration,
        linestyle="--",
        alpha=0.8,
    )

    ax.text(
        0,
        0.25,
        "Start\n0.00 min",
        ha="left",
    )

    ax.text(
        duration,
        0.25,
        (
            f"End\n"
            f"{duration:.2f} min"
        ),
        ha="right",
    )

    configure_time_axis(
        ax,
        duration,
    )

    ax.set_title(
        f"Campaign Timeline — Density {density}%"
    )

    fig.tight_layout()

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


# ===================================================================
# Asset timeline category
# ===================================================================

def asset_timeline_category(
    asset_type,
):

    if asset_type == "honeyfile":
        return "Honey files"

    if asset_type == "env":
        return "Honey ENVs"

    if asset_type in {
        "binary",
        "process",
    }:
        return "Honey binaries/processes"

    return "Other"


# ===================================================================
# Build Plot-4 event list
# ===================================================================

def build_asset_timeline_records(
    asset_events,
    campaign_start,
):

    records = []

    event_number = 1

    for asset in asset_events:

        observations = [
            (
                "DISCOVERED",
                asset["discovery"],
            ),
            (
                "INTERACTED",
                asset["interaction"],
            ),
            (
                "EXECUTED",
                asset["execution"],
            ),
        ]

        for state, event in observations:

            if event is None:
                continue

            records.append({
                "event_id":
                    f"A{event_number:03d}",

                "minutes":
                    relative_minutes(
                        event["timestamp"],
                        campaign_start,
                    ),

                "timestamp":
                    event["timestamp"].isoformat(),

                "state":
                    state,

                "asset_type":
                    asset["asset_type"],

                "asset_name":
                    asset["name"],

                "asset_path":
                    asset["path"],

                "command":
                    event["command"],
            })

            event_number += 1

    return records


# ===================================================================
# Plot 4
#
# Honey asset interaction timeline
# ===================================================================

def plot_asset_timeline(
    asset_events,
    campaign_start,
    campaign_end,
    density,
    output_path,
):

    records = build_asset_timeline_records(
        asset_events,
        campaign_start,
    )

    # Save a complete textual legend/table.
    csv_path = (
        output_path.parent
        / "04_honey_asset_timeline_events.csv"
    )

    pd.DataFrame(
        records
    ).to_csv(
        csv_path,
        index=False,
    )

    categories = [
        "Honey files",
        "Honey ENVs",
        "Honey binaries/processes",
    ]

    y_positions = {
        category: index
        for index, category
        in enumerate(categories)
    }

    state_styles = {
        "DISCOVERED": {
            "linestyle": "-",
            "linewidth": 1.4,
        },

        "INTERACTED": {
            "linestyle": "--",
            "linewidth": 1.7,
        },

        "EXECUTED": {
            "linestyle": ":",
            "linewidth": 2.2,
        },
    }

    fig, ax = plt.subplots(
        figsize=(16, 7)
    )

    for record in records:

        category = asset_timeline_category(
            record["asset_type"]
        )

        y = y_positions[
            category
        ]

        style = state_styles[
            record["state"]
        ]

        x = record[
            "minutes"
        ]

        ax.vlines(
            x,
            y - 0.30,
            y + 0.30,
            **style,
        )

        # Each line gets an ID.
        ax.text(
            x,
            y + 0.34,
            record["event_id"],
            rotation=90,
            ha="center",
            va="bottom",
            fontsize=6,
        )

    duration = campaign_duration_minutes(
        campaign_start,
        campaign_end,
    )

    ax.set_yticks(
        list(
            y_positions.values()
        )
    )

    ax.set_yticklabels(
        list(
            y_positions.keys()
        )
    )

    configure_time_axis(
        ax,
        duration,
    )

    ax.set_title(
        (
            f"Honey Asset Events — Density {density}%\n"
            "Event IDs map to "
            "04_honey_asset_timeline_events.csv"
        )
    )

    # Semantic legend.
    legend_handles = [
        Line2D(
            [0],
            [0],
            linestyle="-",
            label="Discovered",
        ),

        Line2D(
            [0],
            [0],
            linestyle="--",
            label="Interacted",
        ),

        Line2D(
            [0],
            [0],
            linestyle=":",
            label="Executed",
        ),
    ]

    ax.legend(
        handles=legend_handles,
        loc="upper right",
    )

    fig.tight_layout()

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


# ===================================================================
# Read Caldera events
# ===================================================================

def read_caldera_events(path):

    if path is None:
        return []

    with open(
        path,
        encoding="utf-8",
    ) as handle:

        data = json.load(
            handle
        )

    if not isinstance(
        data,
        list,
    ):
        return []

    events = []

    for row in data:

        timestamp_text = (
            row.get(
                "delegated_timestamp"
            )
            or row.get(
                "agent_reported_time"
            )
            or row.get(
                "collected_timestamp"
            )
        )

        if not timestamp_text:
            continue

        try:

            timestamp = parse_timestamp(
                timestamp_text
            )

        except ValueError:

            continue

        ability = row.get(
            "ability_metadata",
            {},
        )

        attack = row.get(
            "attack_metadata",
            {},
        )

        events.append({
            "timestamp":
                timestamp,

            "command":
                (
                    row.get(
                        "plaintext_command"
                    )
                    or row.get(
                        "command",
                        "",
                    )
                ),

            "ability_name":
                ability.get(
                    "ability_name",
                    "",
                ),

            "ability_id":
                ability.get(
                    "ability_id",
                    "",
                ),

            "technique_id":
                attack.get(
                    "technique_id",
                    "",
                ),

            "technique_name":
                attack.get(
                    "technique_name",
                    "",
                ),
        })

    return events


# ===================================================================
# Normalize commands
# ===================================================================

def normalize_command(command):

    command = str(
        command
    ).strip()

    command = command.replace(
        "\\",
        "",
    )

    command = command.replace(
        '"',
        "",
    )

    command = command.replace(
        "'",
        "",
    )

    command = re.sub(
        r"\s+",
        " ",
        command,
    )

    return command.strip()


# ===================================================================
# Caldera -> Tetragon matching
# ===================================================================

def command_seen_in_tetragon(
    caldera_command,
    tetragon_events,
    issued_timestamp,
):

    target = normalize_command(
        caldera_command
    )

    if not target:
        return None

    target_tokens = set(
        target.split()
    )

    best_event = None
    best_score = 0

    for event in tetragon_events:

        if event["type"] != "EXEC":
            continue

        delta = (
            event["timestamp"]
            - issued_timestamp
        ).total_seconds()

        # Small clock/reporting tolerance.
        if delta < -2:
            continue

        # Prevent matching a much later unrelated command.
        if delta > 180:
            continue

        observed = normalize_command(
            tetragon_command(
                event
            )
        )

        if not observed:
            continue

        # Direct string containment.
        if (
            target in observed
            or observed in target
        ):

            return event

        # Token-based fallback.
        observed_tokens = set(
            observed.split()
        )

        union = (
            target_tokens
            | observed_tokens
        )

        if not union:
            continue

        score = (
            len(
                target_tokens
                & observed_tokens
            )
            / len(union)
        )

        if score > best_score:

            best_score = score
            best_event = event

    if best_score >= 0.55:
        return best_event

    return None


# ===================================================================
# Build Caldera/Tetragon matches
# ===================================================================

def build_command_matches(
    caldera_events,
    tetragon_events,
    campaign_start,
    campaign_end,
):

    records = []

    for index, event in enumerate(
        caldera_events,
        start=1,
    ):

        issued = event[
            "timestamp"
        ]

        if (
            issued < campaign_start
            or issued > campaign_end
        ):
            continue

        match = command_seen_in_tetragon(
            event["command"],
            tetragon_events,
            issued,
        )

        record = {
            "event_id":
                f"C{index:03d}",

            "ability_name":
                event["ability_name"],

            "ability_id":
                event["ability_id"],

            "technique_id":
                event["technique_id"],

            "technique_name":
                event["technique_name"],

            "caldera_command":
                event["command"],

            "caldera_time":
                issued.isoformat(),

            "caldera_minutes":
                relative_minutes(
                    issued,
                    campaign_start,
                ),

            "seen_in_tetragon":
                bool(match),

            "tetragon_time":
                "",

            "tetragon_minutes":
                np.nan,

            "tetragon_command":
                "",
        }

        if match is not None:

            record[
                "tetragon_time"
            ] = (
                match["timestamp"]
                .isoformat()
            )

            record[
                "tetragon_minutes"
            ] = relative_minutes(
                match["timestamp"],
                campaign_start,
            )

            record[
                "tetragon_command"
            ] = tetragon_command(
                match
            )

        records.append(
            record
        )

    return records


# ===================================================================
# Plot 5
#
# Caldera commands vs Tetragon
# ===================================================================

def plot_caldera_timeline(
    caldera_events,
    tetragon_events,
    campaign_start,
    campaign_end,
    density,
    output_path,
):

    records = build_command_matches(
        caldera_events,
        tetragon_events,
        campaign_start,
        campaign_end,
    )

    csv_path = (
        output_path.parent
        / "05_caldera_tetragon_matches.csv"
    )

    pd.DataFrame(
        records
    ).to_csv(
        csv_path,
        index=False,
    )

    fig, ax = plt.subplots(
        figsize=(16, 6)
    )

    number_of_events = max(
        len(records),
        1,
    )

    # Unique colors for actions.
    cmap = plt.get_cmap(
        "hsv"
    )

    colors = [
        cmap(i / number_of_events)
        for i
        in range(number_of_events)
    ]

    for index, record in enumerate(
        records
    ):

        color = colors[
            index
        ]

        event_id = record[
            "event_id"
        ]

        # ---------------------------------------------
        # Caldera issued event
        # ---------------------------------------------

        x_caldera = record[
            "caldera_minutes"
        ]

        ax.vlines(
            x_caldera,
            -0.25,
            0.25,
            color=color,
            linewidth=2,
            linestyle="-",
        )

        ax.text(
            x_caldera,
            0.30,
            event_id,
            rotation=90,
            fontsize=6,
            ha="center",
            va="bottom",
            color=color,
        )

        # ---------------------------------------------
        # Matching Tetragon event
        # SAME COLOR
        # ---------------------------------------------

        if record[
            "seen_in_tetragon"
        ]:

            x_tetragon = record[
                "tetragon_minutes"
            ]

            ax.vlines(
                x_tetragon,
                0.75,
                1.25,
                color=color,
                linewidth=2,
                linestyle="--",
            )

            ax.text(
                x_tetragon,
                1.30,
                event_id,
                rotation=90,
                fontsize=6,
                ha="center",
                va="bottom",
                color=color,
            )

            # Optional faint connector.
            ax.plot(
                [
                    x_caldera,
                    x_tetragon,
                ],
                [
                    0,
                    1,
                ],
                color=color,
                alpha=0.20,
                linewidth=0.8,
            )

    duration = campaign_duration_minutes(
        campaign_start,
        campaign_end,
    )

    ax.set_ylim(
        -0.5,
        1.6,
    )

    ax.set_yticks(
        [0, 1]
    )

    ax.set_yticklabels([
        "Caldera command",
        "Seen in Tetragon",
    ])

    configure_time_axis(
        ax,
        duration,
    )

    ax.set_title(
        (
            f"Caldera Commands vs Tetragon — Density {density}%\n"
            "Same color + same event ID = corresponding action; "
            "details in 05_caldera_tetragon_matches.csv"
        )
    )

    legend_handles = [
        Line2D(
            [0],
            [0],
            linestyle="-",
            label="Caldera command issued",
        ),

        Line2D(
            [0],
            [0],
            linestyle="--",
            label="Matching Tetragon EXEC",
        ),
    ]

    ax.legend(
        handles=legend_handles,
        loc="upper right",
    )

    fig.tight_layout()

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


# ===================================================================
# Plot 6
#
# Exact honey asset status by name
# ===================================================================

def plot_exact_asset_status(
    asset_events,
    density,
    output_path,
):

    rows = []

    for asset in asset_events:

        rows.append({
            "label":
                (
                    f"{asset['asset_type']} | "
                    f"{asset['name']}"
                ),

            "asset_type":
                asset["asset_type"],

            "asset_name":
                asset["name"],

            "asset_path":
                asset["path"],

            "discovered":
                int(asset["discovered"]),

            "interacted":
                int(asset["interacted"]),

            "executed":
                int(asset["executed"]),
                    })

    df = pd.DataFrame(
        rows
    )

    if df.empty:
        return

    # Save exact values as CSV as well.
    csv_path = (
        output_path.parent
        / "06_exact_honey_asset_status.csv"
    )

    df.to_csv(
        csv_path,
        index=False,
    )

    # Sort to make interacted assets easier to inspect.
    df["status_total"] = (
        df["discovered"]
        + df["interacted"]
        + df["executed"]
    )

    df = df.sort_values(
        by=[
            "status_total",
            "asset_type",
            "asset_name",
        ],
        ascending=[
            False,
            True,
            True,
        ],
    )

    # Dynamic figure height.
    height = max(
        7,
        min(
            60,
            len(df) * 0.28,
        ),
    )

    fig, ax = plt.subplots(
        figsize=(
            15,
            height,
        )
    )

    y = np.arange(
        len(df)
    )

    discovered = df[
        "discovered"
    ].to_numpy()

    interacted = df[
        "interacted"
    ].to_numpy()

    executed = df[
        "executed"
    ].to_numpy()

    # These are intentionally stacked status indicators:
    # a fully executed binary may therefore have D + I + E.    
    bars_discovered = ax.barh(
        y,
        discovered,
        label="Discovered",
    )

    bars_accessed = ax.barh(
        y,
        interacted,
        left=discovered,
        label="Interacted",
    )

    bars_executed = ax.barh(
        y,
        executed,
        left=(
            discovered
            + interacted
        ),
        label="Executed",
    )

    add_segment_numbers(
        ax,
        bars_discovered,
        discovered,
    )

    add_segment_numbers(
        ax,
        bars_accessed,
        interacted,
    )

    add_segment_numbers(
        ax,
        bars_executed,
        executed,
    )

    ax.set_yticks(
        y
    )

    ax.set_yticklabels(
        df["label"],
        fontsize=7,
    )

    ax.invert_yaxis()

    ax.set_xlabel(
        "Observed status indicators"
    )

    ax.set_title(
        (
            f"Exact Honey Asset Status — Density {density}%\n"
            "Each row represents one deployed honey asset"
        )
    )

    ax.set_xticks(
        [0, 1, 2, 3]
    )

    ax.legend(
        loc="upper right"
    )

    ax.grid(
        axis="x",
        alpha=0.25,
    )

    fig.tight_layout()

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


# ===================================================================
# Plot 7
#
# Caldera command distribution
# ===================================================================

def plot_caldera_command_distribution(
    caldera_events,
    density,
    output_path,
):

    if not caldera_events:
        return

    commands = [
        event["command"]
        for event
        in caldera_events
        if event["command"]
    ]

    if not commands:
        return

    df = pd.DataFrame({
        "command": commands
    })

    counts = (
        df.groupby(
            "command"
        )
        .size()
        .reset_index(
            name="count"
        )
        .sort_values(
            "count",
            ascending=True,
        )
    )

    csv_path = (
        output_path.parent
        / "07_caldera_command_distribution.csv"
    )

    counts.to_csv(
        csv_path,
        index=False,
    )

    # Shortened labels in plot.
    labels = [
        truncate(
            command,
            110,
        )
        for command
        in counts["command"]
    ]

    height = max(
        6,
        len(counts) * 0.55,
    )

    fig, ax = plt.subplots(
        figsize=(
            15,
            height,
        )
    )

    y = np.arange(
        len(counts)
    )

    bars = ax.barh(
        y,
        counts["count"],
    )

    ax.set_yticks(
        y
    )

    ax.set_yticklabels(
        labels,
        fontsize=8,
    )

    ax.set_xlabel(
        "Number of times command was used"
    )

    ax.set_title(
        (
            f"Caldera Command Distribution — Density {density}%"
        )
    )

    ax.grid(
        axis="x",
        alpha=0.25,
    )

    # Numbers on every bar.
    max_count = max(
        counts["count"]
    )

    for rectangle, count in zip(
        bars,
        counts["count"],
    ):

        ax.text(
            rectangle.get_width()
            + max_count * 0.015,
            (
                rectangle.get_y()
                + rectangle.get_height() / 2
            ),
            str(int(count)),
            va="center",
            ha="left",
            fontweight="bold",
        )

    ax.set_xlim(
        0,
        max_count * 1.15 + 0.5,
    )

    fig.tight_layout()

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


# ===================================================================
# Process one campaign
# ===================================================================

def process_campaign(
    density,
    run_dir,
    output_root,
    normal_file_count,
):

    print()
    print(
        f"Processing density {density}%"
    )

    print(
        f"  Run: {run_dir}"
    )

    output_dir = (
        output_root
        / f"density-{density}"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ===============================================================
    # Campaign time
    # ===============================================================

    start_path = (
        run_dir
        / "run-time-start.txt"
    )

    end_path = (
        run_dir
        / "run-time-end.txt"
    )

    campaign_start = read_timestamp_file(
        start_path
    )

    campaign_end = read_timestamp_file(
        end_path
    )

    # ===============================================================
    # Evaluated assets
    # ===============================================================

    evaluated = read_evaluated_assets(
        run_dir
    )

    summary = build_asset_summary(
        evaluated
    )

    # ===============================================================
    # Plot 1
    # ===============================================================

    plot_asset_bars(
        summary,
        density,
        (
            output_dir
            / "01_honey_assets.png"
        ),
    )

    # ===============================================================
    # Plot 2
    # ===============================================================

    plot_asset_bars(
        summary,
        density,
        (
            output_dir
            / "02_honey_assets_vs_normal_files.png"
        ),
        normal_files=normal_file_count,
    )

    # ===============================================================
    # Plot 3
    # ===============================================================

    plot_campaign_timeline(
        campaign_start,
        campaign_end,
        density,
        (
            output_dir
            / "03_campaign_timeline.png"
        ),
    )

    # ===============================================================
    # Tetragon
    # ===============================================================

    tetragon_path = (
        run_dir
        / "tetragon-udr.log"
    )

    tetragon_events = parse_tetragon_log(
        tetragon_path
    )

    # ===============================================================
    # Asset-event reconstruction
    # ===============================================================

    assets = load_assets(
        run_dir
    )

    asset_events = find_asset_events(
        assets,
        tetragon_events,
        campaign_start,
        campaign_end,
    )

    # ===============================================================
    # Plot 4
    # ===============================================================

    plot_asset_timeline(
        asset_events,
        campaign_start,
        campaign_end,
        density,
        (
            output_dir
            / "04_honey_asset_timeline.png"
        ),
    )

    # ===============================================================
    # Caldera events
    # ===============================================================

    caldera_event_log = (
        find_caldera_event_log(
            run_dir
        )
    )

    caldera_events = read_caldera_events(
        caldera_event_log
    )

    # ===============================================================
    # Plot 5
    # ===============================================================

    plot_caldera_timeline(
        caldera_events,
        tetragon_events,
        campaign_start,
        campaign_end,
        density,
        (
            output_dir
            / "05_caldera_tetragon_timeline.png"
        ),
    )

    # ===============================================================
    # Plot 6
    # ===============================================================

    plot_exact_asset_status(
        asset_events,
        density,
        (
            output_dir
            / "06_exact_honey_asset_status.png"
        ),
    )

    # ===============================================================
    # Plot 7
    # ===============================================================

    plot_caldera_command_distribution(
        caldera_events,
        density,
        (
            output_dir
            / "07_caldera_command_distribution.png"
        ),
    )

    print(
        f"  Output: {output_dir}"
    )


# ===================================================================
# Main
# ===================================================================

def main():

    args = parse_args()

    root = Path(
        args.root
    ).expanduser().resolve()

    output_root = Path(
        args.output
    ).expanduser().resolve()

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    campaigns = find_campaigns(
        root
    )

    if not campaigns:

        raise SystemExit(
            (
                "No density-*/run1 "
                f"campaigns found under {root}"
            )
        )

    print(
        f"Found {len(campaigns)} campaigns:"
    )

    for density, run_dir in campaigns:

        print(
            f"  density-{density}: "
            f"{run_dir}"
        )

    # ===============================================================
    # Original file baseline
    # ===============================================================

    normal_file_count = (
        infer_normal_file_count(
            campaigns
        )
    )

    print()

    print(
        (
            "Inferred original normal-file count: "
            f"{normal_file_count}"
        )
    )

    # ===============================================================
    # Process every density
    # ===============================================================

    for density, run_dir in campaigns:

        process_campaign(
            density,
            run_dir,
            output_root,
            normal_file_count,
        )

    print()

    print(
        (
            "Finished. Graphs written to: "
            f"{output_root}"
        )
    )


# ===================================================================
# Entry point
# ===================================================================

if __name__ == "__main__":
    main()