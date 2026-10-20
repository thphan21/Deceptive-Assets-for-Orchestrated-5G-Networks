#!/usr/bin/env bash

set -euo pipefail

# ------------------------------------------------------------
# Arguments
# ------------------------------------------------------------

NAMESPACE="open5gs"
POD=""
SINCE="10s"
OUTPUT=""


while [[ $# -gt 0 ]]; do
    case "$1" in
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --pod)
            POD="$2"
            shift 2
            ;;
        --since)
            SINCE="$2"
            shift 2
            ;;
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$POD" || -z "$OUTPUT" ]]; then
    echo "Usage:"
    echo "$0 --pod <pod> --output <file> [--namespace open5gs] [--since 10s]"
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

NODE=$(kubectl -n "$NAMESPACE" get pod "$POD" \
  -o jsonpath='{.spec.nodeName}')

TETRAGON_POD=$(kubectl -n kube-system get pods \
  -l app.kubernetes.io/name=tetragon \
  --field-selector "spec.nodeName=$NODE" \
  -o jsonpath='{.items[0].metadata.name}')

if [[ -z "$TETRAGON_POD" ]]; then
    echo "No Tetragon pod found on node: $NODE"
    exit 1
fi


echo "Watching Tetragon"
echo "Namespace: $NAMESPACE"
echo "Pod:       $POD"
echo "Since:     $SINCE"
echo "Output:    $OUTPUT"
echo

# # tetragon pod can hv multiple containers. use "export-stdout" container
# unbuffered for live stream, jq to read json, -r to print strings without quotation marks

kubectl logs -n kube-system \
  "$TETRAGON_POD" \
  -c export-stdout \
  --since="$SINCE" \
  -f \
| jq --unbuffered -r \
  --arg ns "$NAMESPACE" \
  --arg pod "$POD" \
  '
  if (
    .process_exec.process.pod.namespace == $ns
    and
    .process_exec.process.pod.name == $pod
  ) then

    "\(.time) | EXEC | PID=\(.process_exec.process.pid) | PPID=\(.process_exec.parent.pid // -1) | \(.process_exec.process.binary) | \(.process_exec.process.arguments // "")"

  elif (
    .process_kprobe.process.pod.namespace == $ns
    and
    .process_kprobe.process.pod.name == $pod
  ) then

    (.process_kprobe.args[0].file_arg.path // "") as $path
    |
    (.process_kprobe.args[1].int_arg // 0) as $access
    |
    "\(.time) | \(if $access == 4 then "READ" elif $access == 2 then "WRITE" else "ACCESS(\($access))" end) | PID=\(.process_kprobe.process.pid) | \(.process_kprobe.process.binary) | \($path)"

  else
    empty
  end
  ' \
| tee "$OUTPUT"