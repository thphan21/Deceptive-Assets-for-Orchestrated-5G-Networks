#!/usr/bin/env python3

import argparse
import csv
import os
import shlex
import subprocess
from datetime import datetime, timezone


# ===================================================================
# Configuration
# ===================================================================

BINARY_DIRECTORY = "/opt/open5gs/bin"


# -------------------------------------------------------------------
# Honey ENV candidates
#
# For every logical asset, candidates are tried from top to bottom.
# An existing real environment variable is NEVER overwritten.
# -------------------------------------------------------------------

HONEY_ENV_CANDIDATES = {
# For the logical honey asset "database_uri", try these names from top to 
# bottom until an unused one is found.

    "database_uri": [
        "DATABASE_URI",
        "BACKUP_DATABASE_URI",
        "SUBSCRIBER_DATABASE_URI",
        "LEGACY_DATABASE_URI",
    ],

    "database_host": [
        "DATABASE_HOST",
        "BACKUP_DATABASE_HOST",
        "SUBSCRIBER_DATABASE_HOST",
        "LEGACY_DATABASE_HOST",
    ],

    "backup_database": [
        "BACKUP_DATABASE",
        "SUBSCRIBER_BACKUP_DATABASE",
        "LEGACY_SUBSCRIBER_DATABASE",
    ],

    "ssh_key_path": [
        "SSH_KEY_PATH",
        "BACKUP_SSH_KEY_PATH",
        "SUBSCRIBER_SSH_KEY_PATH",
    ],

    "api_token": [
        "API_TOKEN",
        "BACKUP_API_TOKEN",
        "SUBSCRIBER_API_TOKEN",
        "LEGACY_API_TOKEN",
    ],
}


HONEY_ENV_VALUES = {
    "database_uri":
        "mongodb://backup-reader:db-secret@mongodb-backup.open5gs.local:27017/open5gs",

    "database_host":
        "mongodb-backup.open5gs.local",

    "backup_database":
        "/opt/open5gs/backups/subscriber-db-previous.dump",

    "ssh_key_path":
        "/opt/open5gs/etc/open5gs/hnet/subscriber-backup.key",

    "api_token":
        "honey-open5gs-api-token-7f3a91c2",
}


# -------------------------------------------------------------------
# Honey binary candidates
#
# The first name that:
#
#   1. does not already exist in /usr/local/bin
#   2. cannot already be resolved through $PATH
#
# is selected.
# -------------------------------------------------------------------

HONEY_BINARY_CANDIDATES = {
    "ping1": [
        "ping1",
        "netping1",
        "net-ping-old",
        "service-ping1",
    ],

    "ping2": [
        "ping2",
        "netping2",
        "net-ping2-old",
        "service-ping2",
    ],

    "ping3": [
        "ping3",
        "netping3",
        "net-ping3-old",
        "service-ping3",
    ],

    "curl1": [
        "curl1.0",
        "curl-legacy1",
        "service-curl1",
        "netcurl1",
    ],

    "curl2": [
        "curl2.0",
        "curl-legacy2",
        "service-curl2",
        "netcurl2",
    ],

    "curl3": [
        "curl3.0",
        "curl-legacy3",
        "service-curl3",
        "netcurl3",
    ],

    "db_check": [
        "open5gs-db-status",
        "open5gs-subscriber-db-check",
        "open5gs-db-health-old",
        "open5gs-subscriber-db-health",
    ],

    "migration": [
        "open5gs-db-backup",
        "open5gs-dbmig",
        "open5gs-mongodb",
        "open5gs-mig",
        "open5gs-db-subscriber-migration",
        "open5gs-subscriber-migration",
        "open5gs-db-mig-backup",
        "open5gs-subscriber-db-migrate",
    ],
}


# ===================================================================
# Arguments
# ===================================================================

parser = argparse.ArgumentParser(
    description=(
        "Deploy honey environment definitions, binaries, "
        "pinned shell history and a honey process."
    )
)

parser.add_argument(
    "--pod",
    required=True,
    help="Target Kubernetes pod",
)

parser.add_argument(
    "--namespace",
    default="open5gs",
    help="Kubernetes namespace (default: open5gs)",
)

parser.add_argument(
    "--manifest",
    required=True,
    help="Output CSV manifest for deployed honey assets",
)

parser.add_argument(
    "--env-output",
    required=True,
    help=(
        "Local output file containing the selected environment "
        "assignments for starting the Caldera agent"
    ),
)

parser.add_argument(
    "--honeyfile-manifest",
    help="Existing honeyfile manifest to append the db-backup lure to",
)

parser.add_argument(
    "--asset-type",
    required=True,
    choices=["env", "binary"],
    help="Honey asset type to deploy: env or binary",
)

parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Show planned deployment without changing the pod",
)

args = parser.parse_args()


# ===================================================================
# State
# ===================================================================

# manifest
rows = []

# actual names chosen for ENV assets
selected_env = {}

# which executable filename was selected for each role e.g. 
# "curl1": {"name": "curl1.0", "path": "/usr/local/bin/curl1.0"}
selected_binaries = {}

deployment_time = datetime.now(timezone.utc).isoformat()


# ===================================================================
# Helpers
# ===================================================================

def shell_quote(value):
    return shlex.quote(str(value))


def kubectl_exec(command, check=True):

    result = subprocess.run(
        [
            "kubectl",
            "-n", args.namespace,
            "exec",
            args.pod,
            "--",
            "/bin/sh",
            "-c",
            command,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed in pod:\n"
            f"{command}\n\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    return result


def kubectl_exec_capture(command):

    result = kubectl_exec(command)

    return result.stdout.strip()


def add_manifest_row(
    asset_type,
    path,
    name,
    role,
    value_or_target="",
    size_bytes="",
    details="",
):

    rows.append({
        "asset_type": asset_type,
        "path": path,
        "name": name,
        "role": role,
        "value_or_target": value_or_target,
        "size_bytes": size_bytes,
        "details": details,
        "pod": args.pod,
        "namespace": args.namespace,
        "deployment_time": deployment_time,
    })


# ===================================================================
# Inspect real environment
# ===================================================================

def get_existing_environment():

    output = kubectl_exec_capture("env") # run env inside pod

    environment = {}

    for line in output.splitlines():

        if "=" not in line:
            continue

        name, value = line.split("=", 1)

        environment[name] = value

    return environment


# ===================================================================
# Select honey ENV names
# ===================================================================

def select_honey_env():

    print()
    print("Selecting honey ENV variables")
    print("----------------------------------------")

    existing_env = get_existing_environment() # dict

    for role, candidates in HONEY_ENV_CANDIDATES.items():

        selected_name = None

        for candidate in candidates:

            if candidate not in existing_env:
                selected_name = candidate
                break

            print(
                f"[skip env] {candidate} already exists"
            )

        if selected_name is None:
            raise RuntimeError(
                f"No unused ENV candidate available for role: {role}"
            )

        # env content
        if HONEY_ENV_VALUES[role] is None:
            raise RuntimeError(
                f"HONEY_ENV_VALUES doesnt contain {role}"
            )
        
        value = HONEY_ENV_VALUES[role] 

        selected_env[role] = {
            "name": selected_name,
            "value": value,
        }

        print(
            f"[env] {selected_name}={value}"
        )

        add_manifest_row(
            asset_type="env",
            path=f"ENV:{selected_name}",
            name=selected_name,
            role=role,
            value_or_target=value,
            size_bytes=len(value.encode()),
            details="selected unused environment variable",
        )


# ===================================================================
# Check whether a binary name already exists
# ===================================================================

def binary_name_exists(name):

    path = f"{BINARY_DIRECTORY}/{name}"

    command = (
        f"if [ -e {shell_quote(path)} ] || "
        f"command -v {shell_quote(name)} >/dev/null 2>&1; "
        f"then exit 0; "
        f"else exit 1; "
        f"fi"
    )

    result = kubectl_exec(
        command,
        check=False,
    )

    return result.returncode == 0


# ===================================================================
# Select unused honey binary names
# ===================================================================

def select_honey_binaries():

    print()
    print("Selecting honey binary names")
    print("----------------------------------------")

    already_selected = set()

    for role, candidates in HONEY_BINARY_CANDIDATES.items():

        selected_name = None

        for candidate in candidates:

            if candidate in already_selected:
                continue

            if binary_name_exists(candidate):

                print(
                    f"[skip binary] {candidate} already exists"
                )

                continue

            selected_name = candidate
            break

        if selected_name is None:
            raise RuntimeError(
                f"No unused binary candidate available for role: {role}"
            )

        path = f"{BINARY_DIRECTORY}/{selected_name}"

        selected_binaries[role] = {
            "name": selected_name,
            "path": path,
        }

        already_selected.add(selected_name)

        print(
            f"[binary selected] {path}"
        )



# ===================================================================
# Deploy complementing honey.yaml file to the honey process binary
# ===================================================================

def append_db_backup_config_manifest():

    if not args.honeyfile_manifest:
        return

    path = DB_BACKUP_CONFIG

    result = kubectl_exec_capture(
        f"stat -c %s {shell_quote(path)}"
    )

    size_bytes = result.strip()

    row = {
        "path": path,
        "directory": os.path.dirname(path),
        "filename": os.path.basename(path),
        "extension": ".yaml",
        "size_bytes": size_bytes,
        "density_requested": "linked-binary-lure",
        "seed": "",
        "mtime": deployment_time,
        "wasAccessed": "",
        "previous_honeyfiles_path": "",
    }

    fieldnames = [
        "path",
        "directory",
        "filename",
        "extension",
        "size_bytes",
        "density_requested",
        "seed",
        "mtime",
        "wasAccessed",
        "previous_honeyfiles_path",
    ]

    with open(
        args.honeyfile_manifest,
        "a",
        newline="",
        encoding="utf-8",
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )

        writer.writerow(row)

DB_BACKUP_CONFIG = (
    # "/opt/open5gs/etc/open5gs/subscriber-migration.yaml"
    "/opt/open5gs/etc/open5gs/db-backup.yaml"
)

def deploy_db_backup_config():

    print()
    print("Deploying db-backup honeyfile")
    print("----------------------------------------")

    content = (
        "database:\n"
        "  host: mongodb\n"
        "  port: 27017\n"
        "  name: open5gs\n"
        "\n"
        "backup:\n"
        "  enabled: true\n"
        "  directory: /opt/open5gs/backups\n"
        "  interval_hours: 24\n"
        "  retention_days: 7\n"
        "  compression: gzip\n"
        "\n"
        "worker:\n"
        "  enabled: true\n"
        "  mode: background\n"
        "  retry_interval_seconds: 60\n"
        "\n"
        "logging:\n"
        "  level: info\n"
        "  file: /var/log/open5gs/db-backup.log\n"
    )

    print(f"[honeyfile] {DB_BACKUP_CONFIG}")

    if args.dry_run:
        return
    if kubectl_exec(
        f"test -e {shell_quote(DB_BACKUP_CONFIG)}",
        check=False
    ).returncode == 0:
        raise RuntimeError(
            f"Refusing to overwrite existing file: {DB_BACKUP_CONFIG}"
        )
    
    kubectl_exec(
        f"printf %s {shell_quote(content)} "
        f"> {shell_quote(DB_BACKUP_CONFIG)} && "
        f"chmod 0644 {shell_quote(DB_BACKUP_CONFIG)}"
    )

    append_db_backup_config_manifest()


# ===================================================================
# Generate binary content
# ===================================================================

def binary_content(role):

    if role in {"ping1", "ping2", "ping3"}:

        return (
            "#!/bin/sh\n"
            'exec ping "$@"\n'
        )

    if role in {"curl1", "curl2", "curl3"}:

        return (
            "#!/bin/sh\n"
            'exec curl "$@"\n'
        )

    if role == "db_check":

        database_host = HONEY_ENV_VALUES["database_host"]

        return (
            "#!/bin/sh\n"
            f'echo "database: {database_host}"\n'
            'echo "status: reachable"\n'
            'echo "role: backup-reader"\n'
        )

    if role == "migration":

        return (
            "#!/bin/sh\n"
            "\n"
            f'CONFIG="{DB_BACKUP_CONFIG}"\n'
            "\n"
            'if [ "${1:-}" = "--worker" ]; then\n'
            '    while true; do\n'
            '        sleep 300\n'
            '    done\n'
            'fi\n'
            "\n"
            'echo "Open5GS database backup utility"\n'
            'echo "status: enabled"\n'
            'echo "backup directory: /opt/open5gs/backups"\n'
            'echo "interval: 24 hours"\n'
            'echo "compression: gzip"\n'
            'echo "config: $CONFIG"\n'
        )

    raise RuntimeError(
        f"Unknown binary role: {role}"
    )


# ===================================================================
# Deploy honey binaries
# ===================================================================

def deploy_honey_binaries():

    print()
    print("Deploying honey binaries")
    print("----------------------------------------")

    for role, binary in selected_binaries.items():

        name = binary["name"]
        path = binary["path"]

        content = binary_content(role)

        print(f"[binary] {path}")

        if not args.dry_run:

            #
            # Important:
            #
            # Check AGAIN immediately before creation.
            #
            # This prevents accidentally overwriting something that
            # appeared between selection and deployment.
            #

            if binary_name_exists(name):
                raise RuntimeError(
                    f"Refusing to overwrite existing binary: {name}"
                )

            kubectl_exec(
                f"mkdir -p {shell_quote(BINARY_DIRECTORY)} && "
                f"printf %s {shell_quote(content)} "
                f"> {shell_quote(path)} && "
                f"chmod 0755 {shell_quote(path)}"
            )

            size_output = kubectl_exec_capture(
                f"wc -c < {shell_quote(path)}"
            )

            size_bytes = size_output.strip()

        else:
            size_bytes = len(content.encode())

        add_manifest_row(
            asset_type="binary",
            path=path,
            name=name,
            role=role,
            size_bytes=size_bytes,
            details="generated honey executable",
        )


# ===================================================================
# Build pinned history using ACTUAL selected binary names
# ===================================================================

def build_pinned_history():

    fake_ping = selected_binaries["ping1"]["name"]
    db_check = selected_binaries["db_check"]["name"]
    curl = selected_binaries["curl1"]["name"]

    database_host = HONEY_ENV_VALUES["database_host"]

    return [
        f"{fake_ping} -c 3 mongodb.open5gs.svc.cluster.local",
        db_check,
        f"{curl} http://{database_host}:27017",
        f'mongosh "mongodb://backup:123456@{database_host}:27017/open5gs"',
        "export DB_PASSWORD=fhkjemuhhxgidfvehfgr2026",
    ]


# ===================================================================
# Pin commands to top of Bash history
# ===================================================================

def deploy_pinned_history():

    print()
    print("Pinning honey commands to Bash history")
    print("----------------------------------------")

    pinned_history = build_pinned_history()

    for index, command in enumerate(
        pinned_history,
        start=1,
    ):
        print(
            f"[history {index}] {command}"
        )

    for index, command in enumerate(
        pinned_history,
        start=1,
    ):

        add_manifest_row(
            asset_type="history",
            path=f"HISTORY:{index}",
            name=f"pinned_history_{index}",
            role="binary_discovery",
            value_or_target=command,
            details="pinned command at beginning of Bash history",
        )

    if args.dry_run:
        return

    pinned_text = "\n".join(
        pinned_history
    ) + "\n"

    #
    # Build grep exclusions dynamically.
    #
    # This removes previous exact copies of the honey commands while
    # preserving every other genuine history entry.
    #

    grep_exclusions = " ".join(
        f"-e {shell_quote(command)}"
        for command in pinned_history
    )

    kubectl_exec(
        f'''
HOME_DIR="${{HOME:-/tmp}}"
HISTFILE="$HOME_DIR/.bash_history"
TMPFILE="/tmp/honey-history.$$"

touch "$HISTFILE"

grep -vxF \
    {grep_exclusions} \
    "$HISTFILE" > "$TMPFILE" || true

{{
    printf %s {shell_quote(pinned_text)}
    cat "$TMPFILE"
}} > "$HISTFILE"

rm -f "$TMPFILE"
'''
    )


# ===================================================================
# Start honey process
# ===================================================================

def start_honey_process():

    print()
    print("Starting honey process")
    print("----------------------------------------")

    migration = selected_binaries["migration"]

    name = migration["name"]
    path = migration["path"]

    command = f"{path} --worker"

    print(
        f"[process] {command}"
    )

    add_manifest_row(
        asset_type="process",
        path=path,
        name=name,
        role="migration_worker",
        value_or_target="--worker",
        details="long-running honey process visible through process discovery",
    )

    if args.dry_run:
        return

    #
    # Use the exact selected binary path.
    #
    # Avoid creating duplicate workers when the deployment script is
    # accidentally run more than once.
    #

    kubectl_exec(
        f'''
if ! ps aux 2>/dev/null | \
    grep -F {shell_quote(command)} | \
    grep -v grep \
    >/dev/null 2>&1
then
    nohup {shell_quote(path)} --worker \
        >/tmp/{shell_quote(name)}.log \
        2>&1 \
        </dev/null &
fi
'''
    )


# ===================================================================
# Write host-side ENV launch file
#
# IMPORTANT:
#
# This file exists on the machine running this deployment script,
# NOT inside the target pod.
#
# Therefore it is not an additional attacker-visible artifact inside
# the UDR filesystem.
# ===================================================================

def write_env_output():

    print()
    print("Writing Caldera-agent ENV launch definitions")
    print("----------------------------------------")

    print(
        f"[local] {args.env_output}"
    )

    if args.dry_run:
        return

    output_directory = os.path.dirname(
        os.path.abspath(args.env_output)
    )

    os.makedirs(
        output_directory,
        exist_ok=True,
    )

    with open(
        args.env_output,
        "w",
        encoding="utf-8",
    ) as handle:

        handle.write(
            "# Honey environment variables\n"
        )

        handle.write(
            "# Source this BEFORE starting the Caldera agent.\n"
        )

        handle.write(
            "# This file exists on the controller/host only.\n\n"
        )

        for asset in selected_env.values():

            name = asset["name"]
            value = asset["value"]

            handle.write(
                f"export {name}={shell_quote(value)}\n"
            )

    os.chmod(
        args.env_output,
        0o600,
    )


# ===================================================================
# Write manifest
# ===================================================================

def write_manifest():

    print()
    print("Writing honey asset manifest")
    print("----------------------------------------")

    print(
        f"[manifest] {args.manifest}"
    )

    if args.dry_run:
        return

    manifest_directory = os.path.dirname(
        os.path.abspath(args.manifest)
    )

    os.makedirs(
        manifest_directory,
        exist_ok=True,
    )

    fieldnames = [
        "asset_type",
        "path",
        "name",
        "role",
        "value_or_target",
        "size_bytes",
        "details",
        "pod",
        "namespace",
        "deployment_time",
    ]

    # Check whether the manifest already exists.
    manifest_exists = os.path.exists(args.manifest)

    with open(
        args.manifest,
        "a",
        newline="",
        encoding="utf-8",
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )

        # Only write the header when creating a new manifest.
        if not manifest_exists:
            writer.writeheader()


        # Original ping/curl are behavioral honey binaries:
        # legitimate users are instructed not to use them but certain wrappers instead.
        if args.asset_type == "binary":
            for name, path, role in [
                ("ping", "/bin/ping", "behavioral_trap_ping"),
                ("curl", "/usr/bin/curl", "behavioral_trap_curl"),
            ]:
                rows.append({
                    "asset_type": "binary",
                    "path": path,
                    "name": name,
                    "role": role,
                    "value_or_target": "",
                    "size_bytes": "",
                    "details": "behavioral honey binary",
                    "pod": args.pod,
                    "namespace": args.namespace,
                    "deployment_time": deployment_time,
                })

        writer.writerows(rows)



# ===================================================================
# Verification for binary process
# ===================================================================

def verify():

    if args.dry_run:
        return

    print()
    print("Verification")
    print("----------------------------------------")

    print()
    print("Honey binaries:")

    for binary in selected_binaries.values():

        path = binary["path"]

        result = kubectl_exec_capture(
            f"ls -l {shell_quote(path)}"
        )

        print(result)

    print()
    print("First five Bash history entries:")

    result = kubectl_exec_capture(
        'head -n 5 "${HOME:-/tmp}/.bash_history"'
    )

    print(result)

    print()
    print("Honey process:")

    migration_path = selected_binaries[
        "migration"
    ]["path"]

    result = kubectl_exec(
        f"ps aux | grep -F "
        f"{shell_quote(migration_path + ' --worker')} | "
        f"grep -v grep || true"
    )

    if result.stdout:
        print(result.stdout.strip())


# ===================================================================
# Print agent launch instructions
# ===================================================================

def print_agent_instructions():

    if args.dry_run:
        return

    print()
    print("Honey ENV deployment")
    print("----------------------------------------")

    print(
        "The ENV variables were NOT written into the UDR filesystem."
    )

    print(
        "They are stored locally in:"
    )

    print(
        f"  {args.env_output}"
    )

    print()

    print(
        "Before starting the Caldera agent, load them with:"
    )

    print()

    print(
        f"  source {shlex.quote(args.env_output)}"
    )

    print()

    print(
        "Then start the Caldera agent from that environment."
    )


# ===================================================================
# Main
# ===================================================================

def main():

    print("============================================================")
    print("Honey ENV / Binary Deployment")
    print("============================================================")

    print(f"Pod:       {args.pod}")
    print(f"Namespace: {args.namespace}")
    print(f"Mode:      {'DRY RUN' if args.dry_run else 'DEPLOY'}")

    # ===============================================================
    # 1. Honey ENV assets
    # ===============================================================

    if args.asset_type == "env":
        # Inspect the existing pod environment and select unused ENV names.
        # This also adds the selected ENV assets to the manifest rows.
        select_honey_env()

        # Store the selected ENV definitions outside the pod.
        write_env_output()

    # ===============================================================
    # 2. Honey binary assets
    # ===============================================================

    elif args.asset_type == "binary":

    # Inspect existing files/PATH and select unused binary names.
        select_honey_binaries()

        # Create the selected honey binaries.
        deploy_honey_binaries()

        # Deploy the complementary db-backup YAML honeyfile.
        deploy_db_backup_config()

        # Put commands containing the selected honey binaries at the
        # beginning of Bash history.
        deploy_pinned_history()

        # Start the backup binary as a visible honey process.
        start_honey_process()

        # Verify the deployed binary/history/process state.
        verify()


    # ===============================================================
    # 3. Final output / bookkeeping
    # ===============================================================

    # Write ONE complete manifest containing ENV, binary,
    # history and process assets.
    write_manifest()


    if args.asset_type == "env":
        # Print instructions for using the selected honey ENV variables.
        print_agent_instructions()

    # Print selected Honey Assets
    print()
    print("Selected honey assets")
    print("----------------------------------------")

    print("ENV variables:")
    for asset in selected_env.values():
        print(f"  - {asset['name']}")

    print()
    print("Binaries:")
    for binary in selected_binaries.values():
        print(f"  - {binary['name']}")

    print()
    print("============================================================")
    print("Deployment complete")
    print("============================================================")


if __name__ == "__main__":
    # deploy honey envs and binaries into history
    main()