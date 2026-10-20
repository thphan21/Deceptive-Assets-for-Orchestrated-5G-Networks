#!/usr/bin/env bash

set -euo pipefail

PROM_URL="${PROM_URL:-http://127.0.0.1:9091}"
STEP="${PROM_STEP:-5s}"

usage() {
    echo "Usage:"
    echo "  $0 start <experiment-directory>"
    echo "  $0 stop  <experiment-directory>"
    exit 1
}

[[ $# -eq 2 ]] || usage

ACTION="$1"
RESULT_DIR="$(realpath -m "$2")"
PROM_DIR="$RESULT_DIR/prometheus"
JSON_DIR="$PROM_DIR/json"
CSV_DIR="$PROM_DIR/csv"

START_EPOCH_FILE="$PROM_DIR/start_epoch.txt"
START_ISO_FILE="$PROM_DIR/start_iso.txt"
END_EPOCH_FILE="$PROM_DIR/end_epoch.txt"
END_ISO_FILE="$PROM_DIR/end_iso.txt"

mkdir -p "$JSON_DIR" "$CSV_DIR"

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: Required command not found: $1" >&2
        exit 1
    }
}

check_prometheus() {
    curl -fsS "$PROM_URL/-/ready" >/dev/null || {
        echo "ERROR: Prometheus is not reachable at $PROM_URL" >&2
        echo "Ensure the port-forward to localhost:9091 is running." >&2
        exit 1
    }
}

record_start() {
    date +%s > "$START_EPOCH_FILE"
    TZ=Europe/Zurich date --iso-8601=seconds > "$START_ISO_FILE"

    echo "Experiment start recorded:"
    cat "$START_ISO_FILE"
}

query_range() {
    local name="$1"
    local query="$2"
    local output="$JSON_DIR/$name.json"

    echo "Exporting $name..."

    curl -fsSG "$PROM_URL/api/v1/query_range" \
        --data-urlencode "query=$query" \
        --data-urlencode "start=$START_EPOCH" \
        --data-urlencode "end=$END_EPOCH" \
        --data-urlencode "step=$STEP" \
        -o "$output"

    local status
    status=$(jq -r '.status // empty' "$output")

    if [[ "$status" != "success" ]]; then
        echo "ERROR: Prometheus query failed for $name" >&2
        jq . "$output" >&2
        exit 1
    fi
}

json_to_csv() {
    local json_file="$1"
    local csv_file="$2"

    python3 - "$json_file" "$csv_file" <<'PY'
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

json_path = Path(sys.argv[1])
csv_path = Path(sys.argv[2])

with json_path.open("r", encoding="utf-8") as handle:
    payload = json.load(handle)

results = payload.get("data", {}).get("result", [])

label_names = sorted({
    key
    for series in results
    for key in series.get("metric", {}).keys()
})

with csv_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow([
        "timestamp_epoch",
        "timestamp_utc",
        *label_names,
        "value",
    ])

    for series in results:
        labels = series.get("metric", {})
        for timestamp, value in series.get("values", []):
            timestamp_float = float(timestamp)
            timestamp_utc = datetime.fromtimestamp(
                timestamp_float,
                tz=timezone.utc,
            ).isoformat()

            writer.writerow([
                timestamp_float,
                timestamp_utc,
                *[labels.get(label, "") for label in label_names],
                value,
            ])
PY
}

write_metadata() {
    cat > "$PROM_DIR/metadata.txt" <<EOF_META
Prometheus URL: $PROM_URL
Query step: $STEP
Start epoch: $START_EPOCH
End epoch: $END_EPOCH
Start local time: $(cat "$START_ISO_FILE")
End local time: $(cat "$END_ISO_FILE")
Duration seconds: $((END_EPOCH - START_EPOCH))
EOF_META
}

write_queries_only_UPF() {
    cat > "$PROM_DIR/queries.txt" <<'EOF_QUERIES'
upf_cpu_cores:
sum(max by (namespace,pod,container) (
  rate(
    container_cpu_usage_seconds_total{
      namespace="open5gs",
      container=~".*upf.*",
      cpu="total"
    }[30s]
  )
))

upf_memory_mib:
sum(max by (namespace,pod,container) (
  container_memory_working_set_bytes{
    namespace="open5gs",
    container=~".*upf.*"
  }
)) / 1024 / 1024

upf_network_receive_mbps:
8 * sum(max by (namespace,pod,interface) (
  rate(
    container_network_receive_bytes_total{
      namespace="open5gs",
      pod=~".*upf.*",
      interface!="lo"
    }[30s]
  )
)) / 1000000

upf_network_transmit_mbps:
8 * sum(max by (namespace,pod,interface) (
  rate(
    container_network_transmit_bytes_total{
      namespace="open5gs",
      pod=~".*upf.*",
      interface!="lo"
    }[30s]
  )
)) / 1000000

upf_restart_count:
max(
  kube_pod_container_status_restarts_total{
    namespace="open5gs",
    pod=~".*upf.*"
  }
)

upf_target_up:
max(
  up{
    namespace="open5gs",
    service=~".*upf.*"
  }
)

vm_cpu_percent:
100 * (
  1 - avg(
    rate(
      node_cpu_seconds_total{
        mode="idle"
      }[30s]
    )
  )
)

vm_memory_percent:
100 * (
  1 -
  node_memory_MemAvailable_bytes
  /
  node_memory_MemTotal_bytes
)
EOF_QUERIES
}

write_queries() {

cat > "$PROM_DIR/queries.txt" <<'EOF_QUERIES'

udr_cpu_cores:

sum(max by (namespace,pod,container) (
  rate(
    container_cpu_usage_seconds_total{
      namespace="open5gs",
      container=~".*udr.*",
      cpu="total"
    }[30s]
  )
))

udr_memory_mib:

sum(max by (namespace,pod,container) (
  container_memory_working_set_bytes{
    namespace="open5gs",
    container=~".*udr.*"
  }
)) / 1024 / 1024

udr_restart_count:

max(
  kube_pod_container_status_restarts_total{
    namespace="open5gs",
    pod=~".*udr.*"
  }
)

amf_cpu_cores:

sum(max by (namespace,pod,container) (
  rate(
    container_cpu_usage_seconds_total{
      namespace="open5gs",
      container=~".*amf.*",
      cpu="total"
    }[30s]
  )
))

amf_memory_mib:

sum(max by (namespace,pod,container) (
  container_memory_working_set_bytes{
    namespace="open5gs",
    container=~".*amf.*"
  }
)) / 1024 / 1024

amf_restart_count:

max(
  kube_pod_container_status_restarts_total{
    namespace="open5gs",
    pod=~".*amf.*"
  }
)

amf_target_up:

max(
  up{
    namespace="open5gs",
    service=~".*amf.*"
  }
)


smf_cpu_cores:

sum(max by (namespace,pod,container) (
  rate(
    container_cpu_usage_seconds_total{
      namespace="open5gs",
      container=~".*smf.*",
      cpu="total"
    }[30s]
  )
))

smf_memory_mib:

sum(max by (namespace,pod,container) (
  container_memory_working_set_bytes{
    namespace="open5gs",
    container=~".*smf.*"
  }
)) / 1024 / 1024

smf_restart_count:

max(
  kube_pod_container_status_restarts_total{
    namespace="open5gs",
    pod=~".*smf.*"
  }
)

smf_target_up:

max(
  up{
    namespace="open5gs",
    service=~".*smf.*"
  }
)


upf_cpu_cores:

sum(max by (namespace,pod,container) (
  rate(
    container_cpu_usage_seconds_total{
      namespace="open5gs",
      container=~".*upf.*",
      cpu="total"
    }[30s]
  )
))

upf_memory_mib:

sum(max by (namespace,pod,container) (
  container_memory_working_set_bytes{
    namespace="open5gs",
    container=~".*upf.*"
  }
)) / 1024 / 1024

upf_network_receive_mbps:

8 * sum(max by (namespace,pod,interface) (
  rate(
    container_network_receive_bytes_total{
      namespace="open5gs",
      pod=~".*upf.*",
      interface!="lo"
    }[30s]
  )
)) / 1000000

upf_network_transmit_mbps:

8 * sum(max by (namespace,pod,interface) (
  rate(
    container_network_transmit_bytes_total{
      namespace="open5gs",
      pod=~".*upf.*",
      interface!="lo"
    }[30s]
  )
)) / 1000000

upf_restart_count:

max(
  kube_pod_container_status_restarts_total{
    namespace="open5gs",
    pod=~".*upf.*"
  }
)

upf_target_up:

max(
  up{
    namespace="open5gs",
    service=~".*upf.*"
  }
)


vm_cpu_percent:

100 * (
  1 - avg(
    rate(
      node_cpu_seconds_total{
        mode="idle"
      }[30s]
    )
  )
)

vm_memory_percent:

100 * (
  1 -
  node_memory_MemAvailable_bytes
  /
  node_memory_MemTotal_bytes
)

EOF_QUERIES

}

export_metrics_only_UPF_VM() {
    START_EPOCH=$(<"$START_EPOCH_FILE")
    END_EPOCH=$(<"$END_EPOCH_FILE")

    if (( END_EPOCH <= START_EPOCH )); then
        echo "ERROR: End time must be later than start time." >&2
        exit 1
    fi

    query_range "upf_cpu_cores" \
      'sum(max by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{namespace="open5gs",container=~".*upf.*",cpu="total"}[30s])))'

    query_range "upf_memory_mib" \
      'sum(max by (namespace,pod,container) (container_memory_working_set_bytes{namespace="open5gs",container=~".*upf.*"})) / 1024 / 1024'

    query_range "upf_network_receive_mbps" \
      '8 * sum(max by (namespace,pod,interface) (rate(container_network_receive_bytes_total{namespace="open5gs",pod=~".*upf.*",interface!="lo"}[30s]))) / 1000000'

    query_range "upf_network_transmit_mbps" \
      '8 * sum(max by (namespace,pod,interface) (rate(container_network_transmit_bytes_total{namespace="open5gs",pod=~".*upf.*",interface!="lo"}[30s]))) / 1000000'

    query_range "upf_restart_count" \
      'max(kube_pod_container_status_restarts_total{namespace="open5gs",pod=~".*upf.*"})'

    query_range "upf_target_up" \
      'max(up{namespace="open5gs",service=~".*upf.*"})'

    query_range "vm_cpu_percent" \
      '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[30s])))'

    query_range "vm_memory_percent" \
      '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)'

    for json_file in "$JSON_DIR"/*.json; do
        name=$(basename "$json_file" .json)
        json_to_csv "$json_file" "$CSV_DIR/$name.csv"
    done

    write_metadata
    write_queries

    (
        cd "$PROM_DIR"
        sha256sum json/*.json csv/*.csv metadata.txt queries.txt \
            > checksums.sha256
    )

    echo
    echo "Prometheus export complete:"
    echo "$PROM_DIR"
}


export_metrics() {

    START_EPOCH=$(<"$START_EPOCH_FILE")

    END_EPOCH=$(<"$END_EPOCH_FILE")

    if (( END_EPOCH <= START_EPOCH )); then
        echo "ERROR: End time must be later than start time." >&2
        exit 1
    fi


    query_range "udr_cpu_cores" \
      'sum(max by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{namespace="open5gs",container=~".*udr.*",cpu="total"}[30s])))'

    query_range "udr_memory_mib" \
      'sum(max by (namespace,pod,container) (container_memory_working_set_bytes{namespace="open5gs",container=~".*udr.*"})) / 1024 / 1024'

    query_range "udr_restart_count" \
      'max(kube_pod_container_status_restarts_total{namespace="open5gs",pod=~".*udr.*"})'

    query_range "amf_cpu_cores" \
      'sum(max by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{namespace="open5gs",container=~".*amf.*",cpu="total"}[30s])))'

    query_range "amf_memory_mib" \
      'sum(max by (namespace,pod,container) (container_memory_working_set_bytes{namespace="open5gs",container=~".*amf.*"})) / 1024 / 1024'

    query_range "amf_restart_count" \
      'max(kube_pod_container_status_restarts_total{namespace="open5gs",pod=~".*amf.*"})'

    query_range "amf_target_up" \
      'max(up{namespace="open5gs",service=~".*amf.*"})'


    query_range "smf_cpu_cores" \
      'sum(max by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{namespace="open5gs",container=~".*smf.*",cpu="total"}[30s])))'

    query_range "smf_memory_mib" \
      'sum(max by (namespace,pod,container) (container_memory_working_set_bytes{namespace="open5gs",container=~".*smf.*"})) / 1024 / 1024'

    query_range "smf_restart_count" \
      'max(kube_pod_container_status_restarts_total{namespace="open5gs",pod=~".*smf.*"})'

    query_range "smf_target_up" \
      'max(up{namespace="open5gs",service=~".*smf.*"})'


    query_range "upf_cpu_cores" \
      'sum(max by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{namespace="open5gs",container=~".*upf.*",cpu="total"}[30s])))'

    query_range "upf_memory_mib" \
      'sum(max by (namespace,pod,container) (container_memory_working_set_bytes{namespace="open5gs",container=~".*upf.*"})) / 1024 / 1024'

    query_range "upf_network_receive_mbps" \
      '8 * sum(max by (namespace,pod,interface) (rate(container_network_receive_bytes_total{namespace="open5gs",pod=~".*upf.*",interface!="lo"}[30s]))) / 1000000'

    query_range "upf_network_transmit_mbps" \
      '8 * sum(max by (namespace,pod,interface) (rate(container_network_transmit_bytes_total{namespace="open5gs",pod=~".*upf.*",interface!="lo"}[30s]))) / 1000000'

    query_range "upf_restart_count" \
      'max(kube_pod_container_status_restarts_total{namespace="open5gs",pod=~".*upf.*"})'

    query_range "upf_target_up" \
      'max(up{namespace="open5gs",service=~".*upf.*"})'


    query_range "vm_cpu_percent" \
      '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[30s])))'

    query_range "vm_memory_percent" \
      '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)'


    for json_file in "$JSON_DIR"/*.json; do

        name=$(basename "$json_file" .json)

        json_to_csv "$json_file" "$CSV_DIR/$name.csv"

    done

    write_metadata

    write_queries

    (
        cd "$PROM_DIR"

        sha256sum json/*.json csv/*.csv metadata.txt queries.txt \
            > checksums.sha256
    )

    echo
    echo "Prometheus export complete:"
    echo "$PROM_DIR"

}

main() {
    for command in curl jq python3 date realpath sha256sum; do
        require_command "$command"
    done

    check_prometheus

    case "$ACTION" in
        start)
            record_start
            ;;

        stop)
            if [[ ! -s "$START_EPOCH_FILE" ]]; then
                echo "ERROR: No experiment start timestamp found." >&2
                echo "Run '$0 start $RESULT_DIR' before the experiment." >&2
                exit 1
            fi

            date +%s > "$END_EPOCH_FILE"
            TZ=Europe/Zurich date --iso-8601=seconds > "$END_ISO_FILE"

            echo "Experiment end recorded:"
            cat "$END_ISO_FILE"

            export_metrics
            ;;

        *)
            usage
            ;;
    esac
}

main
