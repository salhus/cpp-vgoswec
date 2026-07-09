#!/usr/bin/env bash
# sweep_kpkd_vgoswec.sh — Kp×Kd tuning sweep for all 5 VGOSWEC flap variants.
#
# For each flap, sweeps Kp ∈ {2,3,4,5,6} × Kd ∈ {0,0.5,1,2,3} (25 combos),
# with fixed alpha=11, Ki=5, passive_safe=true, clip_torque=10, u_min/u_max=±10.
# Objective: band-integrated capture (mean power summed across the flap's band).
# Hard constraints: passive-safe, 0% clamp, max|pitch|<0.8, non-injecting at band edges.
#
# Usage:
#   cd /path/to/cpp-vgoswec
#   bash scripts/sweep_kpkd_vgoswec.sh
#
# Output:
#   analysis/kpkd_sweep_VGM<angle>.csv  — per-flap swept grid
#   (Run scripts/plot_kpkd_surface.py afterwards to regenerate figures.)

set -euo pipefail

BIN="${BIN:-./build/demo_vgoswec}"
DURATION=171   # [s]  ≥ 40×T_res for all flaps; second half used for averages
OUTDIR="analysis"
mkdir -p "$OUTDIR"

if [[ ! -x "$BIN" ]]; then
  echo "[ERROR] Demo binary not found at: $BIN"
  echo "        Build first: cmake --build build -j\$(nproc)"
  exit 1
fi

# ---------------------------------------------------------------------------
# Per-flap sweep configuration
# ---------------------------------------------------------------------------
declare -A TEMPLATE_CONFIG=(
  [0]="config/vgoswec_0_exc_ff_pid.yaml"
  [10]="config/vgoswec_10_exc_ff_pid.yaml"
  [20]="config/vgoswec_20_exc_ff_pid.yaml"
  [45]="config/vgoswec_45_exc_ff_pid.yaml"
  [90]="config/vgoswec_90_exc_ff_pid.yaml"
)

# Sweep bands (low_T:res_T:high_T) — periods where band metrics are evaluated.
# Edges plus resonance plus one interior point.
declare -A SWEEP_PERIODS=(
  [0]="3.5 4.0 4.5 5.0 5.86 6.0 7.0"
  [10]="2.5 3.0 3.5 4.29 5.0 5.5 6.0"
  [20]="2.5 3.0 3.5 4.01 4.5 5.0 6.0"
  [45]="2.0 2.5 3.0 3.42 4.0 5.0 6.0"
  [90]="2.0 2.5 2.99 3.5 4.0 4.5 5.0"
)

# Band edges (used for non-injection constraint check)
declare -A BAND_LOW=(  [0]=3.5 [10]=2.5 [20]=2.5 [45]=2.0 [90]=2.0 )
declare -A BAND_HIGH=( [0]=7.0 [10]=6.0 [20]=6.0 [45]=6.0 [90]=5.0 )

KP_VALUES=(2 3 4 5 6)
KD_VALUES=(0 0.5 1 2 3)

# ---------------------------------------------------------------------------
# Python analysis helper (inline)
# ---------------------------------------------------------------------------
ANALYZE_PY=$(cat <<'PYEOF'
import csv, sys, numpy as np

csv_file, vel_col, tau_col, pitch_col, pw_col = sys.argv[1:]
rows = list(csv.DictReader(open(csv_file)))
n = len(rows)
s = slice(n // 2, n)   # second half only

vel   = np.array([float(r[vel_col])   for r in rows])[s]
tau   = np.array([float(r[tau_col])   for r in rows])[s]
pitch = np.array([float(r[pitch_col]) for r in rows])[s]
pw    = np.array([float(r[pw_col])    for r in rows])[s]

mean_p   = float(pw.mean())
max_pitch = float(np.abs(pitch).max())
max_tau  = float(np.abs(tau).max())
clamp_frac = float(np.mean(np.abs(tau) >= 9.8))
corr     = float(np.corrcoef(tau, vel)[0, 1]) if vel.std() > 1e-12 and tau.std() > 1e-12 else 0.0

print(f"{mean_p:.6e},{max_pitch:.6f},{max_tau:.6f},{clamp_frac:.4f},{corr:.6f}")
PYEOF
)

# ---------------------------------------------------------------------------
# Sweep loop
# ---------------------------------------------------------------------------
for ANGLE in 0 10 20 45 90; do
  TMPL="${TEMPLATE_CONFIG[$ANGLE]}"
  PERIODS="${SWEEP_PERIODS[$ANGLE]}"
  T_LOW="${BAND_LOW[$ANGLE]}"
  T_HIGH="${BAND_HIGH[$ANGLE]}"
  CSV_OUT="$OUTDIR/kpkd_sweep_VGM${ANGLE}.csv"

  echo ""
  echo "==================================================================="
  echo " VGM-${ANGLE}   (band ${T_LOW}–${T_HIGH} s)"
  echo "==================================================================="

  # Header
  echo "flap_angle,kp,kd,period_s,mean_power_w,max_pitch_rad,max_tau_nm,clamp_frac,corr_tau_vel,passive_safe,no_clamp,pitch_ok,edge_ok" > "$CSV_OUT"

  SCRATCH_CFG="/tmp/vgoswec_sweep_scratch.yaml"

  for KP in "${KP_VALUES[@]}"; do
    for KD in "${KD_VALUES[@]}"; do
      # Build scratch config from template
      cp "$TMPL" "$SCRATCH_CFG"
      # Set gains
      sed -i "s/kp: .*/kp: ${KP}/" "$SCRATCH_CFG"
      sed -i "s/ki: .*/ki: 5.0/" "$SCRATCH_CFG"
      sed -i "s/kd: .*/kd: ${KD}/" "$SCRATCH_CFG"
      sed -i "s/alpha: .*/alpha: 11.0/" "$SCRATCH_CFG"
      sed -i "s/clip_torque: .*/clip_torque: 10.0/" "$SCRATCH_CFG"
      sed -i "s/u_min: .*/u_min: -10.0/" "$SCRATCH_CFG"
      sed -i "s/u_max: .*/u_max: 10.0/" "$SCRATCH_CFG"
      sed -i "s/passive_safe: .*/passive_safe: true/" "$SCRATCH_CFG"
      sed -i "s/duration: .*/duration: ${DURATION}.0/" "$SCRATCH_CFG"

      # Track per-combo aggregates for band-integrated capture
      BAND_POWER_SUM=0
      BAND_PERIODS=0
      COMBO_PASS=1

      for T in $PERIODS; do
        sed -i "s/period: .*/period: ${T}/" "$SCRATCH_CFG"

        "$BIN" --config "$SCRATCH_CFG" --no-viz --wave-period "$T" --duration "$DURATION" \
          > /dev/null 2>&1 || true

        RESULT_CSV="output/vgoswec_sweep_scratch_results.csv"
        if [[ ! -f "$RESULT_CSV" ]]; then
          # Try generic output name
          RESULT_CSV=$(ls output/*scratch*results.csv 2>/dev/null | head -1 || echo "")
        fi
        if [[ -z "$RESULT_CSV" || ! -f "$RESULT_CSV" ]]; then
          echo "  [WARN] No output CSV found for VGM-${ANGLE} kp=${KP} kd=${KD} T=${T}; skipping"
          continue
        fi

        STATS=$(python3 -c "$ANALYZE_PY" "$RESULT_CSV" \
          flap_pitch_vel_rads pto_torque_nm flap_pitch_rad power_w 2>/dev/null || echo "nan,nan,nan,nan,nan")

        IFS=',' read -r MEAN_P MAX_PITCH MAX_TAU CLAMP_FRAC CORR <<< "$STATS"

        # Constraint flags
        PASSIVE_SAFE=1;  [[ $(python3 -c "print(1 if float('$MEAN_P')>=0 else 0)" 2>/dev/null || echo 0) == "1" ]] || PASSIVE_SAFE=0
        NO_CLAMP=1;      [[ $(python3 -c "print(1 if float('$CLAMP_FRAC')==0 else 0)" 2>/dev/null || echo 0) == "1" ]] || NO_CLAMP=0
        PITCH_OK=1;      [[ $(python3 -c "print(1 if float('$MAX_PITCH')<0.8 else 0)" 2>/dev/null || echo 0) == "1" ]] || PITCH_OK=0

        # Edge check: corr < 0 at band edges
        EDGE_OK=1
        if [[ "$T" == "$T_LOW" || "$T" == "$T_HIGH" ]]; then
          [[ $(python3 -c "print(1 if float('$CORR')<0 else 0)" 2>/dev/null || echo 0) == "1" ]] || EDGE_OK=0
        fi

        echo "${ANGLE},${KP},${KD},${T},${MEAN_P},${MAX_PITCH},${MAX_TAU},${CLAMP_FRAC},${CORR},${PASSIVE_SAFE},${NO_CLAMP},${PITCH_OK},${EDGE_OK}" >> "$CSV_OUT"

        # Accumulate band-integrated capture
        P_F=$(python3 -c "print(float('$MEAN_P'))" 2>/dev/null || echo 0)
        BAND_POWER_SUM=$(python3 -c "print($BAND_POWER_SUM + max(0.0, $P_F))" 2>/dev/null || echo 0)
        BAND_PERIODS=$((BAND_PERIODS + 1))

        [[ $PASSIVE_SAFE -eq 1 && $NO_CLAMP -eq 1 && $PITCH_OK -eq 1 ]] || COMBO_PASS=0
      done

      BAND_AVG=$(python3 -c "print($BAND_POWER_SUM / max(1, $BAND_PERIODS))" 2>/dev/null || echo 0)
      echo "  kp=${KP}  kd=${KD}  band_avg_P=${BAND_AVG}W  constraints_ok=${COMBO_PASS}"
    done
  done

  echo ""
  echo "Saved: $CSV_OUT"
done

rm -f /tmp/vgoswec_sweep_scratch.yaml

echo ""
echo "Sweep complete. Run scripts/plot_kpkd_surface.py to regenerate figures."
