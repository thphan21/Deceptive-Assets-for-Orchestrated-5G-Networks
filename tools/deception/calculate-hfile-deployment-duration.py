#!/usr/bin/env python3
import argparse
import json
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--start", required=True)
parser.add_argument("--end", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

def read_timestamp(path):
    return datetime.fromisoformat(
        Path(path).read_text().strip().replace("Z", "+00:00")
    )

start = read_timestamp(args.start)
end = read_timestamp(args.end)

duration = (end - start).total_seconds()

if duration < 0:
    parser.error("End timestamp is earlier than start timestamp.")

result = {
    "Honeyfile Deployment duration": (
        f"{duration:.2f} seconds ({duration / 60:.2f} minutes)"
    )
}

Path(args.output).parent.mkdir(parents=True, exist_ok=True)

with open(args.output, "w") as f:
    json.dump(result, f, indent=2)

print(f"Honeyfile Deployment duration: {result['Honeyfile Deployment duration']}")
print(f"Saved to: {args.output}")