#!/usr/bin/env bash

set -euo pipefail

DN_NS="dn-server"
DN_SERVER_IP="172.31.0.2"

if [[ "${1:-check}" != "check" && "${1:-check}" != "repair" ]]; then
    echo "Usage:"
    echo "  $0 check"
    echo "  sudo $0 repair"
    exit 1
fi

ACTION="${1:-check}"

mapfile -t UE_ROWS < <(
    ip -4 -o addr show \
    | awk '$2 ~ /^uesimtun[0-9]+$/ {
        split($4, address, "/")
        print $2, address[1]
      }' \
    | sort -k1V
)

if (( ${#UE_ROWS[@]} == 0 )); then
    echo "ERROR: No uesimtun interfaces were found." >&2
    exit 1
fi

FAILED=0

for row in "${UE_ROWS[@]}"; do
    read -r UE_IF UE_IP <<< "$row"

    ROUTE_TABLE="rt_${UE_IF}"

    echo
    echo "===== $UE_IF / $UE_IP ====="

    echo "Checking policy-routing rule..."

    if ip rule show \
        | grep -q "from ${UE_IP} lookup ${ROUTE_TABLE}"
    then
        echo "  Rule: OK"
    else
        echo "  Rule: MISSING"

        if [[ "$ACTION" == "repair" ]]; then
            echo "  Creating rule..."

            ip rule add \
                from "$UE_IP/32" \
                table "$ROUTE_TABLE"

            echo "  Rule repaired."
        else
            FAILED=1
        fi
    fi

    echo "Checking UE routing table..."

    if ip route show table "$ROUTE_TABLE" 2>/dev/null \
        | grep -q "^default dev ${UE_IF}"
    then
        echo "  Route: OK"
    else
        echo "  Route: MISSING"

        if [[ "$ACTION" == "repair" ]]; then
            echo "  Creating default route..."

            ip route replace \
                default \
                dev "$UE_IF" \
                table "$ROUTE_TABLE"

            echo "  Route repaired."
        else
            FAILED=1
        fi
    fi

    echo "Route selected by Linux:"

    ip route get "$DN_SERVER_IP" from "$UE_IP" \
        || true

    echo "Testing uplink..."

    if ping \
        -I "$UE_IF" \
        -c 2 \
        -W 3 \
        "$DN_SERVER_IP" \
        >/dev/null
    then
        echo "  Uplink: OK"
    else
        echo "  Uplink: FAILED"
        FAILED=1
    fi

    echo "Testing downlink..."

    if ip netns exec "$DN_NS" \
        ping \
        -c 2 \
        -W 3 \
        "$UE_IP" \
        >/dev/null
    then
        echo "  Downlink: OK"
    else
        echo "  Downlink: FAILED"
        FAILED=1
    fi
done

echo

if (( FAILED != 0 )); then
    echo "ERROR: At least one UE path is not healthy." >&2
    echo
    echo "If its rule and route are both present but ping still fails,"
    echo "the problem is in the 5G user-plane session, not Linux routing."
    exit 1
fi

echo "All UE uplink and downlink paths are healthy."y

