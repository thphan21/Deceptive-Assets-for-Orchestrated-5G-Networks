#!/usr/bin/env python3

import argparse
import csv
import json
import os


# -------------------------------------------------------------------
# Arguments
# -------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
    "--honeyfile-manifest",
    required=True,
    help="Original honeyfile deployment manifest"
)

    parser.add_argument(
        "--env-manifest",
        required=True,
        help="Honey ENV manifest",
    )

    parser.add_argument(
        "--binary-manifest",
        required=True,
        help="Honey binary/process manifest",
    )

    parser.add_argument(
        "--discovery-log",
        required=True,
        help="Attacker-visible discovery output",
    )

    parser.add_argument(
        "--tetragon-log",
        required=True,
        help="Filtered Tetragon execution log",
    )

    parser.add_argument(
        "--output-manifest",
        required=True,
        help="Evaluated honey asset CSV",
    )

    parser.add_argument(
        "--summary",
        required=True,
        help="Evaluation summary JSON",
    )

    return parser.parse_args()


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
# Validate input files
# -------------------------------------------------------------------

def validate_input_files(input_file_list):
    for path in input_file_list:
        if not os.path.exists(path):
            raise SystemExit(f"Required input file does not exist: {path}")



# -------------------------------------------------------------------
# Read files
# -------------------------------------------------------------------

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_text(path):
    with open(path, "r", errors="replace") as f:
        return f.read()


# -------------------------------------------------------------------
# Parse Tetragon EXEC events
#
# Expected format:
#
# timestamp | EXEC | PID=x | PPID=x | binary | arguments
# -------------------------------------------------------------------

def parse_exec_events(text):
    events = []

    for raw_line in text.splitlines():

        if " | EXEC | " not in raw_line:
            continue

        parts = [
            part.strip()
            for part in raw_line.split("|", 5)
        ]

        if len(parts) != 6:
            continue

        timestamp, event_type, pid, ppid, binary, arguments = parts

        events.append({
            "timestamp": timestamp,
            "binary": binary,
            "arguments": arguments,
            "command": f"{binary} {arguments}".strip(),
        })

    return events

# -------------------------------------------------------------------
# Honeyfile evaluation
# -------------------------------------------------------------------
# Determine whether a Tetragon file-access event represents a READ.
#
# Supported examples:
#
# READ
# ACCESS(4)
# ACCESS(5)
# -------------------------------------------------------------------
def contains_read(event_type):
    """
    Return True when a Tetragon file-access event includes READ access.
    """

    if event_type == "READ":
        return True

    if (
        event_type.startswith("ACCESS(")
        and event_type.endswith(")")
    ):

        try:

            value = int(
                event_type[len("ACCESS("):-1]
            )

        except ValueError:
            return False

        # Linux permission bit 4 represents READ.
        return bool(value & 4)

    return False

def contains_write(event_type):
    if event_type == "WRITE":
        return True

    if event_type.startswith("ACCESS(") and event_type.endswith(")"):
        try:
            value = int(event_type[len("ACCESS("):-1])
        except ValueError:
            return False
        
        # Linux permission bit 2 represents WRITE.
        return bool(value & 2)

    return False

# ===================================================================
# Parse all actual honeyfile READ accesses from the Tetragon log.
# ===================================================================

def read_interacted_paths(text, honeyfile_rows):
    """
    Extract paths that were actually read from the Tetragon log.

    Discovery binaries such as find and ls are excluded because simply
    discovering/listing a file should not count as accessing it.
    """

    interacted = set()

    excluded_binaries = {
        "find",
        "ls",
    }

    honeyfiles = {
        row.get("path", "").strip()
        for row in honeyfile_rows
        if row.get("path", "").strip()
    }

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        # EXEC events belong to process execution parsing,
        # not file-access parsing.
        # Process execution:
        # interaction commands explicitly referencing a honeyfile
        if " | EXEC | " in line:
            parts = [part.strip() for part in line.split("|", 5)]

            if len(parts) != 6:
                continue

            timestamp, event_type, pid, ppid, binary, arguments = parts
            binary_name = os.path.basename(binary)

            if binary_name in HONEYFILE_INTERACTION_BINARIES:
                for honeyfile in honeyfiles:
                    if honeyfile in arguments:
                        interacted.add(honeyfile)

            continue


        if " | EXEC | " in line:
            continue

        parts = [
            part.strip()
            for part in line.split("|", 4)
        ]

        if len(parts) != 5:
            continue

        timestamp, event_type, pid, binary, path = parts

        if not (contains_read(event_type) or contains_write(event_type)):
            continue

        binary_name = os.path.basename(binary)
        

        # find and ls may cause kernel-level reads while merely
        # discovering/listing files. Do not count these as attacker
        # access.
        if binary_name in excluded_binaries:
            continue

        if path in honeyfiles:
            interacted.add(path)

    return interacted

# ===================================================================
# HONEYFILE: Discovery and evaluation
# ===================================================================

def honeyfile_was_discovered(
    row,
    discovery_text,
):

    path = row.get(
        "path",
        "",
    ).strip()

    filename = row.get(
        "filename",
        "",
    ).strip()

    # Full path appeared in discovery output.
    if path and path in discovery_text:
        return True

    # Filename appeared as an individual output line.
    if filename:

        for line in discovery_text.splitlines():

            if line.strip() == filename:
                return True

    return False



# -------------------------------------------------------------------
# Honeyfile evaluation
# -------------------------------------------------------------------
def evaluate_honeyfile(
    row,
    discovery_text,
    accessed_paths,
):

    path = row.get(
        "path",
        "",
    ).strip()

    discovered = honeyfile_was_discovered(
        row,
        discovery_text,
    )

    accessed = (
        path in accessed_paths
        if path
        else False
    )

    return discovered, accessed

# -------------------------------------------------------------------
# ENV evaluation
# -------------------------------------------------------------------

def evaluate_env(row, discovery_text, exec_events):

    name = row["name"].strip()
    value = row.get("value_or_target", "").strip()

    # Broad discovery:
    # e.g. env output contains DATABASE_URI=...
    discovered = name in discovery_text

    interacted = False

    for event in exec_events:
        binary_name = os.path.basename(event["binary"])
        arguments = event["arguments"]

        if binary_name in {"env", "printenv"}:
            continue

        if (
            f"${name}" in arguments
            or f"${{{name}}}" in arguments
            or (value and value in arguments)
        ):
            interacted = True
            break

    return discovered, interacted


# -------------------------------------------------------------------
# Binary evaluation
# -------------------------------------------------------------------

def binary_was_interacted_with(row, exec_events):

    name = row["name"].strip() # "db-subscriber-migration"
    path = row["path"].strip() # "/opt/open5gs/bin/db-subscriber-migration"

    interacted = False
    executed = False

    # Example event:
    # {
    #   "binary": "/bin/sh",
    #   "arguments": "/opt/open5gs/bin/db-subscriber-migration --worker"
    # }
    for event in exec_events:

        binary = event["binary"]
        arguments = event["arguments"]
        binary_name = os.path.basename(binary)

        # Explicit inspection / interaction.
        if (
            path
            and path in arguments
            and binary_name not in {
                "find", "ls", "locate", "which", "whereis"
            }
            and "--worker" not in arguments
        ):
            interacted = True

        # Direct execution.
        if binary == path and "--worker" not in arguments:
            interacted = True
            executed = True

        
        # Execution through sh/bash.
        # Shell-script case:
        # binary    = /bin/sh
        # arguments = /opt/open5gs/bin/db-subscriber-migration --worker
        # Explicit non-discovery reference.
        argument_parts = arguments.split()

        if (
            binary_name in {"sh", "bash"}
            and argument_parts
            and argument_parts[0] == path
            and "--worker" not in arguments
        ):
            interacted = True
            executed = True  

    return interacted, executed


def evaluate_binary(row, discovery_text, exec_events):

    name = row["name"].strip() # "db-subscriber-migration"
    path = row["path"].strip() # "/opt/open5gs/bin/db-subscriber-migration"

    discovered = (
        name in discovery_text
        or path in discovery_text
    )

    interacted, executed = binary_was_interacted_with(row, exec_events)

    return discovered, interacted, executed


# -------------------------------------------------------------------
# Process evaluation
# -------------------------------------------------------------------

def evaluate_process(row, discovery_text, exec_events):

    # Example process manifest row:
    #
    # {
    #     "asset_type": "process",
    #     "name": "db-subscriber-migration",
    #     "path": "/opt/open5gs/bin/db-subscriber-migration",
    #     ...
    # }

    name = row["name"].strip()
    path = row["path"].strip()

    discovered = (
        name in discovery_text
        or path in discovery_text
    )

    interacted = False

    # Event: 
    # {
    #     "binary": "/usr/bin/cat",
    #     "arguments": "/opt/open5gs/bin/db-subscriber-migration",
    #     "command":
    #         "/usr/bin/cat /opt/open5gs/bin/db-subscriber-migration"
    # }
    for event in exec_events:

        binary = event["binary"]
        binary_name = os.path.basename(binary) # e.g. cat
        arguments = event["arguments"]

        if (
            name in arguments
            or path in arguments
        ) and binary_name not in {"ps", "pgrep"}:

            # Ignore deployment-created migration worker.
            if not (
                "--worker" in arguments
                and binary_name in {"sh", "bash"}
            ):
                interacted = True


        # Explicit process binary execution.
        if binary == path and "--worker" not in arguments:
            interacted = True

        argument_parts = arguments.split()

        if (
            binary_name in {"sh", "bash"}
            and argument_parts
            and argument_parts[0] == path
            and "--worker" not in arguments
        ):
            interacted = True

    return discovered, interacted


# -------------------------------------------------------------------
# Evaluate all assets
# -------------------------------------------------------------------

def evaluate_assets(
    honeyfile_rows,
    accessed_paths,
    env_rows,
    binary_rows,
    discovery_text,
    exec_events
):
    evaluated = []

    # Honeyfile assets
    for row in honeyfile_rows:
        path = row.get(
            "path",
            ""
        ).strip()

        if not path:
            continue

        discovered, interacted = evaluate_honeyfile(
            row,
            discovery_text,
            accessed_paths
        )

        filename = row.get(
            "filename",
            ""
        ).strip()

        if filename:
            name = filename
        else:
            name = os.path.basename(path)

        evaluated.append({
            "asset_type": "honeyfile",
            "name": name,
            "path": path,
            "role": row.get("role", ""),
            "discovered": int(discovered),
            "interacted": int(interacted),
            "engaged": int(discovered and interacted),
        })


    # ENV assets
    for row in env_rows:

        if row.get("asset_type") != "env":
            continue

        discovered, interacted = evaluate_env(
            row,
            discovery_text, exec_events,
        )

        evaluated.append({
            "asset_type": "env",
            "name": row["name"],
            "path": row["path"],
            "role": row.get("role", ""),
            "discovered": int(discovered),
            "interacted": int(interacted),
            "engaged": int(discovered and interacted),
        })

    # Binary and process assets
    for row in binary_rows:

        asset_type = row.get("asset_type", "")

        if asset_type == "binary":
            discovered, interacted, executed = evaluate_binary(
                row,
                discovery_text, exec_events,
            )

        elif asset_type == "process":
            discovered, interacted = evaluate_process(
                row,
                discovery_text, exec_events,
            )
            executed = False

        else:
            continue

        evaluated.append({
            "asset_type": asset_type,
            "name": row["name"],
            "path": row["path"],
            "role": row.get("role", ""),
            "discovered": int(discovered),
            "interacted": int(interacted),
            "engaged": int(discovered and interacted),
            "executed": int(executed),
        })

    return evaluated


# -------------------------------------------------------------------
# Metrics
# -------------------------------------------------------------------

def metrics_for(evaluated, asset_type):

    assets = [
        row
        for row in evaluated
        if row["asset_type"] == asset_type
    ]

    total = len(assets)

    discovered = sum(
        row["discovered"]
        for row in assets
    )

    interacted = sum(
        row["interacted"]
        for row in assets
    )
    engaged = sum(
        row["engaged"]
        for row in assets
    )

    executed = sum(
        row.get("executed", 0)
        for row in assets
    )

    metrics = {
    "deployed": total,
    "discovered": discovered,
    "interacted": interacted,
    "engaged": engaged,

    "discovery_rate": (
        discovered / total
        if total else 0.0
    ),

    "interaction_rate": (
        interacted / total
        if total else 0.0
    ),

    "engagement_rate": (
        engaged / discovered
        if discovered else 0.0
    ),
    }

    if asset_type == "binary":
        metrics["executed"] = executed
        metrics["execution_rate"] = (
            executed / total
            if total else 0.0
        )

    return metrics



def build_summary(evaluated):

    return {
        "env": metrics_for(evaluated, "env"),
        "binary": metrics_for(evaluated, "binary"),
        "process": metrics_for(evaluated, "process"),
    }


def calculate_summary(evaluated):
    return {
        "env": metrics_for(
            evaluated,
            "env"
        ),
        "binary": metrics_for(
            evaluated,
            "binary"
        ),
        "process": metrics_for(
            evaluated,
            "process"
        ),

        "honeyfile": metrics_for(
            evaluated,
            "honeyfile"
        )

    }


# -------------------------------------------------------------------
# Write evaluated manifest
# -------------------------------------------------------------------

def write_evaluated_manifest(path, evaluated):

    output_parent = os.path.dirname(
        os.path.abspath(path)
    )

    os.makedirs(
        output_parent,
        exist_ok=True,
    )

    fieldnames = [
        "asset_type",
        "name",
        "path",
        "role",
        "discovered",
        "interacted",
        "engaged",
        "executed",
    ]

    with open(
        path,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(evaluated)


# -------------------------------------------------------------------
# Write JSON summary
# -------------------------------------------------------------------

def write_summary(path, summary):

    summary_parent = os.path.dirname(
        os.path.abspath(path)
    )

    os.makedirs(
        summary_parent,
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            summary,
            f,
            indent=2,
        )


# -------------------------------------------------------------------
# Console summary
# -------------------------------------------------------------------

def print_summary(summary, output_manifest, summary_path):

    # honeyfile-specific output

    m = summary["honeyfile"]

    print()
    print()
    print("Honey file evaluation")
    print("----------------------")
    print(f"  Deployed:          {m['deployed']}")
    print(f"  Discovered:        {m['discovered']}")
    print(f"  Interacted:        {m['interacted']}")
    print(f"  Engaged:           {m['engaged']}")

    print(
        f"  Discovery rate:    "
        f"{m['discovery_rate'] * 100:.2f}%"
    )

    print(
        f"  Interaction rate:  "
        f"{m['interaction_rate'] * 100:.2f}%"
    )

    print(
        f"  Engagement rate:   "
        f"{m['engagement_rate'] * 100:.2f}%"
    )


    print()
    print("Honey asset evaluation")
    print("----------------------")

    for asset_type in [
        "env",
        "binary",
        "process",
    ]:

        m = summary[asset_type]

        print()
        print(asset_type.upper())

        print(f"  Deployed:     {m['deployed']}")
        print(f"  Discovered:   {m['discovered']}")
        print(f"  Interacted:   {m['interacted']}")
        print(f"  Engaged:       {m['engaged']}")

        print(
            f"  Discovery:"
            f"{m['discovery_rate'] * 100:.2f}%"
        )

        print(
            f"  Interaction:"
            f"{m['interaction_rate'] * 100:.2f}%"
        )

        print(
            f"  Engagement:"
            f"{m['engagement_rate'] * 100:.2f}%"
        )

        if asset_type == "binary":
            print(f"  Executed:      {m['executed']}")
            print(
                f"  Execution:"
                f"{m['execution_rate'] * 100:.2f}%"
            )


    print()
    print(f"Evaluated manifest: {output_manifest}")
    print(f"Summary:            {summary_path}")


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():

    # Parse arguments
    args = parse_args()

    input_file_list = [
        args.honeyfile_manifest,
        args.env_manifest,
        args.binary_manifest,
        args.discovery_log,
        args.tetragon_log
    ]
    validate_input_files(input_file_list)

    # Read input files
    honeyfile_rows = read_csv(
    args.honeyfile_manifest
    )
    
    env_rows = read_csv(
        args.env_manifest
    )

    binary_rows = read_csv(
        args.binary_manifest
    )

    discovery_text = read_text(
        args.discovery_log
    )

    tetragon_text = read_text(
        args.tetragon_log
    )

    # -------------------------------------------------------------------
    # Parse Tetragon EXEC events
    # Expected format:
    # timestamp | EXEC | PID=x | PPID=x | binary | arguments
    # -------------------------------------------------------------------
    # Parse Tetragon events
    exec_events = parse_exec_events(
        tetragon_text
    )


    # parse honeyfile READ observations
    accessed_paths = read_interacted_paths(
        tetragon_text,
        honeyfile_rows
    )


    # ---------------------------------------------------------------
    # Evaluate assets (honey files, binaries and envs)
    # ---------------------------------------------------------------
    # Evaluate honey binaries and envs
    # returns
    # evaluated.append({
    #            "asset_type": asset_type,
    #            "name": row["name"],
    #            "path": row["path"],
    #            "role": row.get("role", ""),
    #            "discovered": int(discovered),
    #            "interacted": int(interacted),
    #        })
    evaluated = evaluate_assets(
        honeyfile_rows,
        accessed_paths,
        env_rows,
        binary_rows,
        discovery_text,
        exec_events,
    )

    # Calculate metrics
    # return {
    #        "env": metrics_for(evaluated, "env"),
    #        "binary": metrics_for(evaluated, "binary"),
    #        "process": metrics_for(evaluated, "process"),
    #    }
    #summary = build_summary(
    #    evaluated
    #)
    summary = calculate_summary(
    evaluated
)

    # Write results
    write_evaluated_manifest(
        args.output_manifest,
        evaluated,
    )

    write_summary(
        args.summary,
        summary,
    )

    # Print results
    print_summary(
        summary,
        args.output_manifest,
        args.summary,
    )


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

if __name__ == "__main__":
    main()