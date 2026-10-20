
#!/usr/bin/env bash

set -u

RUNTIME_DIR="${HOME}/.local/run/project-port-forwards"
LOG_DIR="${HOME}/.local/log/project-port-forwards"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

# Format:
# name|namespace|resource|local-port|remote-port
FORWARDS=(
  "osm-nbi|osm|svc/nbi|9999|9999"
  "osm-webui|osm|svc/ng-ui|8080|80"
  "open5gs-webui|open5gs|svc/open5gs-0078507098-webui|9998|9999"
  "osm-grafana|osm|svc/grafana|3000|80"
  "osm-prometheus|osm|svc/prometheus|9090|9090"
  "monitoring-prometheus|monitoring|svc/kube-prometheus-stack-0072-prometheus|9091|9090"
  "monitoring-grafana|monitoring|svc/kube-prometheus-stack-0072623329-grafana|3001|80"
  "monitoring-alertmanager|monitoring|pod/alertmanager-kube-prometheus-stack-0072-alertmanager-0|9093|9093"
)

pid_file() {
  echo "${RUNTIME_DIR}/$1.pid"
}

log_file() {
  echo "${LOG_DIR}/$1.log"
}

is_running() {
  local file pid

  file="$(pid_file "$1")"

  [[ -f "$file" ]] || return 1

  pid="$(cat "$file" 2>/dev/null)" || return 1

  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

local_port_in_use() {
  local port="$1"

  ss -ltnH 2>/dev/null |
    awk '{print $4}' |
    grep -Eq "[:.]${port}$"
}

start_forward() {
  local name="$1"
  local namespace="$2"
  local resource="$3"
  local local_port="$4"
  local remote_port="$5"

  local pidfile logfile pid

  pidfile="$(pid_file "$name")"
  logfile="$(log_file "$name")"

  # Avoid starting duplicate port-forwards.
  if is_running "$name"; then
    echo "[RUNNING] $name already active, PID $(cat "$pidfile")"
    return 0
  fi

  rm -f "$pidfile"

  # Verify the Kubernetes resource exists.
  if ! kubectl -n "$namespace" get "$resource" >/dev/null 2>&1; then
    echo "[ERROR] $name: resource not found: $namespace/$resource"
    return 1
  fi

  # Verify the local port is available.
  if local_port_in_use "$local_port"; then
    echo "[ERROR] $name: local port $local_port is already in use"
    return 1
  fi

  echo "[START] $name: 127.0.0.1:${local_port} -> ${namespace}/${resource}:${remote_port}"

  {
    echo
    echo "============================================================"
    echo "Started: $(date --iso-8601=seconds)"
    echo "Command: kubectl -n $namespace port-forward --address 127.0.0.1 $resource $local_port:$remote_port"
    echo "============================================================"
  } >> "$logfile"

  # Start the port-forward in the background.
  nohup kubectl -n "$namespace" port-forward \
    --address 127.0.0.1 \
    "$resource" \
    "${local_port}:${remote_port}" \
    >> "$logfile" 2>&1 &

  pid=$!
  echo "$pid" > "$pidfile"

  sleep 1

  if kill -0 "$pid" 2>/dev/null; then
    echo "[OK] $name started, PID $pid"
  else
    echo "[ERROR] $name failed to start"
    rm -f "$pidfile"
    tail -n 10 "$logfile"
    return 1
  fi
}

start_all() {
  local failures=0
  local entry name namespace resource local_port remote_port

  for entry in "${FORWARDS[@]}"; do
    IFS='|' read -r name namespace resource local_port remote_port <<< "$entry"

    start_forward \
      "$name" \
      "$namespace" \
      "$resource" \
      "$local_port" \
      "$remote_port" || failures=$((failures + 1))
  done

  echo

  if (( failures > 0 )); then
    echo "[WARN] $failures port-forward(s) failed to start."
    return 1
  fi

  echo "[OK] All port-forwards started or already running."
}

# Only supported command: start
if [[ "${1:-}" != "start" ]]; then
  echo "Usage: $0 start"
  exit 1
fi

start_all
