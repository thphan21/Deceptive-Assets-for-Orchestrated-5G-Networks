#!/usr/bin/env bash

set -euo pipefail

echo "Stopping D-ITG tmux sessions..."

for session in \
    ditg-ul-sender \
    ditg-dl-sender \
    ditg-ul-receiver \
    ditg-dl-receiver \
    ditg-gtpu-capture
do
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "  Stopping $session"
        tmux kill-session -t "$session"
    fi
done

echo "Stopping leftover D-ITG and experiment tcpdump processes..."

sudo pkill -f '/usr/bin/ITGSend' 2>/dev/null || true
sudo pkill -f '/usr/bin/ITGRecv' 2>/dev/null || true

echo "D-ITG experiment processes stopped."
