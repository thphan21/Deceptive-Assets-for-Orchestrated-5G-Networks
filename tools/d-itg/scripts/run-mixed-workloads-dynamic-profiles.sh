#!/usr/bin/env bash
# -------------------------------------------------------------------
# Arguments & Variables
# -------------------------------------------------------------------

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 <ue-count> <run-number> <duration-ms> <result-dir>"
    exit 1
fi

UE_COUNT="$1"
RUN_NUMBER="$2"
TEST_DURATION_MS="$3"
RESULT_DIR="$4"

DN_NS="dn-server"
DN_SERVER_IP="172.31.0.2"

# -------------------------------------------------------------------
# Result subdirectories
# -------------------------------------------------------------------

DITG_DIR="$RESULT_DIR/d-itg"
DITG_RAW_DIR="$DITG_DIR/raw"
DITG_CONSOLE_DIR="$DITG_DIR/console"

mkdir -p \
    "$RESULT_DIR" \
    "$DITG_RAW_DIR" \
    "$DITG_CONSOLE_DIR"


UL_RECEIVER_LOG="$DITG_RAW_DIR/uplink-receiver.log"
DL_RECEIVER_LOG="$DITG_RAW_DIR/downlink-receiver.log"

UL_RECEIVER_CONSOLE="$DITG_CONSOLE_DIR/uplink-receiver-console.txt"
DL_RECEIVER_CONSOLE="$DITG_CONSOLE_DIR/downlink-receiver-console.txt"

UL_SENDER_LOG="$DITG_RAW_DIR/uplink-sender.log"
DL_SENDER_LOG="$DITG_RAW_DIR/downlink-sender.log"

UL_SENDER_CONSOLE="$DITG_CONSOLE_DIR/uplink-sender-console.txt"
DL_SENDER_CONSOLE="$DITG_CONSOLE_DIR/downlink-sender-console.txt"

# ================================
# Change the workload profile here.
# ================================
#PROFILE="1GB"
#PROFILE="10GB"
#PROFILE="10MB"
PROFILE="100MB"
#PROFILE="0"

UPLINK_TEMPLATE="$HOME/tools/d-itg/profiles/uplink-profile-${PROFILE}.txt"
DOWNLINK_TEMPLATE="$HOME/tools/d-itg/profiles/downlink-profile-${PROFILE}.txt"


if [[ "$PROFILE" != "0" ]] && [[ ! -f "$UPLINK_TEMPLATE" || ! -f "$DOWNLINK_TEMPLATE" ]]; then
    echo "ERROR: Workload profile missing."
    exit 1
fi


# -------------------------------------------------------------------
# UE health files
# -------------------------------------------------------------------

HEALTHY_FILE_PATH="$RESULT_DIR/healthy-ues.csv"
UNHEALTHY_FILE_PATH="$RESULT_DIR/unhealthy-ues.csv"

UPLINK_PROFILE_PATH="$RESULT_DIR/uplink-profile.txt"
DOWNLINK_PROFILE_PATH="$RESULT_DIR/downlink-profile.txt"



# -------------------------------------------------------------------
# Script
# -------------------------------------------------------------------

echo 
echo "========================================" 
echo "Cleaning old UE policy-routing rules" 
echo "========================================"

while read -r UE_IF UE_IP; do
    TABLE="rt_${UE_IF}"

    echo "========================================"
    echo "Interface: $UE_IF"
    echo "IP:        $UE_IP"
    echo "Table:     $TABLE"

    # Remove any old rules referencing this specific table.
    while ip rule show | grep -q "lookup ${TABLE}$"; do
        PREF=$(
            ip rule show |
            awk -v table="$TABLE" '
                $0 ~ ("lookup " table "$") {
                    gsub(":","",$1)
                    print $1
                    exit
                }'
        )

        sudo ip rule del pref "$PREF"
    done

    # Clear all old routes from this UE's table.
    # Install exactly one rule for the CURRENT UE address.
    # adds a policy-routing rule. Example for uesimtun68
    # "from 10.45.2.10 lookup rt_uesimtun68"
    # = packet w. src ip 10.45.2.10, don't use main routing, 
    # but rt_usetimtun68 routing table
    # see rule in "ip rule show"
    sudo ip rule add \
        from "${UE_IP}/32" \
        table "$TABLE"

    # Add exactly one correct route
    # Replace the table contents with exactly the route we need.
    # clears only the routes inside that routing table
    # bsp uesimtun68 becomes empty
    sudo ip route flush table "$TABLE"

    # Add exactly one correct source-policy rule
    sudo ip route add \
        default \
        dev "$UE_IF" \
        table "$TABLE"

# input source for the loop.
done < <(
    ip -4 -o addr show |
    awk '
        $2 ~ /^uesimtun[0-9]+$/ {
            split($4,a,"/")
            print $2, a[1]
        }
    ' |
    sort -V
)

echo
echo "========================================"
echo "Verifying dn-server, if it exists?"
echo "========================================"

if ! ip netns list | grep -q "^${DN_NS}\b"; then
    echo "ERROR: Network namespace $DN_NS does not exist."
    exit 1
fi

echo "Namespace exists: $DN_NS"

sudo ip netns exec "$DN_NS" ip -br -4 addr
sudo ip netns exec "$DN_NS" ip route

if ! sudo ip netns exec "$DN_NS" \
    ip -4 addr show |
    grep -q "$DN_SERVER_IP"
then
    echo "ERROR: $DN_SERVER_IP is not configured inside $DN_NS."
    exit 1
fi

echo "dn-server IP exists: $DN_SERVER_IP"

mapfile -t UE_CANDIDATES < <(
    ip -4 -o addr show |
    awk '
        $2 ~ /^uesimtun[0-9]+$/ {
            split($4,a,"/")
            print $2 "," a[1]
        }
    ' |
    sort -t, -k1V
)

# check how many exist
echo "Current UE candidates: ${#UE_CANDIDATES[@]}"

# perform health checks

rm -f "$HEALTHY_FILE_PATH" "$UNHEALTHY_FILE_PATH"

printf 'interface,ue_ip\n' > "$HEALTHY_FILE_PATH"
printf 'interface,ue_ip,reason\n' > "$UNHEALTHY_FILE_PATH"

SELECTED=0

for row in "${UE_CANDIDATES[@]}"; do

    IFS=',' read -r UE_IF UE_IP <<< "$row"

    echo
    echo "Checking $UE_IF / $UE_IP"

    # Verify interface still exists.
    if ! ip link show "$UE_IF" >/dev/null 2>&1; then
        echo "  FAIL: interface disappeared"

        printf '%s,%s,%s\n' \
            "$UE_IF" "$UE_IP" "interface-disappeared" \
            >> "$UNHEALTHY_FILE_PATH"

        continue
    fi

    # -----------------------
    # UPLINK
    # UE -> dn-server
    # -----------------------

    if ! ping \
        -I "$UE_IF" \
        -c 1 \
        -W 3 \
        "$DN_SERVER_IP" \
        >/dev/null 2>&1
    then
        echo "  Uplink: FAIL"

        printf '%s,%s,%s\n' \
            "$UE_IF" "$UE_IP" "uplink-failed" \
            >> "$UNHEALTHY_FILE_PATH"

        continue
    fi

    echo "  Uplink: OK"

    # -----------------------
    # DOWNLINK
    # dn-server -> UE
    # -----------------------

    if ! sudo ip netns exec "$DN_NS" \
        ping \
        -c 1 \
        -W 3 \
        "$UE_IP" \
        >/dev/null 2>&1
    then
        echo "  Downlink: FAIL"

        printf '%s,%s,%s\n' \
            "$UE_IF" "$UE_IP" "downlink-failed" \
            >> "$UNHEALTHY_FILE_PATH"

        continue
    fi

    echo "  Downlink: OK"

    # Passed BOTH directions.
    printf '%s,%s\n' \
        "$UE_IF" "$UE_IP" \
        >> "$HEALTHY_FILE_PATH"

    SELECTED=$((SELECTED + 1))

    echo "  HEALTHY: selected as UE $SELECTED"

    if (( SELECTED == UE_COUNT )); then
        break
    fi

done

echo
echo "========================================"
echo "Healthy UE selection complete"
echo "========================================"

echo "Candidates:         ${#UE_CANDIDATES[@]}"
echo "Selected Healthy:   $SELECTED"

if (( SELECTED < UE_COUNT )); then
    echo "ERROR: Not enough healthy UEs."
    echo "Requested: $UE_COUNT"
    echo "Found:     $SELECTED"
    echo
    echo "See:"
    echo "  $UNHEALTHY_FILE_PATH"
    exit 1
fi

echo
echo "========================================"
echo "Find list of (un)selected UEs"
echo "========================================"


echo "HEALTHY_FILE_PATH:   $HEALTHY_FILE_PATH"
echo "UNHEALTHY_FILE_PATH: $UNHEALTHY_FILE_PATH"

echo
echo "Healthy UEs:"
cat "$HEALTHY_FILE_PATH"

echo
echo "Unhealthy UEs:"
cat "$UNHEALTHY_FILE_PATH"

# ================================================
# OK.
# ================================================

echo
echo "========================================"
echo "Creating experiment directory"
echo "========================================"



mkdir -p "$RESULT_DIR"

echo "RESULT_DIR: $RESULT_DIR"

echo
echo "========================================"
echo "Creating permanent mapping of UEs, ports, interfaces"
echo "========================================"
# Create permanent mapping of UEs in this part. Experiment. 
# Create header:
printf '%s\n' \
'ue_number,interface,ue_ip,uplink_video_port,uplink_audio_port,downlink_video_port,downlink_audio_port' \
> "$RESULT_DIR/ue-map.csv"

# generate (deterministic) port for each of the UEs
# Print the file starting from line 2 until the end.
# | pipes output into next command
tail -n +2 "$HEALTHY_FILE_PATH" | 
while IFS=',' read -r UE_IF UE_IP; do

    # Example:
    # uesimtun68 -> 68
    # take value stored in UE_IF, 
    # removes uesimtun from the beginning, 
    # and stores whatever remains
    UE_NUMBER="${UE_IF#uesimtun}"

    BASE_PORT=$((10000 + UE_NUMBER * 4))

    UL_VIDEO_PORT=$BASE_PORT
    UL_AUDIO_PORT=$((BASE_PORT + 1))
    DL_VIDEO_PORT=$((BASE_PORT + 2))
    DL_AUDIO_PORT=$((BASE_PORT + 3))

    printf '%s,%s,%s,%d,%d,%d,%d\n' \
        "$UE_NUMBER" \
        "$UE_IF" \
        "$UE_IP" \
        "$UL_VIDEO_PORT" \
        "$UL_AUDIO_PORT" \
        "$DL_VIDEO_PORT" \
        "$DL_AUDIO_PORT" \
        >> "$RESULT_DIR/ue-map.csv"

done

UE_MAP_COUNT=$(tail -n +2 "$RESULT_DIR/ue-map.csv" | wc -l) 
echo "UEs written to mapping: $UE_MAP_COUNT" 
if (( UE_MAP_COUNT != UE_COUNT )); then 
	echo "ERROR: UE mapping contains $UE_MAP_COUNT UEs instead of $UE_COUNT." 
	exit 1 
fi


if [[ "$PROFILE" != "0" ]]; then
echo
echo "========================================"
echo "Generating Uplink profiles for indv. UEs"
echo "========================================"

# generate uplink profiles for indv. UEs
# clear and create profile
: > "$UPLINK_PROFILE_PATH"


# ================================================
# Uplink Profiles
# ================================================
tail -n +2 "$RESULT_DIR/ue-map.csv" |
while IFS=',' read -r \
    UE_NUMBER \
    UE_IF \
    UE_IP \
    UL_VIDEO_PORT \
    UL_AUDIO_PORT \
    DL_VIDEO_PORT \
    DL_AUDIO_PORT
do
    UL_FILE_PORT=$((21000 + UE_NUMBER))
    UL_VOICE_PORT=$((22000 + UE_NUMBER))

    export \
        DN_SERVER_IP \
        UE_IF \
        UE_IP \
        UL_VIDEO_PORT \
        UL_AUDIO_PORT \
        UL_FILE_PORT \
        UL_VOICE_PORT \
        TEST_DURATION_MS

    envsubst < "$UPLINK_TEMPLATE" \
        >> "$UPLINK_PROFILE_PATH"

    printf '\n' >> "$UPLINK_PROFILE_PATH"

done

sed -i '/^[[:space:]]*$/d' "$UPLINK_PROFILE_PATH"

# -------------------------------------------------------------------
# Verify generated uplink profile
# -------------------------------------------------------------------

NR_UPLINK_PROFILES=$(wc -l < "$UPLINK_PROFILE_PATH")
echo "NR_UPLINK_PROFILES:   $NR_UPLINK_PROFILES (teams call + VoIP + File Upload)"
echo "We expect UE_NUMBER*4 Uplink Profiles"
# EXPECTED_PROFILE_COUNT=$((UE_COUNT * 4))



echo
echo "========================================"
echo "Generating Downlink profiles for indv. UEs"
echo "========================================"

# generate downlink profiles for indv UEs
: > "$DOWNLINK_PROFILE_PATH"

# ================================================
# Downlink Profiles
# ================================================

tail -n +2 "$RESULT_DIR/ue-map.csv" |
while IFS=',' read -r \
    UE_NUMBER \
    UE_IF \
    UE_IP \
    UL_VIDEO_PORT \
    UL_AUDIO_PORT \
    DL_VIDEO_PORT \
    DL_AUDIO_PORT
do
    DL_FILE_PORT=$((20000 + UE_NUMBER))
    DL_VOICE_PORT=$((23000 + UE_NUMBER))

    export \
        UE_IP \
        DL_VIDEO_PORT \
        DL_AUDIO_PORT \
        DL_FILE_PORT \
        DL_VOICE_PORT \
        TEST_DURATION_MS

    envsubst < "$DOWNLINK_TEMPLATE" \
    >> "$DOWNLINK_PROFILE_PATH"

    printf '\n' >> "$DOWNLINK_PROFILE_PATH"

done

sed -i '/^[[:space:]]*$/d' "$DOWNLINK_PROFILE_PATH"

# -------------------------------------------------------------------
# Verify generated downlink profile
# -------------------------------------------------------------------

UL_FLOW_COUNT=$(wc -l < "$UPLINK_PROFILE_PATH")
DL_FLOW_COUNT=$(wc -l < "$DOWNLINK_PROFILE_PATH")

echo "Generated UL flows: $UL_FLOW_COUNT"
echo "Generated DL flows: $DL_FLOW_COUNT"

echo
echo "Generated downlink profile:"
cat "$DOWNLINK_PROFILE_PATH"

echo
echo "Generated uplink profile:"
cat "$UPLINK_PROFILE_PATH"


if (( UL_FLOW_COUNT == 0 || DL_FLOW_COUNT == 0 )); then
    echo "ERROR: No D-ITG flows generated."
    exit 1
fi

if grep -q -- '-t [0-9]*-a ' "$UPLINK_PROFILE_PATH" "$DOWNLINK_PROFILE_PATH"; then
    echo "ERROR: Malformed D-ITG profile: flows were concatenated."
    exit 1
fi

# ================================================
# OK.
# ================================================

echo
echo "========================================"
echo "Cleaning up old Recv Logs"
echo "========================================"

# stop old D-ITG receiver processes
sudo pkill -f '/usr/bin/ITGRecv' 2>/dev/null || true

# Remove old receiver logs from this experiment run
sudo rm -f \
    "$UL_RECEIVER_LOG" \
    "$DL_RECEIVER_LOG" \
    "$UL_RECEIVER_CONSOLE" \
    "$DL_RECEIVER_CONSOLE"

echo
echo "========================================"
echo "Starting up Uplink Receiver: START"
echo "========================================"

# Authenticate sudo once in the foreground
sudo -v

# Start uplink receiver inside dn-server (receiver on netflix side).
sudo -n ip netns exec "$DN_NS" \
    /usr/bin/ITGRecv \
    -a "$DN_SERVER_IP" \
    -l "$UL_RECEIVER_LOG" \
    > "$UL_RECEIVER_CONSOLE" 2>&1 &

# $! stores the PID of the background sudo wrapper, not necessarily the final ITGRecv PID
UL_RECEIVER_PID=$!
sleep 1
    
# confirm an ITGRecv process exists inside dn-server.
if ! sudo -n ip netns exec "$DN_NS" pgrep -a ITGRecv; then 
	echo "ERROR: Uplink ITGRecv is not running inside $DN_NS." 
	cat "$UL_RECEIVER_CONSOLE" 
	exit 1 
fi

# Then verify D-ITG signaling port 9000:
if ! sudo -n ip netns exec "$DN_NS" \
	ss -lntp | grep -q ':9000'
then
	echo "ERROR: Uplink ITGRecv is not listening on TCP port 9000." 
	cat "$UL_RECEIVER_CONSOLE" 
	exit 1 
fi	
	

# Inspect startup output:
cat "$UL_RECEIVER_CONSOLE"

echo
echo "Uplink receiver wrapper PID: $UL_RECEIVER_PID"

echo
echo "========================================"
echo "Starting up Uplink Receiver: FINISH SUCESS"
echo "========================================"

echo
echo "========================================"
echo "Starting up Downlink Receiver: START"
echo "========================================"

# Start downlink receiver on the host
sudo -n /usr/bin/ITGRecv \
    -l "$DL_RECEIVER_LOG" \
    > "$DL_RECEIVER_CONSOLE" 2>&1 &

# $! stores the PID of the background sudo wrapper, not necessarily the final ITGRecv PID
DL_RECEIVER_PID=$!

sleep 1

# Verify the downlink receiver is running on the host.
if ! pgrep -a ITGRecv | grep -q "$DL_RECEIVER_LOG"; then 
	echo "ERROR: Downlink ITGRecv is not running on the host." 
	cat "$DL_RECEIVER_CONSOLE" 
	exit 1 
fi


# Verify D-ITG signaling port 9000 on the host. 
if ! sudo -n ss -lntp | grep -q ':9000'; then 
	echo "ERROR: Downlink ITGRecv is not listening on TCP port 9000." 
	cat "$DL_RECEIVER_CONSOLE" 
	exit 1 
fi 

# Inspect startup output. 
cat "$DL_RECEIVER_CONSOLE" 

echo 

echo "Downlink receiver wrapper PID: $DL_RECEIVER_PID" 

echo 
echo "========================================" 
echo "Starting up Downlink Receiver: FINISH SUCCESS" 
echo "========================================"


echo 
echo "SUCCESS: Both D-ITG receivers are ready."

# =====================
# OK.
# =====================


# -------------------------------------------------------------------
# Configure D-ITG uplink signaling route
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Configuring D-ITG uplink signaling route"
echo "========================================"

# Use the first selected healthy UE for D-ITG's signaling connection.
# This signaling connection coordinates flow setup/teardown; 
# the actual audio/video data still uses each UE's own uesimtunX interface.

IFS=',' read -r \
    SIGNAL_UE_NUMBER \
    SIGNAL_IF \
    SIGNAL_IP \
    _ \
    < <(tail -n +2 "$RESULT_DIR/ue-map.csv" | head -n 1)

echo "Signaling UE:        UE$SIGNAL_UE_NUMBER"
echo "Signaling interface: $SIGNAL_IF"
echo "Signaling IP:        $SIGNAL_IP"

# replace = idempotent:
# an existing route is replaced instead of duplicated.
sudo ip route replace \
    "${DN_SERVER_IP}/32" \
    dev "$SIGNAL_IF" \
    src "$SIGNAL_IP"

echo "Selected route:"
ip route get "$DN_SERVER_IP"

if ! ip route get "$DN_SERVER_IP" \
    | grep -q "dev $SIGNAL_IF"
then
    echo "ERROR: D-ITG signaling route does not use $SIGNAL_IF."
    exit 1
fi

if ! ping \
    -I "$SIGNAL_IF" \
    -c 1 \
    -W 3 \
    "$DN_SERVER_IP" \
    >/dev/null 2>&1
then
    echo "ERROR: Signaling path to $DN_SERVER_IP does not work."
    exit 1
fi

echo "SUCCESS: D-ITG signaling route works."

# -------------------------------------------------------------------
# Prepare sender files
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Preparing D-ITG senders"
echo "========================================"

# Remove old sender logs.
# Makes repeated execution start with fresh sender results.
sudo rm -f \
    "$UL_SENDER_LOG" \
    "$DL_SENDER_LOG"

rm -f \
    "$UL_SENDER_CONSOLE" \
    "$DL_SENDER_CONSOLE"

echo "SUCCESS: Old sender logs removed."

# -------------------------------------------------------------------
# Verify generated profiles before starting traffic
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Checking generated Teams profiles"
echo "========================================"


UL_FLOW_COUNT=$(wc -l < "$UPLINK_PROFILE_PATH")
DL_FLOW_COUNT=$(wc -l < "$DOWNLINK_PROFILE_PATH")

#echo "Expected UL flows ((UE_COUNT * 4)):  $EXPECTED_PROFILE_COUNT"
echo "Generated UL flows:                  $UL_FLOW_COUNT"

#echo "Expected DL flows ((UE_COUNT * 4)): $EXPECTED_DOWNLINK_PROFILE_COUNT"
echo "Generated DL flows:                 $DL_FLOW_COUNT"


echo "SUCCESS: Both Teams profiles contain the expected number of flows."


# -------------------------------------------------------------------
# Final receiver readiness check
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Final receiver readiness check"
echo "========================================"

if ! sudo -n ip netns exec "$DN_NS" \
    ss -lnt | grep -q ':9000'
then
    echo "ERROR: Uplink receiver disappeared before traffic start."
    exit 1
fi

if ! sudo -n ss -lnt | grep -q ':9000'; then
    echo "ERROR: Downlink receiver disappeared before traffic start."
    exit 1
fi

echo "========================================"
echo "SUCCESS: Both receivers are ready immediately before traffic."
echo "========================================"

fi
# -------------------------------------------------------------------
# Start uplink sender
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Prometheus START Timestamp"
echo "========================================"

~/tools/d-itg/scripts/prom-export.sh start "$RESULT_DIR"
PROM_STARTED=1


PROM_START_TIME=$(TZ=Europe/Zurich date --iso-8601=seconds)

PROM_START_TIME_FORMATTED=$(date -d "$PROM_START_TIME" '+%d.%m.%y at %H:%M:%S')

echo "Prometheus start time: $PROM_START_TIME_FORMATTED"

# -------------------------------------------------------------------
# Zero D-ITG workload
# -------------------------------------------------------------------

if [[ "$PROFILE" == "0" ]]; then
    echo
    echo "========================================"
    echo "ZERO D-ITG WORKLOAD"
    echo "========================================"
    echo "No D-ITG traffic will be generated."
    echo "Collecting Prometheus metrics for $((TEST_DURATION_MS / 1000)) seconds."

    sleep "$((TEST_DURATION_MS / 1000))"

    echo "Zero-workload observation completed."

    ~/tools/d-itg/scripts/prom-export.sh stop "$RESULT_DIR"
    PROM_STARTED=0

    echo "Prometheus metrics exported."
    exit 0
fi


echo
echo "========================================"
echo "Starting Uplink Sender"
echo "========================================"

/usr/bin/ITGSend \
    "$UPLINK_PROFILE_PATH" \
    -l "$UL_SENDER_LOG" \
    > "$UL_SENDER_CONSOLE" 2>&1 &

UL_SENDER_PID=$!

echo "SUCCESS: Uplink sender launched."
echo "UL sender PID: $UL_SENDER_PID"
echo "UL flows:      $UL_FLOW_COUNT"


# -------------------------------------------------------------------
# Start downlink sender
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Starting Downlink Sender"
echo "========================================"

sudo -n ip netns exec "$DN_NS" \
    /usr/bin/ITGSend \
    "$DOWNLINK_PROFILE_PATH" \
    -l "$DL_SENDER_LOG" \
    > "$DL_SENDER_CONSOLE" 2>&1 &

DL_SENDER_PID=$!

echo "SUCCESS: Downlink sender launched."
echo "DL sender PID: $DL_SENDER_PID"
echo "DL flows:      $DL_FLOW_COUNT"


# -------------------------------------------------------------------
# Wait for BOTH senders
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Bidirectional Teams traffic running"
echo "========================================"

echo "Traffic duration per flow: $((TEST_DURATION_MS / 1000)) seconds"
echo "Waiting for both senders to finish..."

echo
echo "========================================"
echo "Optional manual sanity checks"
echo "Run these in ANOTHER terminal while traffic is running:"
echo "========================================"

echo
echo "# Check whether both ITGSend processes are still running:"
echo "pgrep -a ITGSend"

echo
echo "# Check uplink receiver inside dn-server:"
echo "sudo ip netns exec $DN_NS pgrep -a ITGRecv"

echo
echo "# Check downlink receiver on the host:"
echo "pgrep -a ITGRecv"

echo
echo "# Watch uplink receiver activity:"
echo "tail -f $UL_RECEIVER_CONSOLE"

echo
echo "# Watch downlink receiver activity:"
echo "tail -f $DL_RECEIVER_CONSOLE"

echo
echo "# Watch uplink sender output:"
echo "tail -f $UL_SENDER_CONSOLE"

echo
echo "# Watch downlink sender output:"
echo "tail -f $DL_SENDER_CONSOLE"

echo
echo "========================================"
echo "Script is now waiting for both senders..."
echo "========================================"


# Do not use kill -0 here.
# A sender that finished successfully is no longer alive.
# wait returns the actual exit status.
# wait blocks until the process finishes and returns its actual exit status.
# Do not use kill -0 as the final success check: a successfully completed
# sender is expected to have disappeared by the time we check its result.

if wait "$UL_SENDER_PID"; then
    UL_STATUS=0
else
    UL_STATUS=$?
fi

echo
echo "UL sender finished."
echo "UL sender exit status: $UL_STATUS"

if wait "$DL_SENDER_PID"; then
    DL_STATUS=0
else
    DL_STATUS=$?
fi

echo
echo "DL sender finished."
echo "DL sender exit status: $DL_STATUS"


echo
echo "========================================"
echo "Both sender waits completed. Prometheus STOP Timestamp"
echo "========================================"

~/tools/d-itg/scripts/prom-export.sh stop "$RESULT_DIR"
PROM_STARTED=0

PROM_STOP_TIME=$(TZ=Europe/Zurich date --iso-8601=seconds)

PROM_STOP_TIME_FORMATTED=$(date -d "$PROM_STOP_TIME" '+%d.%m.%y at %H:%M:%S')

echo "Prometheus start time: $PROM_START_TIME_FORMATTED"



echo
echo "========================================"
echo "Both sender waits completed. Checking results now."
echo "========================================"
echo "UL status: $UL_STATUS"
echo "DL status: $DL_STATUS"

if (( UL_STATUS == 0 )); then
    echo "SUCCESS: Uplink sender completed normally."
else
    echo "ERROR: Uplink sender failed."

    echo
    echo "===== Uplink sender console ====="
    cat "$UL_SENDER_CONSOLE" 2>/dev/null || true
fi


if (( DL_STATUS == 0 )); then
    echo "SUCCESS: Downlink sender completed normally."
else
    echo "ERROR: Downlink sender failed."

    echo
    echo "===== Downlink sender console ====="
    cat "$DL_SENDER_CONSOLE" 2>/dev/null || true
fi


if (( UL_STATUS != 0 || DL_STATUS != 0 )); then
    echo
    echo "ERROR: One or both D-ITG senders failed."
    exit 1
fi

echo "SUCCESS: Both D-ITG senders completed normally."

# -------------------------------------------------------------------
# Verify receivers survived the experiment
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Checking receivers after traffic"
echo "========================================"

if ! sudo -n ip netns exec "$DN_NS" \
    pgrep -f "/usr/bin/ITGRecv.*${UL_RECEIVER_LOG}" \
    >/dev/null
then
    echo "ERROR: Uplink receiver died during traffic."
    exit 1
fi

echo "SUCCESS: Uplink receiver survived the traffic run."


if ! pgrep -f "/usr/bin/ITGRecv.*${DL_RECEIVER_LOG}" \
    >/dev/null
then
    echo "ERROR: Downlink receiver died during traffic."
    exit 1
fi

echo "SUCCESS: Downlink receiver survived the traffic run."

# -------------------------------------------------------------------
# Verify all expected flows completed
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Checking completed receiver flows"
echo "========================================"

UL_UDP_FINISHED_COUNT=$(
    grep -c 'Finish on UDP port' \
        "$UL_RECEIVER_CONSOLE" \
        || true
)

UL_TCP_FINISHED_COUNT=$(
    grep -c 'Finish on TCP port' \
        "$UL_RECEIVER_CONSOLE" \
        || true
)

UL_FINISHED_COUNT=$((UL_UDP_FINISHED_COUNT + UL_TCP_FINISHED_COUNT))


DL_UDP_FINISHED_COUNT=$(
    grep -c 'Finish on UDP port' \
        "$DL_RECEIVER_CONSOLE" \
        || true
)

DL_TCP_FINISHED_COUNT=$(
    grep -c 'Finish on TCP port' \
        "$DL_RECEIVER_CONSOLE" \
        || true
)

DL_FINISHED_COUNT=$((DL_UDP_FINISHED_COUNT + DL_TCP_FINISHED_COUNT))

echo
echo "Expected UL flows:     $UL_FLOW_COUNT"
echo "Finished UL UDP flows: $UL_UDP_FINISHED_COUNT"
echo "Finished UL TCP flows: $UL_TCP_FINISHED_COUNT"
echo "Finished UL total:     $UL_FINISHED_COUNT"

echo
echo "Expected DL flows:     $DL_FLOW_COUNT"
echo "Finished DL UDP flows: $DL_UDP_FINISHED_COUNT"
echo "Finished DL TCP flows: $DL_TCP_FINISHED_COUNT"
echo "Finished DL total:     $DL_FINISHED_COUNT"


if (( UL_FINISHED_COUNT != UL_FLOW_COUNT )); then
    echo "ERROR: Not all uplink flows finished."
    exit 1
fi

echo "SUCCESS: All $UL_FLOW_COUNT uplink flows finished."


if (( DL_FINISHED_COUNT != DL_FLOW_COUNT )); then
    echo "ERROR: Not all downlink flows finished."
    exit 1
fi

echo "SUCCESS: All $DL_FLOW_COUNT downlink flows finished."


# -------------------------------------------------------------------
# Verify receiver logs contain traffic
# -------------------------------------------------------------------

echo
echo "========================================"
echo "Checking D-ITG receiver logs"
echo "========================================"

if [[ ! -s "$UL_RECEIVER_LOG" ]]; then
    echo "ERROR: Uplink receiver log is empty or missing."
    exit 1
fi

echo "SUCCESS: Uplink receiver log contains traffic data."


if [[ ! -s "$DL_RECEIVER_LOG" ]]; then
    echo "ERROR: Downlink receiver log is empty or missing."
    exit 1
fi

echo "SUCCESS: Downlink receiver log contains traffic data."

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------

echo
echo "========================================"
echo "D-ITG BIDIRECTIONAL TRAFFIC: SUCCESS"
echo "========================================"

echo "UEs:               $UE_COUNT"
echo "UL flows expected: $UL_FLOW_COUNT"
echo "UL flows finished: $UL_FINISHED_COUNT"
echo "DL flows expected: $DL_FLOW_COUNT"
echo "DL flows finished: $DL_FINISHED_COUNT"
echo "UL sender status:  $UL_STATUS"
echo "DL sender status:  $DL_STATUS"

echo
echo "SUCCESS: Both senders completed."
echo "SUCCESS: Both receivers survived."
echo "SUCCESS: All expected UL flows finished."
echo "SUCCESS: All expected DL flows finished."
echo "SUCCESS: Both receiver logs contain data."
echo "========================================"
echo "End of Experiment."
echo "========================================"
echo "Decode D-ITG Logs."
echo "========================================"

if [[ ! -d "$DITG_RAW_DIR" ]]; then
    echo "ERROR: D-ITG raw results directory does not exist:"
    echo "  $DITG_RAW_DIR"
    exit 1
fi

if ~/tools/d-itg/scripts/decode-d-itg-run.sh \
    "$DITG_RAW_DIR"
then
    echo "SUCCESS: D-ITG results decoded."
else
    DECODE_STATUS=$?

    echo "ERROR: D-ITG decoding failed."
    echo "Decode exit status: $DECODE_STATUS"
    exit 1
fi

echo "========================================"
echo "End of script."
echo "========================================"
