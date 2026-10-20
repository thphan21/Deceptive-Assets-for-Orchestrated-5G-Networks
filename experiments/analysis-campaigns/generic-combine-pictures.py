#!/usr/bin/env python3

from pathlib import Path
import argparse
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

'''
Example Usage:

python3 ~/experiments/analysis-ditg/generic-combine-pictures.py \
  --i 2 \
  --j 3 \
  --out ~/experiments/combined.png \
  --caption "Figure 1: Throughput and delay results for all scenarios" \
  --caption-size 16 \
  --image-caption "(a) Scenario 1" \
  --image-caption "(b) Scenario 2" \
  --image-caption "(c) Scenario 3" \
  --image-caption "(d) Scenario 4" \
  --image-caption "(e) Scenario 5" \
  --image-caption "(f) Scenario 6" \
  ~/experiments/plot1.png \
  ~/experiments/plot2.png \
  ~/experiments/plot3.png \
  ~/experiments/plot4.png \
  ~/experiments/plot5.png \
  ~/experiments/plot6.png

results in:

        Figure 1: Throughput and delay results for all scenarios

plot1   plot2   plot3
plot4   plot5   plot6

(each plot also gets its own small caption underneath)
'''

# Width of one grid cell in inches. Cell height is derived from the images.
CELL_WIDTH = 6.0


def combine_images(i, j, image_paths, out_path,
                   caption=None, caption_size=14,
                   image_captions=None, image_caption_size=12):
    """
    Combine images into an i x j grid.

    i = number of rows
    j = number of columns
    image_paths = list of image paths
    out_path = output image path
    caption = optional overall caption placed above the whole grid
    caption_size = font size of the overall caption
    image_captions = optional list of per-image captions (same order as images)
    image_caption_size = font size of the per-image captions
    """

    if len(image_paths) > i * j:
        raise ValueError(
            f"Grid {i}x{j} has {i*j} spaces, "
            f"but {len(image_paths)} images were provided."
        )

    if image_captions and len(image_captions) > len(image_paths):
        raise ValueError(
            f"{len(image_captions)} image captions were provided, "
            f"but only {len(image_paths)} images."
        )

    images = [mpimg.imread(path) for path in image_paths]

    # Size each cell to the images' own aspect ratio (height / width).
    # A fixed cell shape is what left empty bands above and below each plot.
    aspect = max(img.shape[0] / img.shape[1] for img in images)
    cell_height = CELL_WIDTH * aspect

    fig, axes = plt.subplots(
        i,
        j,
        figsize=(CELL_WIDTH * j, cell_height * i),
        squeeze=False,              # always a 2D array, even for 1x1
        constrained_layout=True     # makes room for the caption and labels
    )
    axes = axes.flatten()

    for idx, (ax, image) in enumerate(zip(axes, images)):
        ax.imshow(image)
        ax.axis("off")

        # Per-image caption (below the image)
        if image_captions and idx < len(image_captions):
            ax.text(
                0.5, -0.02,
                image_captions[idx],
                transform=ax.transAxes,
                ha="center",
                va="top",
                fontsize=image_caption_size
            )

    # Hide unused grid positions
    for ax in axes[len(images):]:
        ax.axis("off")

    # Overall caption at the top of the figure
    if caption:
        fig.suptitle(caption, fontsize=caption_size)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # bbox_inches="tight" crops whatever margin is left around the content
    plt.savefig(
        out_path,
        dpi=300,
        bbox_inches="tight",
        pad_inches=0.1
    )

    plt.close(fig)

    print(f"Saved combined image to: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Combine multiple images into an i x j grid."
    )

    parser.add_argument("--i", type=int, required=True, help="Number of rows")
    parser.add_argument("--j", type=int, required=True, help="Number of columns")
    parser.add_argument("--out", required=True, help="Output image path")
    parser.add_argument(
        "--caption",
        default=None,
        help="Overall caption placed above the combined figure"
    )
    parser.add_argument(
        "--caption-size",
        type=int,
        default=14,
        help="Font size of the overall caption (default: 14)"
    )
    parser.add_argument(
        "--image-caption",
        action="append",
        default=None,
        help="Caption for an individual image. Repeat once per image, "
             "in the same order as the images"
    )
    parser.add_argument(
        "--image-caption-size",
        type=int,
        default=12,
        help="Font size of the per-image captions (default: 12)"
    )
    parser.add_argument(
        "images",
        nargs="+",
        help="Paths to input images in display order"
    )

    args = parser.parse_args()

if __name__ == "__main__":
    combine_images(
        args.i,
        args.j,
        args.images,
        args.out,
        caption=args.caption,
        caption_size=args.caption_size,
        image_captions=args.image_caption,
        image_caption_size=args.image_caption_size
    )