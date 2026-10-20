#!/usr/bin/env python3

from pathlib import Path
import math
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import argparse

#BASE = Path("./experiments/analysis-ditg/plots")

parser = argparse.ArgumentParser()
parser.add_argument(
    "--root",
    required=True,
    help="Root directory containing the workload plot folders",
)
args = parser.parse_args()

BASE = Path(args.root)


WORKLOADS = ["0","10MB", "100MB", "1GB", "10GB"]

COLUMNS = 3

for workload in WORKLOADS:
    folder = BASE / workload

    if not folder.is_dir():
        print(f"Skipping {workload}: directory not found")
        continue

    images = sorted(folder.glob("*.png"))

    if not images:
        print(f"Skipping {workload}: no PNG files found")
        continue

    rows = math.ceil(len(images) / COLUMNS)

    fig, axes = plt.subplots(
        rows,
        COLUMNS,
        figsize=(18, 5.5 * rows)
    )

    # Make axes always iterable as a flat list
    axes = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for ax, image_path in zip(axes, images):
        img = mpimg.imread(image_path)
        ax.imshow(img)
        ax.set_title(image_path.stem, fontsize=10)
        ax.axis("off")

    # Hide unused cells
    for ax in axes[len(images):]:
        ax.axis("off")

    fig.suptitle(
        f"{workload} — Experiment Evaluation Plots",
        fontsize=18
    )

    plt.tight_layout(rect=[0, 0, 1, 0.97])

    output = BASE / f"{workload}_combined.png"

    fig.savefig(
        output,
        dpi=150,
        bbox_inches="tight"
    )

    plt.close(fig)

    print(
        f"{workload}: combined {len(images)} plots "
        f"into {rows}x{COLUMNS} -> {output}"
    )