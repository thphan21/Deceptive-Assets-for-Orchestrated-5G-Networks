#!/usr/bin/env bash

set -euo pipefail

source "$HOME/5g-testbed.env"

echo "Gracefully deregistering UEs..."

cd "$UERANSIM_DIR"

for ue in $(sudo ./build/nr-cli -d 2>/dev/null | awk '/^imsi-/ {print $1}'); do
    echo "  $ue"
    sudo ./build/nr-cli "$ue" -e "deregister switch-off" || true
done

sleep 5

echo "Stopping UERANSIM..."

sudo tmux kill-session -t ueransim-ue 2>/dev/null || true
sudo tmux kill-session -t ueransim-gnb 2>/dev/null || true

sudo pkill -TERM -f '/build/nr-ue' 2>/dev/null || true
sudo pkill -TERM -f '/build/nr-gnb' 2>/dev/null || true

for interface in /sys/class/net/uesimtun*; do
    [[ -e "$interface" ]] || continue
    sudo ip link delete "$(basename "$interface")" 2>/dev/null || true
done

echo "UERANSIM stopped."
