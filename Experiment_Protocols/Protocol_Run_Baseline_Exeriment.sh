# =================================================
# [1/8] Set up susbcribers in open5gs
# =================================================
# check current number in mongo db

MONGO_POD=$(kubectl -n open5gs get pods \
  -l app.kubernetes.io/name=mongodb \
  -o jsonpath='{.items[0].metadata.name}')

kubectl -n open5gs exec "$MONGO_POD" -- \
  mongosh --quiet open5gs --eval 'db.subscribers.countDocuments({})'

# Create subscribers if needed. They will be saved in the mongodb.
~/tools/d-itg/scripts/create-open5gs-subscribers.sh 50


# =================================================
# [2/8] Start gNB.
# =================================================
# Open a separate running terminal.

tmux new -s ueransim-gnb
tmux ls
tmux -t attach ueransim-gnb

cd /home/<user>/UERANSIM

sudo ./build/nr-gnb \
  -c ./config/open5gs-gnb.yaml

# =================================================
# [3/8] Start UERANSIM
# =================================================
# Open another separate running terminal.
tmux new -s ueransim-ue
tmux ls
tmux -t attach ueransim-ue

cd ~/UERANSIM

sudo ./build/nr-ue \
  -c ./config/open5gs-ue.yaml \
  -n 30 \
  -t 1000

# Wait a bit, until all UEs were able to register. This command can be helpful to see how many users were registered.
ip -br -4 addr show | grep '^uesimtun' | wc -l


# =================================================
# [4/8] Check uplink and downlink
# =================================================
# In a third, new terminal:
# Downlink
sudo ~/tools/d-itg/scripts/open5gs-dn-link.sh ensure

# Uplink (tests downlink for each UE we created)
sudo ~/tools/d-itg/scripts/check-ue-paths.sh check


# =================================================
# [5/8] Set the correct profile workload
# =================================================

# in run-mixed-workloads-dynamic-profiles.sh you can change the profile to the according workload.
# Approx. on line 48
~/tools/d-itg/scripts/run-mixed-workloads-dynamic-profiles.sh


# =================================================
# [6/8] Run D-ITG experiment. Set Variables and start the experiment.
# =================================================
# it takes 2-3 minutes to finished.
HONEY_DENSITY=0
RUN_NR=1
UE_COUNT=10
DURATION_MS=120000
LOAD=100MB

NS="open5gs"

echo "$HONEY_DENSITY"

RUN_DIR=~/experiments/baseline-mixed-workloads_"${UE_COUNT}"-ues/density"${HONEY_DENSITY}"/"${LOAD}"/run"${RUN_NR}"
echo "$RUN_DIR"

DEPLOYMENT=$(kubectl -n "$NS" get deployment \
  -l app.kubernetes.io/name=udr \
  -o jsonpath='{.items[0].metadata.name}')

echo "$DEPLOYMENT"


~/tools/d-itg/scripts/run-mixed-workloads-dynamic-profiles.sh \
    "$UE_COUNT" \
    "$RUN_NR" \
    "$DURATION_MS" \
    "$RUN_DIR"


# =================================================
# [7/8] Shutdown UERANSIM and gNB
# =================================================
./shutdown-UERANSIM.sh



# =================================================
# [8/8] Remove subscribers from the MongoDB.
# =================================================
./delete-subscribers.sh 30

