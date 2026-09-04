#!/usr/bin/env bash
set -euo pipefail

# Accept the six formal-shaped opaque arguments used by the launcher probe.
[[ "$#" -eq 6 ]]

"/usr/bin/python3.8" "$A08_PROBE_RESPONSIVE_CHILD" \
  "$A08_ITEM_OUTPUT_DIR/roscore_inherited_mask_probe.json" &
ROSCORE_PID="$!"
"$VINS_NODE_BIN" \
  "$A08_WORKSPACE_LINK/vins_aqualoc_archaeo_external.yaml" \
  >"$A08_ITEM_OUTPUT_DIR/wrapper_probe.log" 2>&1 &
VINS_PID="$!"

for _ in $(seq 1 250); do
  if [[ -f "$A08_ITEM_OUTPUT_DIR/roscore_inherited_mask_probe.json" && \
        -f "$A08_VINS_LIFECYCLE_START_MANIFEST" ]]; then
    break
  fi
  sleep 0.02
done
[[ -f "$A08_ITEM_OUTPUT_DIR/roscore_inherited_mask_probe.json" ]]
[[ -f "$A08_VINS_LIFECYCLE_START_MANIFEST" ]]

kill "$VINS_PID"
wait "$VINS_PID"
kill "$ROSCORE_PID"
wait "$ROSCORE_PID"
