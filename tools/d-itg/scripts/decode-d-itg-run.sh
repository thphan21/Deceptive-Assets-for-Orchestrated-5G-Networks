#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <experiment-directory>"
    exit 1
fi

RESULT_DIR="$(realpath "$1")"

cd "$RESULT_DIR"

for log in uplink-receiver.log downlink-receiver.log; do
    if [[ ! -s "$log" ]]; then
        echo "ERROR: Missing or empty file: $RESULT_DIR/$log" >&2
        exit 1
    fi
done

echo "Decoding uplink..."

ITGDec uplink-receiver.log \
    > uplink-summary.txt

ITGDec uplink-receiver.log \
    -d 1000 uplink-delay.dat \
    -j 1000 uplink-jitter.dat \
    -b 1000 uplink-bitrate.dat \
    -p 1000 uplink-packetloss.dat

echo "Decoding downlink..."

ITGDec downlink-receiver.log \
    > downlink-summary.txt

ITGDec downlink-receiver.log \
    -d 1000 downlink-delay.dat \
    -j 1000 downlink-jitter.dat \
    -b 1000 downlink-bitrate.dat \
    -p 1000 downlink-packetloss.dat

sha256sum \
    uplink-summary.txt \
    downlink-summary.txt \
    uplink-*.dat \
    downlink-*.dat \
    > ditg-checksums.sha256

echo
echo "D-ITG metrics exported to:"
echo "$RESULT_DIR"
