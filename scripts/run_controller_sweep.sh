#!/usr/bin/env bash
set -euo pipefail

CONFIG="config/vgoswec_45_passive.yaml"
BIN="./build/demo_vgoswec"
OUTDIR="output/sweeps/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR"

controllers=(passive opt_passive cc exc_ff_pid)

echo "[1/3] Building..."
cmake --build build -j"$(nproc)"

echo "[2/3] Running controller sweep..."
for c in "${controllers[@]}"; do
  echo "  -> $c"
  "$BIN" --config "$CONFIG" --no-viz --controller "$c"
  cp output/vgoswec_45_results.csv "$OUTDIR/${c}.csv"
done

echo "[3/3] Summarizing..."
python3 - "$OUTDIR" <<'PY'
import csv, os, sys, math
outdir = sys.argv[1]
controllers = ["passive","opt_passive","cc","exc_ff_pid"]

def summarize(path):
    rows=0
    t_end=float("nan")
    max_pitch=0.0
    max_vel=0.0
    sum_power=0.0
    sum_tau=0.0
    with open(path, newline="") as fh:
        r=csv.DictReader(fh)
        for row in r:
            rows += 1
            t=float(row["time_s"]); t_end=t
            pitch=abs(float(row["flap_pitch_rad"]))
            vel=abs(float(row["flap_pitch_vel_rads"]))
            p=float(row["power_w"])
            tau=float(row["pto_torque_nm"])
            if pitch>max_pitch: max_pitch=pitch
            if vel>max_vel: max_vel=vel
            sum_power += p
            sum_tau += tau
    mean_power = sum_power/rows if rows else float("nan")
    mean_tau = sum_tau/rows if rows else float("nan")
    return rows, t_end, max_pitch, max_vel, mean_power, mean_tau

print("\nController Sweep Summary")
print("outdir:", outdir)
print("-"*108)
print(f"{'controller':<12} {'rows':>8} {'t_end':>8} {'max|pitch|[rad]':>18} {'max|vel|[rad/s]':>18} {'mean power [W]':>16} {'mean tau [Nm]':>16}")
print("-"*108)

best = None
for c in controllers:
    p = os.path.join(outdir, f"{c}.csv")
    if not os.path.exists(p):
        print(f"{c:<12} MISSING")
        continue
    rows,t_end,max_pitch,max_vel,mean_power,mean_tau = summarize(p)
    print(f"{c:<12} {rows:8d} {t_end:8.3f} {max_pitch:18.6f} {max_vel:18.6f} {mean_power:16.6e} {mean_tau:16.6e}")
    if best is None or mean_power > best[1]:
        best = (c, mean_power)

print("-"*108)
if best:
    print(f"Best mean power: {best[0]} ({best[1]:.6e} W)")
print()
PY

echo "Done. CSVs + summary source in: $OUTDIR"