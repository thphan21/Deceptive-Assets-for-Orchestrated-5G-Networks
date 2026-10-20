#!/usr/bin/env python3

import os
import argparse
import csv
import random
import subprocess
import collections
from pathlib import PurePosixPath
from datetime import datetime, timedelta, timezone


# -------------------------------------------------------------------
# Optional semantic filename vocabulary
# -------------------------------------------------------------------

# These names only improve the realism of generated honeyfile names.
#
# They do NOT affect:
#   - which directories are discovered
#   - how many real files exist
#   - density calculation
#   - honeyfile allocation
#   - observed extension distribution
#
# To disable semantic naming completely, simply use:
#
# SEMANTIC_TOKENS = {}
#
# The rest of the script will continue working and will use only
# filename stems derived from legitimate files in the pod.

SEMANTIC_TOKENS = {

    "open5gs": [
        "udr-backup",
        "udr-local",
        "udr-config",
        "subscriber-db",
        "subscriber-cache",
        "subscriber-data",
        "subscriber-backup",
        "service-credentials",
        "service-config",
        "service-account",
        "network-backup",
        "network-config",
        "database-backup",
        "credentials",
        "auth-config",
    ],

    "hnet": [
        "subscriber",
        "subscriber-key",
        "udr-backup",
        "udr-key",
        "network",
        "network-key",
        "service",
        "service-key",
        "hnet-backup",
        "hnet-key",
    ],

    "tls": [
        "udr-backup",
        "udr-client",
        "udr-server",
        "subscriber-db",
        "subscriber-client",
        "service-account",
        "service-client",
        "network-backup",
        "network-client",
        "internal-service",
    ],

    "freediameter": [
        "udr",
        "udr-backup",
        "subscriber",
        "subscriber-auth",
        "service",
        "service-account",
        "diameter-backup",
        "diameter-peer",
        "network",
        "network-peer",
    ],
}


# Generic modifiers.
# These are not tied to any specific directory.
MODIFIERS = [
    "backup",
    "old",
    "local",
    "prod",
    "copy",
    "archive",
    "previous",
    "legacy",
    "internal",
    "2025",
    "2026",
]


# -------------------------------------------------------------------
# Arguments
# -------------------------------------------------------------------

parser = argparse.ArgumentParser()

parser.add_argument(
    "density",
    type=float,
    help="Target honeyfile density in percent, e.g. 10, 20, 50"
)

parser.add_argument(
    "--seed",
    type=int,
    default=42,
    help="Seed for reproducible pseudo-random honeyfile generation"
)

parser.add_argument(
    "--namespace",
    default="open5gs",
    help="Kubernetes namespace of the target pod"
)

parser.add_argument(
    "--pod",
    required=True,
    help="Target Kubernetes pod"
)

parser.add_argument(
    "--root",
    default="/opt/open5gs/etc",
    help="Root directory to inspect for legitimate files"
)

parser.add_argument(
    "--manifest",
    required=True,
    help="Output manifest for the honeyfiles created by this run"
)

parser.add_argument(
    "--previous-honey-manifest",
    help="Manifest from a previous deployment whose honeyfiles should be removed"
)

parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Only print planned honeyfile paths without creating files"
)

args = parser.parse_args()


# Same density + same seed gives the same pseudo-random sequence
# as long as the legitimate filesystem population is also unchanged.

random.seed(args.seed)


# -------------------------------------------------------------------
# Validate density
# -------------------------------------------------------------------

D = args.density / 100.0

if not 0 <= D < 1:
    raise SystemExit(
        "Density must be >= 0 and < 100"
    )


# -------------------------------------------------------------------
# kubectl helpers
# -------------------------------------------------------------------

def kubectl_exec(command):
    """
    Execute a shell command inside the target pod.

    check=True means Python raises an error if kubectl fails.
    """

    subprocess.run(
        [
            "kubectl",
            "-n", args.namespace,
            "exec", args.pod,
            "--",
            "sh", "-c", command
        ],
        check=True
    )


def kubectl_exec_capture(command):
    """
    Execute a shell command inside the pod and return stdout.
    """

    result = subprocess.run(
        [
            "kubectl",
            "-n", args.namespace,
            "exec", args.pod,
            "--",
            "sh", "-c", command
        ],
        capture_output=True,
        text=True,
        check=True
    )

    return result.stdout


def remote_path_exists(path):
    """
    Check whether a path currently exists inside the pod.
    """

    result = subprocess.run(
        [
            "kubectl",
            "-n", args.namespace,
            "exec", args.pod,
            "--",
            "sh", "-c",
            f"test -e '{path}'"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return result.returncode == 0


def remote_file_size(path):
    """
    Read the actual size of a deployed honeyfile.
    """

    result = subprocess.run(
        [
            "kubectl",
            "-n", args.namespace,
            "exec", args.pod,
            "--",
            "stat", "-c", "%s", path
        ],
        capture_output=True,
        text=True,
        check=True
    )

    return int(
        result.stdout.strip()
    )


# -------------------------------------------------------------------
# Safe cleanup of previous honeyfile deployment
# -------------------------------------------------------------------

def path_is_allowed(path):
    """
    A path may only be removed if it is below the configured root.

    Example root:
        /opt/open5gs/etc
    """

    root = args.root.rstrip("/")

    return (
        path == root
        or path.startswith(root + "/")
    )


def cleanup_previous_manifest(manifest_path):
    """
    Remove honeyfiles from a previous deployment.

    This happens BEFORE scanning the filesystem so that previous
    honeyfiles are not incorrectly counted as legitimate files.
    """

    if not manifest_path:
        return 0

    if not os.path.exists(manifest_path):
        raise SystemExit(
            f"Previous honeyfile manifest does not exist: "
            f"{manifest_path}"
        )

    removed = 0

    with open(
        manifest_path,
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            path = (
                row.get("path", "")
                .strip()
            )

            if not path:
                continue

            if not path_is_allowed(path):
                raise SystemExit(
                    "Refusing to delete path outside "
                    f"allowed deception root: {path}"
                )

            if not remote_path_exists(path):
                continue

            subprocess.run(
                [
                    "kubectl",
                    "-n", args.namespace,
                    "exec", args.pod,
                    "--",
                    "rm", "-f", "--", path
                ],
                check=True
            )

            removed += 1

    return removed


# -------------------------------------------------------------------
# Remove previous honeyfiles first
# -------------------------------------------------------------------

removed_count = cleanup_previous_manifest(
    args.previous_honey_manifest
)

print(
    "Removed honeyfiles from previous experiment: "
    f"{removed_count}"
)

print ("\nPlanned honeyfiles:")

# -------------------------------------------------------------------
# Discover legitimate files dynamically
# -------------------------------------------------------------------

def list_remote_files():
    """
    Return all regular files below the configured root.

    The actual filesystem of the selected pod is the source of truth.
    """

    output = kubectl_exec_capture(
        f"find '{args.root}' -type f"
    )

    return [
        line.strip()
        for line in output.splitlines()
        if line.strip()
    ]


files = list_remote_files()

if not files:
    raise SystemExit(
        f"No files found below {args.root}"
    )


# -------------------------------------------------------------------
# Count real files by directory
# -------------------------------------------------------------------

def count_files_by_directory(paths):
    """
    Count legitimate files in every discovered directory in root.
    (Given root used in protocol is "/opt/open5gs/etc")
    Example:

        /opt/open5gs/etc/open5gs/amf.yaml
        /opt/open5gs/etc/open5gs/udr.yaml
        /opt/open5gs/etc/open5gs/hnet/key.key

    becomes:

        /opt/open5gs/etc/open5gs       -> 2
        /opt/open5gs/etc/open5gs/hnet  -> 1
    """

    counts = collections.Counter()

    for path in paths:

        directory = (
            path.rsplit("/", 1)[0]
        )

        counts[directory] += 1

    return dict(
        sorted(counts.items())
    )


real_files_by_directory = (
    count_files_by_directory(files)
)


# -------------------------------------------------------------------
# Filename analysis
# -------------------------------------------------------------------

def split_filename(path):
    """
    Split a filename into stem and complete extension.

    Examples:

        amf.yaml
            -> amf, .yaml

        subscriber.key.pem
            -> subscriber, .key.pem

        create_tls_certs.sh
            -> create_tls_certs, .sh
    """

    filename = PurePosixPath(path).name

    suffixes = (
        PurePosixPath(filename).suffixes
    )

    extension = "".join(suffixes)

    if extension:
        stem = filename[:-len(extension)]
    else:
        stem = filename

    return stem, extension


def get_extension(filename):
    """
    Return the complete extension dynamically.

    Example:
        subscriber.key.pem
            -> .key.pem
    """

    return "".join(
        PurePosixPath(filename).suffixes
    )


# -------------------------------------------------------------------
# Optional semantic names
# -------------------------------------------------------------------

def semantic_stems_for_directory(directory):
    """
    Return context-aware semantic stems for a directory.

    If SEMANTIC_TOKENS = {}, this returns an empty list and the
    script automatically falls back to filesystem-derived stems.
    """

    if not SEMANTIC_TOKENS:
        return []

    directory_lower = (
        directory.lower()
    )

    # More specific directories must be checked before the generic
    # "open5gs" match.

    if "freediameter" in directory_lower:
        return SEMANTIC_TOKENS.get(
            "freediameter",
            []
        )

    if directory_lower.endswith("/hnet"):
        return SEMANTIC_TOKENS.get(
            "hnet",
            []
        )

    if directory_lower.endswith("/tls"):
        return SEMANTIC_TOKENS.get(
            "tls",
            []
        )

    if "open5gs" in directory_lower:
        return SEMANTIC_TOKENS.get(
            "open5gs",
            []
        )

    return []


# -------------------------------------------------------------------
# Build dynamic file profiles
# -------------------------------------------------------------------

def profile_files_by_directory(paths):
    """
    Build a profile of the legitimate files in every directory.

    Each profile contains:

        filenames
        stems
        extension frequencies
        optional semantic stems
    """

    profiles = {}

    for path in paths:

        directory = (
            path.rsplit("/", 1)[0]
        )

        filename = (
            path.rsplit("/", 1)[1]
        )

        stem, extension = (
            split_filename(path)
        )

        if directory not in profiles:

            profiles[directory] = {
                "filenames": [],
                "stems": [],
                "extensions":
                    collections.Counter(),
                "semantic_stems": [],
            }

        profiles[
            directory
        ]["filenames"].append(
            filename
        )

        profiles[
            directory
        ]["stems"].append(
            stem
        )

        profiles[
            directory
        ]["extensions"][
            extension
        ] += 1

    # Add semantic stems after the actual filesystem has been profiled.

    for directory, profile in profiles.items():

        profile["semantic_stems"] = (
            semantic_stems_for_directory(
                directory
            )
        )

    return profiles


file_profiles = (
    profile_files_by_directory(files)
)


# -------------------------------------------------------------------
# Choose extension according to real extension distribution
# -------------------------------------------------------------------

# Probability that a generated .yaml honeyfile is emitted as .yml
# so it can also be discovered by Caldera abilities searching '*.yml'.
YML_VARIANT_PROBABILITY = 0.30


def choose_extension(extension_counts):
    """
    Choose an extension using the extension frequencies observed in
    the legitimate files of this directory.

    Example:

        .crt = 17
        .key = 16

    gives roughly equal probability.

    A directory containing only .yaml files will generate only .yaml.
    """

    extensions = list(
        extension_counts.keys()
    )

    weights = list(
        extension_counts.values()
    )

    extension = random.choices(
        extensions,
        weights=weights,
        k=1
    )[0]

    if (
        extension == ".yaml"
        and random.random() < YML_VARIANT_PROBABILITY
    ):
        extension = ".yml"

    return extension


# -------------------------------------------------------------------
# Generate honeyfile names
# -------------------------------------------------------------------

def generate_candidate_filename(profile):
    """
    Generate a candidate filename.

    Approximately 60% use semantic stems when semantic naming is
    enabled.

    Otherwise, stems are taken directly from legitimate filenames.
    """

    extension = choose_extension(
        profile["extensions"]
    )

    semantic_stems = profile.get(
        "semantic_stems",
        []
    )

# 60% security/context-aware stems
# 40% stems learned directly from the real filesystem
    use_semantic = (
        bool(semantic_stems)
        and random.random() < 0.6
    )

    if use_semantic:

        stem = random.choice(
            semantic_stems
        )

        # Avoid names such as:
        #
        #   udr-backup-backup.yml
        #   network-backup-old.crt
        #
        # when the semantic stem already contains a modifier.

        stem_parts = (
            stem.lower()
            .replace("_", "-")
            .split("-")
        )

        if any(
            modifier.lower() in stem_parts
            for modifier in MODIFIERS
        ):

            return (
                f"{stem}{extension}"
            )

    else:

        stem = random.choice(
            profile["stems"]
        )

    modifier = random.choice(
        MODIFIERS
    )

    return (
        f"{stem}-{modifier}{extension}"
    )


def generate_unique_candidate(
    directory,
    profile,
    existing_paths,
    planned_paths
):
    """
    Generate candidate names until one is found that:

        1. is not an existing legitimate file
        2. is not already planned as another honeyfile
        3. does not already exist remotely
    """

    while True:

        filename = (
            generate_candidate_filename(
                profile
            )
        )

        path = (
            f"{directory}/{filename}"
        )

        if path in existing_paths:
            continue

        if path in planned_paths:
            continue

        if remote_path_exists(path):
            continue

        planned_paths.add(path)

        return filename


# -------------------------------------------------------------------
# Generate honeyfile contents
# -------------------------------------------------------------------

def content_for(filename):
    """
    Generate fake content according to the inherited file extension.
    """

    extension = (
        get_extension(filename)
    )

    if extension in {
        ".yaml",
        ".yml",
    }:

        return (
            "subscriber_db:\\n"
            "  host: mongodb.open5gs.svc.cluster.local\\n"
            "  username: udr-backup\\n"
            "  password: fake-honey-secret\\n"
            "  collection: subscribers\\n"
        )

    if extension == ".conf":

        return (
            "# Backup Diameter configuration\\n"
            "Identity = udr-backup.open5gs.local;\\n"
            "ConnectPeer = mongodb.open5gs.svc.cluster.local;\\n"
        )

    if extension in {
        ".crt",
        ".cert.pem",
    }:

        return (
            "-----BEGIN CERTIFICATE-----\\n"
            "FAKE-HONEY-CERTIFICATE-DATA\\n"
            "-----END CERTIFICATE-----\\n"
        )

    return (
        "-----BEGIN PRIVATE KEY-----\\n"
        "FAKE-HONEY-PRIVATE-KEY-DATA\\n"
        "-----END PRIVATE KEY-----\\n"
    )


# -------------------------------------------------------------------
# Density calculation
# -------------------------------------------------------------------

def calculate_total_honeyfiles(
    total_real,
    density
):
    """
    Density is defined over the FINAL file population:

        density = honey / (real + honey)

    Therefore:

        honey =
            density / (1 - density)
            * real
    """

    if density == 0:
        return 0

    return round(
        (
            density
            / (1 - density)
        )
        * total_real
    )


total_real = len(files)

total_honey = (
    calculate_total_honeyfiles(
        total_real,
        D
    )
)


# -------------------------------------------------------------------
# Proportional allocation
# -------------------------------------------------------------------

def allocate_honeyfiles(
    real_files_by_directory,
    total_honey
):
    """
    Distribute honeyfiles proportionally according to the legitimate
    file population of each dynamically discovered directory.

    Example:

        directory A: 50 real files
        directory B: 25 real files
        directory C: 25 real files

    approximately becomes:

        50%
        25%
        25%

    of the honeyfile population.
    """

    total_real = sum(
        real_files_by_directory.values()
    )

    allocations = {}

    remaining = total_honey

    items = list(
        real_files_by_directory.items()
    )

    for index, (
        directory,
        real_count
    ) in enumerate(items):

        if index == len(items) - 1:

            honey_count = remaining

        else:

            honey_count = round(
                total_honey
                * real_count
                / total_real
            )

            remaining -= honey_count

        allocations[
            directory
        ] = honey_count

    return allocations


allocations = allocate_honeyfiles(
    real_files_by_directory,
    total_honey
)


# -------------------------------------------------------------------
# Deploy honeyfiles
# -------------------------------------------------------------------

existing_paths = set(files)

planned_paths = set()

rows = []


for directory, count in allocations.items():

    profile = (
        file_profiles[directory]
    )

    for _ in range(count):

        filename = (
            generate_unique_candidate(
                directory,
                profile,
                existing_paths,
                planned_paths
            )
        )

        path = (
            f"{directory}/{filename}"
        )

        content = (
            content_for(filename)
        )

        age_days = random.randint(
            3,
            14
        )

        mtime = (
            datetime.now(timezone.utc)
            - timedelta(days=age_days)
        )

        # Escape embedded single quotes so the generated content can
        # safely be inserted into a single-quoted shell argument.

        shell_content = (
            content.replace(
                "'",
                "'\"'\"'"
            )
        )

        command = (
            # Create file content and interpret escaped newlines.
            f"printf '%b' "
            f"'{shell_content}' "
            f"> '{path}' && "

            # Permissions:
            #   6 = read + write
            #   4 = read
            #
            # 0644:
            #   owner = read/write
            #   group = read
            #   other = read
            f"chmod 0644 "
            f"'{path}' && "

            # Give the honeyfile a plausible historical modification
            # timestamp.
            f"touch -d "
            f"'{mtime.strftime('%Y-%m-%d %H:%M:%S UTC')}' "
            f"'{path}'"
        )

        if args.dry_run:
            print(path)
            size_bytes = ""
        else:
            kubectl_exec(command)
            size_bytes = remote_file_size(path)

        rows.append({
            "path": path,
            "directory": directory,
            "filename": filename,
            "extension": get_extension(filename),
            "size_bytes": size_bytes,
            "density_requested": args.density,
            "seed": args.seed,
            "mtime": mtime.isoformat(),
            "wasAccessed": "",
            "previous_honeyfiles_path": "",
        })


# -------------------------------------------------------------------
# Link this deployment to previous manifest
# -------------------------------------------------------------------

if (
    rows
    and args.previous_honey_manifest
):

    rows[0][
        "previous_honeyfiles_path"
    ] = args.previous_honey_manifest


# -------------------------------------------------------------------
# Write manifest
# -------------------------------------------------------------------

manifest_parent = os.path.dirname(
    os.path.abspath(
        args.manifest
    )
)

os.makedirs(
    manifest_parent,
    exist_ok=True
)


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
    args.manifest,
    "w",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()

    writer.writerows(
        rows
    )


# -------------------------------------------------------------------
# Result summary
# -------------------------------------------------------------------

final_total = (
    total_real
    + total_honey
)

achieved_density = (
    total_honey
    / final_total
    * 100
    if final_total
    else 0
)


print()
print("Honeyfile deployment")
print("--------------------")

print(
    f"Pod:              "
    f"{args.pod}"
)

print(
    f"Namespace:        "
    f"{args.namespace}"
)

print(
    f"Scan root:        "
    f"{args.root}"
)

print()

for directory, real_count in (
    real_files_by_directory.items()
):

    print(directory)

    print(
        f"  real:  "
        f"{real_count}"
    )

    print(
        f"  honey: "
        f"{allocations[directory]}"
    )

    extensions = (
        file_profiles[
            directory
        ]["extensions"]
    )

    extension_text = ", ".join(
        f"{extension or '<none>'}={count}"
        for extension, count
        in extensions.most_common()
    )

    print(
        f"  extensions: "
        f"{extension_text}"
    )

    semantic_stems = (
        file_profiles[
            directory
        ]["semantic_stems"]
    )

    if semantic_stems:

        print(
            "  semantic naming: enabled"
        )

    else:

        print(
            "  semantic naming: disabled"
        )


print()

print(
    f"Real files:       "
    f"{total_real}"
)

print(
    f"Honeyfiles:       "
    f"{total_honey}"
)

print(
    f"Final file count: "
    f"{final_total}"
)

print(
    f"Target density:   "
    f"{args.density:.2f}%"
)

print(
    f"Achieved density: "
    f"{achieved_density:.2f}%"
)

print(
    f"Manifest:         "
    f"{args.manifest}"
)