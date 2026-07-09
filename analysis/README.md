# analysis/README.md
# Kp×Kd Sweep Results for VGOSWEC exc_ff_pid Controller

> **⚠ Data notice:** The CSV files in this directory are **illustrative synthetic data**
> derived from a physics-based model calibrated to the empirical α=11 sweep results.
> They faithfully represent the constraint structure and qualitative optimality landscape
> (Kp=4, Kd=1 or 2 per flap), but are **not from actual Chrono/SEA-Stack simulation runs**.
> To replace with real simulation results, build the demo and run
> `bash scripts/sweep_kpkd_vgoswec.sh` (see §Regenerating from scratch below).

## Contents

| File | Description |
|------|-------------|
| `kpkd_sweep_VGM0.csv`  | Kp×Kd sweep grid for VGM-0  (band 3.5–7.0 s) |
| `kpkd_sweep_VGM10.csv` | Kp×Kd sweep grid for VGM-10 (band 2.5–6.0 s) |
| `kpkd_sweep_VGM20.csv` | Kp×Kd sweep grid for VGM-20 (band 2.5–6.0 s) |
| `kpkd_sweep_VGM45.csv` | Kp×Kd sweep grid for VGM-45 (band 2.0–6.0 s) |
| `kpkd_sweep_VGM90.csv` | Kp×Kd sweep grid for VGM-90 (band 2.0–5.0 s) |
| `figures/`             | Journal-quality 3-D surface plots (generated) |

## CSV columns

| Column | Description |
|--------|-------------|
| `flap_angle` | Flap angle [°] |
| `kp` | Proportional gain Kp [N·m/(rad/s)] |
| `kd` | Derivative gain Kd [N·m·s/(rad/s)] |
| `period_s` | Wave period T [s] |
| `mean_power_w` | Mean absorbed power over second half of run [W] |
| `max_pitch_rad` | Maximum \|pitch\| [rad] |
| `max_tau_nm` | Maximum \|PTO torque\| [N·m] |
| `clamp_frac` | Fraction of timesteps where \|tau\| ≥ 9.8 N·m |
| `corr_tau_vel` | corr(tau, theta_dot) — negative = dissipative |
| `passive_safe` | 1 if mean_power ≥ 0 |
| `no_clamp` | 1 if clamp_frac = 0 |
| `pitch_ok` | 1 if max_pitch < 0.8 rad |
| `edge_ok` | 1 if corr_tau_vel < 0 (at band-edge periods only; 1 elsewhere) |

## Fixed parameters

- `alpha = 11` (empirically universal across all 5 flaps)
- `Ki = 5.0` (fixed; bounded by u_min/u_max ±10)
- `passive_safe = true` (guard active)
- `clip_torque = 10.0` N·m
- `u_min = -10.0`, `u_max = 10.0` N·m (PID clamp)

## Regenerating from scratch

```bash
# 1. Build the demo
cmake --build build -j$(nproc)

# 2. Run the full sweep (~125 simulations × 5 flaps)
bash scripts/sweep_kpkd_vgoswec.sh

# 3. Regenerate figures
python3 scripts/plot_kpkd_surface.py
```

