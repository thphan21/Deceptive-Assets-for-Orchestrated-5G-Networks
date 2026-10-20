#!/usr/bin/env bash

set -euo pipefail

source "$HOME/5g-testbed.env"

echo "[1/5] Checking Open5GS pods"
kubectl -n "$OPEN5GS_NS" get pods

echo
echo "[2/5] Ensuring the AMF NGAP NodePort exists"

if ! kubectl -n "$OPEN5GS_NS" \
    get svc open5gs-amf-ngap-nodeport >/dev/null 2>&1
then
    kubectl -n "$OPEN5GS_NS" expose deployment "$OPEN5GS_RELEASE-amf" \
        --name open5gs-amf-ngap-nodeport \
        --type NodePort \
        --port 38412 \
        --target-port ngap \
        --protocol SCTP
fi

NODEPORT=$(kubectl -n "$OPEN5GS_NS" \
    get svc open5gs-amf-ngap-nodeport \
    -o jsonpath='{.spec.ports[0].nodePort}')

echo "AMF NGAP endpoint: $VM_IP:$NODEPORT/SCTP"

echo
echo "[3/5] Enabling IPv4 forwarding"
sudo sysctl -w net.ipv4.ip_forward=1

echo
echo "[4/5] Ensuring NAT for the UE subnet"

sudo iptables -t nat \
    -C POSTROUTING \
    -s "$UE_SUBNET" \
    -o "$EXT_IF" \
    -j MASQUERADE 2>/dev/null ||
sudo iptables -t nat \
    -A POSTROUTING \
    -s "$UE_SUBNET" \
    -o "$EXT_IF" \
    -j MASQUERADE

echo
echo "[5/5] Updating the UERANSIM gNB configuration"

cp -n "$GNB_CONFIG" "$GNB_CONFIG.bak" || true

sed -i -E "s|^linkIp:.*|linkIp: $VM_IP|" "$GNB_CONFIG"
sed -i -E "s|^ngapIp:.*|ngapIp: $VM_IP|" "$GNB_CONFIG"
sed -i -E "s|^gtpIp:.*|gtpIp: $VM_IP|" "$GNB_CONFIG"
sed -i -E "s|^([[:space:]]*- address:).*|\1 $VM_IP|" "$GNB_CONFIG"
sed -i -E "s|^([[:space:]]*port:).*|\1 $NODEPORT|" "$GNB_CONFIG"

echo
echo "UERANSIM environment setup completed."
