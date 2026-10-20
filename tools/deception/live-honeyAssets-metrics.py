#!/usr/bin/env python3

import argparse
import csv
import os
import time


# -------------------------------------------------------------------
# Arguments
# -------------------------------------------------------------------

parser = argparse.ArgumentParser()

parser.add_argument("--manifest", required=True, help="Current honeyfile deployment manifest")
parser.add_argument("--asset-manifest", required=True, help="Combined honey ENV/binary/process manifest")
parser.add_argument("--tetragon-log", required=True, help="Current live Tetragon log")
parser.add_argument("--pod", required=True, help="Current target pod")
parser.add_argument("--namespace", default="open5gs")
parser.add_argument("--target-nf", required=True, help="Logical network function name, e.g. udr")
parser.add_argument("--output", required=True, help="Output .prom file for Node Exporter")
parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds")

args = parser.parse_args()


# -------------------------------------------------------------------
# Suspicious binaries
# -------------------------------------------------------------------

SUSPICIOUS_BINARIES = {

    # File/content inspection
    "cat", "grep", "egrep", "fgrep", "head",
    "tail", "less", "more", "strings",  "sed", "awk", "nano", 

    # File manipulation / staging
    "cp", "mv", "mkdir",     "rm",#
    "touch", #
    "chmod", #
    "chown",#
    "chgrp", #


    # Archive / compression
    "tar", "gzip", "gunzip", "zip", "unzip",

    # Network transfer / potential exfiltration
    "curl", "wget", "scp", "sftp", "ping",

}

HONEYFILE_INTERACTION_BINARIES = {
    # Read / inspect
    "cat", "grep", "egrep", "fgrep",
    "head", "tail", "less", "more",
    "strings", "sed", "awk", "nano",

    # Copy / move / modify / remove
    "cp", "mv", "rm", "touch",
    "chmod", "chown", "chgrp",

    # Archive / compress
    "tar", "gzip", "gunzip", "zip", "unzip",

    # Transfer
    "curl", "wget", "scp", "sftp",
}

# -------------------------------------------------------------------
# Read manifests
# -------------------------------------------------------------------

def read_manifest():
    paths = set()

    with open(args.manifest, newline="") as f:
        for row in csv.DictReader(f):
            path = row.get("path", "").strip()
            if path:
                paths.add(path)

    return paths


def read_asset_manifest():
    assets = []

    with open(args.asset_manifest, newline="") as f:
        for row in csv.DictReader(f):
            asset_type = row.get("asset_type", "").strip()

            if asset_type in {"env", "binary", "process"}:
                assets.append(row)

    return assets


# -------------------------------------------------------------------
# Read Tetragon log
# -------------------------------------------------------------------

def read_tetragon_log():
    try:
        with open(args.tetragon_log, "r", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


# -------------------------------------------------------------------
# Permission helper
# -------------------------------------------------------------------

def contains_read(event_type):
    if event_type == "READ":
        return True

    if event_type.startswith("ACCESS(") and event_type.endswith(")"): # e.g "ACCESS(4)"
        try:
            value = int(event_type[len("ACCESS("):-1])
        except ValueError:
            return False

        # Linux permission bit 4 = read
        return bool(value & 4)
        # info
        # ACCESS(4)  → read
        # ACCESS(2)  → write
        # ACCESS(6)  → read + write

    return False


def contains_write(event_type):
    if event_type == "WRITE":
        return True

    if event_type.startswith("ACCESS(") and event_type.endswith(")"):
        try:
            value = int(event_type[len("ACCESS("):-1])
        except ValueError:
            return False

        # Linux permission bit 2 = write
        return bool(value & 2)

    return False


# -------------------------------------------------------------------
# Parse Tetragon log
# -------------------------------------------------------------------

def parse_tetragon(tetragon_text, honeyfiles, assets):

    interacted_honeyfiles = 0
    accessed_paths = 0

    no_suspicious_exec_events = 0
    suspicious_binaries_seen = set()

    binary_exec_counts = {
        binary: 0 for binary in SUSPICIOUS_BINARIES
    }

    # Execution is also counted as interaction.
    interacted_assets = 0
    honeyenvs_interacted = 0
    honeybinaries_interacted = 0
    executed_assets = 0


    for raw_line in tetragon_text.splitlines():

        line = raw_line.strip()
        if not line:
            continue


        # -----------------------------------------------------------
        # EXEC event
        #
        # timestamp | EXEC | PID=x | PPID=x | binary | arguments
        # -----------------------------------------------------------

        if " | EXEC | " in line:

            parts = [part.strip() for part in line.split("|", 5)]

            if len(parts) != 6:
                continue

            timestamp, event_type, pid, ppid, binary, arguments = parts
            binary_name = os.path.basename(binary)


            # -------------------------------------------------------
            # Existing suspicious-command metrics
            # -------------------------------------------------------

            if binary_name in SUSPICIOUS_BINARIES:
                no_suspicious_exec_events += 1
                suspicious_binaries_seen.add(binary_name)
                binary_exec_counts[binary_name] += 1


            # -------------------------------------------------------
            # Honeyfile interaction through command execution
            # -------------------------------------------------------

            if binary_name in HONEYFILE_INTERACTION_BINARIES:

                for honeyfile in honeyfiles:

                    if honeyfile in arguments:
                        interacted_honeyfiles += 1
                        accessed_paths += 1
                        interacted_assets += 1
                        
            # -------------------------------------------------------
            # Honey ENV
            # -------------------------------------------------------

            for asset in assets:

                if asset["asset_type"] != "env":
                    continue

                name = asset.get("name", "").strip()
                value = asset.get("value_or_target", "").strip()

                key = ("env", name)


                # Explicit use of a honey ENV counts as interaction.
                if binary_name not in {"env", "printenv"}:

                    if (
                        f"${name}" in arguments
                        or f"${{{name}}}" in arguments
                        or (value and value in arguments)
                    ):
                        interacted_assets += 1
                        honeyenvs_interacted += 1


            # -------------------------------------------------------
            # Honey binary / process
            # -------------------------------------------------------
            processed_binary_paths = set()
            
            for asset in assets:

                # A process is the running representation of a binary,
                # so both are treated as the same honey asset type.
                if asset["asset_type"] not in {"binary", "process"}:
                    continue

                name = asset.get("name", "").strip()
                path = asset.get("path", "").strip()

                if not path:
                    continue

                # Binary and process with the same path are the same asset. Prevent it doesnt run through 2x
                if path in processed_binary_paths:
                    continue

                processed_binary_paths.add(path)

                # Binary and process use the same canonical identity.
                key = ("binary", path)


                # "ps aux | grep db-check" doesnt count as interaction
                if (
                    (name in arguments or path in arguments)
                    and binary_name not in {
                        "find", "ls", "locate", "which", "whereis",
                        "ps", "pgrep"
                    }
                    and "--worker" not in arguments
                    and binary != path
                ):
                    interacted_assets += 1
                    honeybinaries_interacted += 1

                # Explicit execution of the binary.
                # Execution is also an interaction.
                if binary == path and "--worker" not in arguments:
                    interacted_assets += 1
                    honeybinaries_interacted += 1
                    executed_assets += 1

            continue


        # -----------------------------------------------------------
        # File event
        #
        # timestamp | READ/WRITE | PID=x | binary | path
        # -----------------------------------------------------------

        parts = [part.strip() for part in line.split("|", 4)]

        if len(parts) != 5:
            continue

        timestamp, event_type, pid, binary, path = parts
        binary_name = os.path.basename(binary)


        # -----------------------------------------------------------
        # Honeyfile access
        # -----------------------------------------------------------

        if contains_read(event_type) or contains_write(event_type):

            # find / ls only enumerate.
            if binary_name in {"find", "ls"}:
                continue

            if path in honeyfiles:

                interacted_honeyfiles += 1
                accessed_paths += 1
                interacted_assets += 1


    return (
        interacted_honeyfiles,
        accessed_paths,
        no_suspicious_exec_events,
        suspicious_binaries_seen,
        binary_exec_counts,
        interacted_assets,
        executed_assets,
        honeyenvs_interacted,
        honeybinaries_interacted,
    )


# -------------------------------------------------------------------
# Calculate current state
# -------------------------------------------------------------------

def calculate():

    honeyfiles = read_manifest()
    assets = read_asset_manifest()
    tetragon_text = read_tetragon_log()

    (
        interacted_honeyfiles,
        accessed_paths,
        no_suspicious_exec_events,
        suspicious_binaries_seen,
        binary_exec_counts,
        interacted_assets,
        executed_assets,
        honeyenvs_interacted,
        honeybinaries_interacted,
    ) = parse_tetragon(
        tetragon_text,
        honeyfiles,
        assets
    )


    return (
        len(honeyfiles),
        interacted_honeyfiles,
        no_suspicious_exec_events,
        len(suspicious_binaries_seen),
        binary_exec_counts,
        accessed_paths,
        interacted_assets,
        executed_assets,
        honeyenvs_interacted,
        honeybinaries_interacted,
    )


# -------------------------------------------------------------------
# Write Prometheus metrics
# -------------------------------------------------------------------

def write_metrics(
    total_nr_honeyfiles,
    honeyfiles_interacted,
    suspicious_events,
    suspicious_binary_count,
    binary_exec_counts,
    accessed_paths,
    interacted_assets,
    executed_assets,
    honeyenvs_interacted,
    honeybinaries_interacted,
):

    output_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(output_dir, exist_ok=True)

    temp_path = args.output + ".tmp"

    labels = (
        f'target_namespace="{args.namespace}",'
        f'target_pod="{args.pod}",'
        f'target_nf="{args.target_nf}"'
    )

    lines = [
        # Existing honeyfile metrics
        "# HELP thesis_honeyfiles_total Number of honeyfiles deployed in the current experiment.",
        "# TYPE thesis_honeyfiles_total gauge",
        f"thesis_honeyfiles_total{{{labels}}} {total_nr_honeyfiles}",
        "",

        "# HELP thesis_honeyfiles_interacted Number of deployed honeyfiles interacted with.",
        "# TYPE thesis_honeyfiles_interacted gauge",
        f"thesis_honeyfiles_interacted{{{labels}}} {honeyfiles_interacted}",
        "",

        "# HELP thesis_honeyenvs_interacted Number of honey environment variables interacted with.",
        "# TYPE thesis_honeyenvs_interacted gauge",
        f"thesis_honeyenvs_interacted{{{labels}}} {honeyenvs_interacted}",
        "",

        "# HELP thesis_honeybinaries_interacted Number of honey binaries interacted with.",
        "# TYPE thesis_honeybinaries_interacted gauge",
        f"thesis_honeybinaries_interacted{{{labels}}} {honeybinaries_interacted}",
        "",

        # Existing suspicious-command metrics
        "# HELP thesis_suspicious_exec_events Number of suspicious process executions observed by Tetragon.",
        "# TYPE thesis_suspicious_exec_events gauge",
        f"thesis_suspicious_exec_events{{{labels}}} {suspicious_events}",
        "",

        "# HELP thesis_suspicious_binaries_seen Number of distinct suspicious binaries observed.",
        "# TYPE thesis_suspicious_binaries_seen gauge",
        f"thesis_suspicious_binaries_seen{{{labels}}} {suspicious_binary_count}",
        "",

        "# HELP thesis_suspicious_binary_executions Number of executions per suspicious binary.",
        "# TYPE thesis_suspicious_binary_executions gauge",


    ]


    for binary in sorted(SUSPICIOUS_BINARIES):

        lines.append(
            f'thesis_suspicious_binary_executions'
            f'{{{labels},binary="{binary}"}} '
            f'{binary_exec_counts[binary]}'
        )


    # ---------------------------------------------------------------
    # Aggregate honey-asset metrics
    #
    # These are NOT mutually exclusive.
    # ---------------------------------------------------------------

    lines.extend([
        "",

        "# HELP thesis_honey_assets_interacted Number of honey assets interacted with.",
        "# TYPE thesis_honey_assets_interacted gauge",
        f"thesis_honey_assets_interacted{{{labels}}} {interacted_assets}",
        "",

        "# HELP thesis_honey_assets_executed Number of honey assets explicitly executed.",
        "# TYPE thesis_honey_assets_executed gauge",
        f"thesis_honey_assets_executed{{{labels}}} {executed_assets}",
        "",
    ])


    # Write atomically so Node Exporter never reads a partial file.
    with open(temp_path, "w") as f:
        f.write("\n".join(lines))

    os.replace(temp_path, args.output)


# -------------------------------------------------------------------
# Live loop
# -------------------------------------------------------------------

print(
    "Live Tetragon honey asset monitoring started. "
    f"Refresh interval: {args.interval}s"
)


while True:

    (
        total_nr_honeyfiles,
        accessed,
        suspicious_events,
        suspicious_binary_count,
        binary_counts,
        accessed_paths,
        interacted_assets,
        executed_assets,
        honeyenvs_interacted,
        honeybinaries_interacted,
    ) = calculate()


    write_metrics(
        total_nr_honeyfiles,
        accessed,
        suspicious_events,
        suspicious_binary_count,
        binary_counts,
        accessed_paths,
        interacted_assets,
        executed_assets,
        honeyenvs_interacted,
        honeybinaries_interacted,
    )

    print(
    f"total_honeyfiles={total_nr_honeyfiles} "
    f"interacted_honeyfiles={accessed} "
    f"suspicious_events={suspicious_events} "
    f"suspicious_binaries={suspicious_binary_count} "
    f"honey_interacted={interacted_assets} "
    f"honey_executed={executed_assets} "
    f"honeyenvs_interacted={honeyenvs_interacted} "
    f"honeybinaries_interacted={honeybinaries_interacted}"
)


    time.sleep(args.interval)