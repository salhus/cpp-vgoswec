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
| `capture_efficiency_VGM0.csv`  | Capture-efficiency sweep (T=2.0–7.0 s) for tuned VGM-0 |
| `capture_efficiency_VGM10.csv` | Capture-efficiency sweep (T=2.0–7.0 s) for tuned VGM-10 |
| `capture_efficiency_VGM20.csv` | Capture-efficiency sweep (T=2.0–7.0 s) for tuned VGM-20 |
| `capture_efficiency_VGM45.csv` | Capture-efficiency sweep (T=2.0–7.0 s) for tuned VGM-45 |
| `capture_efficiency_VGM90.csv` | Capture-efficiency sweep (T=2.0–7.0 s) for tuned VGM-90 |
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

Capture-efficiency CSV columns (`capture_efficiency_VGM*.csv`):

| Column | Description |
|--------|-------------|
| `T_s` | Wave period [s] |
| `omega_rads` | Angular frequency [rad/s], `2π/T` |
| `P_capture_W` | Steady-state mean absorbed power from tuned `exc_ff_pid` [W] (second half of run) |
| `P_opt_W` | Theoretical optimum power [W], blank when masked |
| `B55_Nmsrad` | De-normalized pitch radiation damping `B55` [N·m·s/rad] |
| `F_exc_Nm` | De-normalized pitch excitation moment magnitude `|F_exc|` for `A=0.014 m` [N·m] |
| `eta` | Capture efficiency `η = P_capture / P_opt`, blank when masked |
| `masked` | `true` where `B55 <= 1e-4` (reactive-limited / undefined `P_opt`, including non-positive `B55`) |

## Capture-efficiency method (tuned `exc_ff_pid`)

- Script: `scripts/capture_efficiency_sweep.py`
- Flaps: VGM-0/10/20/45/90 tuned configs from PR #31 (no gain retuning).
- Grid: `T = {2.0, 2.5, ..., 7.0} s` for all flaps.
- Capture numerator: run headless and average `power_w` over the second half of each run.
- Optimum denominator:
  - Body: `body1` (flap), ignore `body2`.
  - Pitch term: `body1/hydro_coeffs/radiation_damping/components/5_5`.
  - Excitation: `body1/hydro_coeffs/excitation/mag` at DOF5 (index 4), direction 0.
  - De-normalization: `B55 = B55_norm * rho * omega`, `|F_exc| = mag * rho * g * A`.
  - Wave amplitude fixed to `A = 0.014 m` (`H = 0.028 m`) for both sim and `P_opt`.
- Masking (essential): `B55 <= 1e-4` => `P_opt` undefined (reactive-limited, including non-positive `B55`), so `η` is not reported/plotted.
- VGM-0 caveat: near `T ≈ 4.8–6.0 s`, the pitch mode is reactive-limited (`B55` approaches zero), so resonance-band efficiency is physically undefined and is explicitly annotated in the VGM-0 figure.

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

# 4. Capture efficiency (all 5 flaps, T=2.0..7.0 s)
python3 scripts/capture_efficiency_sweep.py

# 5. Re-plot only from committed capture-efficiency CSVs
python3 scripts/capture_efficiency_sweep.py --plot-only
```
