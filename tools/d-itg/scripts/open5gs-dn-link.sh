#!/usr/bin/env bash

set -euo pipefail

DN_NS="dn-server"
DN_SERVER_IF="dn-server-if"
DN_UPF_IF="dn-upf"

DN_SERVER_ADDR="172.31.0.2/24"
DN_SERVER_IP="172.31.0.2"

DN_UPF_ADDR="172.31.0.1/24"
DN_UPF_IP="172.31.0.1"

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"


get_upf_pid() {
    UPF_POD=$(kubectl -n open5gs get pod \
        -l app.kubernetes.io/name=upf \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}')

    UPF_CONTAINER_ID=$(kubectl -n open5gs get pod "$UPF_POD" \
        -o jsonpath='{.status.containerStatuses[0].containerID}' \
        | sed 's#^[^:]*://##')

    UPF_PID=$(k3s crictl inspect "$UPF_CONTAINER_ID" \
        | jq -r '.info.pid')

    echo "UPF pod: $UPF_POD"
    echo "UPF PID: $UPF_PID"
}


connection_valid() {
    ip netns exec "$DN_NS" \
        ip link show "$DN_SERVER_IF" >/dev/null 2>&1 \
        || return 1

    nsenter -t "$UPF_PID" -n \
        ip link show "$DN_UPF_IF" >/dev/null 2>&1 \
        || return 1

    ip netns exec "$DN_NS" \
        ip route show default \
        | grep -q "default via $DN_UPF_IP dev $DN_SERVER_IF" \
        || return 1
}


ensure_connection() {
    get_upf_pid

    if connection_valid; then
        echo "Downlink connection is already valid."
        return
    fi

    echo "Creating or repairing the downlink connection..."

    # Create the server namespace if it does not exist.
    ip netns add "$DN_NS" 2>/dev/null || true

    # Deleting one side removes the complete old veth pair.
    ip netns exec "$DN_NS" \
        ip link delete "$DN_SERVER_IF" 2>/dev/null || true

    ip link delete "$DN_SERVER_IF" 2>/dev/null || true
    ip link delete "$DN_UPF_IF" 2>/dev/null || true

    # Create the virtual Ethernet cable.
    ip link add "$DN_SERVER_IF" \
        type veth \
        peer name "$DN_UPF_IF"

    # Move one side into dn-server and one side into the UPF.
    ip link set "$DN_SERVER_IF" netns "$DN_NS"
    ip link set "$DN_UPF_IF" netns "$UPF_PID"

    # Configure the server side.
    ip netns exec "$DN_NS" \
        ip link set lo up

    ip netns exec "$DN_NS" \
        ip addr replace "$DN_SERVER_ADDR" dev "$DN_SERVER_IF"

    ip netns exec "$DN_NS" \
        ip link set "$DN_SERVER_IF" up

    ip netns exec "$DN_NS" \
        ip route replace default \
        via "$DN_UPF_IP" \
        dev "$DN_SERVER_IF"

    # Configure the UPF side.
    nsenter -t "$UPF_PID" -n \
        ip addr replace "$DN_UPF_ADDR" dev "$DN_UPF_IF"

    nsenter -t "$UPF_PID" -n \
        ip link set "$DN_UPF_IF" up

    # Verify the virtual connection.
    ip netns exec "$DN_NS" \
        ping -c 1 -W 2 "$DN_UPF_IP" >/dev/null

    echo "Downlink connection created successfully."
}


show_status() {
    get_upf_pid

    echo
    echo "===== dn-server ====="
    ip netns exec "$DN_NS" ip -br addr 2>/dev/null \
        || echo "$DN_NS does not exist"

    echo
    ip netns exec "$DN_NS" ip route 2>/dev/null || true

    echo
    echo "===== UPF network namespace ====="
    nsenter -t "$UPF_PID" -n ip -br addr

    echo
    echo "===== Connection status ====="

    if connection_valid; then
        echo "VALID"
    else
        echo "MISSING OR STALE"
    fi
}


watch_connection() {
    echo "Watching the UPF connection every 10 seconds."

    while true; do
        ensure_connection || true
        sleep 10
    done
}


case "${1:-}" in
    ensure)
        ensure_connection
        ;;

    status)
        show_status
        ;;

    watch)
        watch_connection
        ;;

    *)
        echo "Usage:"
        echo "  sudo $0 ensure"
        echo "  sudo $0 status"
        echo "  sudo $0 watch"
        exit 1
        ;;
esac
