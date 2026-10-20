# Create Plots from DITG Experiments (percentage)

source evaluate-exp-venv/bin/activate

python3 ./experiments/analysis-ditg/evaluate_ditg_data_percentage.py \
  --root ./experiments/baseline-mixed-workloads_10-ues \
  --output ./experiments/analysis-ditg/with0-plots-good-percentage \
  --duration 120

# Combine plots by workloads

python3 ./experiments/analysis-ditg/combine_plots.py \
  --root ./experiments/analysis-ditg/with0-plots-good-percentage


# Evaluate Campaigns

source evaluate-exp-venv/bin/activate

for RUN_DIR in ./experiments/<MA_Campaign>/density-*/run*/; do
  echo "Processing: $RUN_DIR"

  python3 ./experiments/analysis-campaigns/honeyassets_report.py \
    --events     "$RUN_DIR/caldera_event-logs.json" \
    --manifest   "$RUN_DIR/honey-assets-manifest.csv" \
    --honeyfiles "$RUN_DIR/honeyfiles.csv" \
    --discovery  "$RUN_DIR/caldera-discovery.log" \
    --tetragon   "$RUN_DIR/tetragon-udr.log" \
    --alerts     "$RUN_DIR/alertmanager-alerts.json" \
    --out        "$RUN_DIR/analysis_plots"
done


# Create plots combining all densities

source evaluate-exp-venv/bin/activate

python3 ./experiments/analysis-campaigns/honeyassets_report_all_densities.py \
    --campaigns ./experiments/<MA_Campaign> \
    --out ./experiments/analysis-campaigns/all-density-Honeytypes-plots