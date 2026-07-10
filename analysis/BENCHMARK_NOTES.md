# Capture-efficiency benchmark — exc_ff_pid (frozen state)

This document records the frozen benchmark configuration for the
`exc_ff_pid` controller capture-efficiency sweep. Treat these values as the
single source of truth; the sweep script and the per-flap configs must agree.

## Controller
- **Type:** `exc_ff_pid` — stabilized velocity-tracking absorber with a
  passive-safety guard (`passive_safe: true`).
- **Law:** `tau = clamp(-B_ctrl * theta_dot + PID_vel(alpha * F_exc,pitch(t) - theta_dot), -clip, clip)`
- **Passive-safety guard:** if `tau * theta_dot > 0` (energy injection), the
  command is replaced by the dissipative floor `-B_ctrl * theta_dot`.

## Sea state (single source of truth)
- **Wave type:** regular
- **Wave height:** **H = 0.05 m** (amplitude a = H/2 = 0.025 m)
- This value MUST match `WAVE_HEIGHT_M` in `scripts/capture_efficiency_sweep.py`
  and `wave.height` in every `config/vgoswec_*_exc_ff_pid.yaml`.

## Frequency band (wave-tank scale)
- **Sweep grid:** uniform in frequency, **omega = 4.0 .. 12.0 rad/s** (0.5 rad/s
  steps) => **T ~ 0.52 .. 1.57 s**. Set by `OMEGA_GRID` in the sweep script.
- **Rationale:** this is a wave-tank-scale device. The physically active pitch
  radiation-damping band is omega ~ 6-11 rad/s (B55 peaks near omega ~ 9.5-10
  rad/s; see the BEMRosetta B55 1.pitch plot). The H5 files carry coefficients
  over omega = 0.05 .. 15 rad/s, so the 4-12 band requires no extrapolation.
- The low-frequency edge (omega < 4 rad/s) is dropped: B55 there is near the
  numerical floor and a few points dip below the mask threshold.

## Hydrodynamics
- **Reference frame:** CG-referenced H5 files (`hydroData/vgoswec_{0,10,20,45,90}.h5`).
  Hinge-referenced files (prefixed `hinged_`) are NOT used by this benchmark.
- **P_opt (Budal / Falnes bound):** `P_opt = |F_exc|^2 / (8 * B55)`, computed from
  body1 pitch hydro (`radiation_damping/components/5_5` and
  `excitation/mag[dof=5,dir=0]`), at H = 0.05 m. This is the single-DOF optimal for
  a **free-flap (CG-referenced) pitch mode** — NOT the hinge-referenced flap optimum.
- **De-normalization (WEC-Sim / BEMIO convention, rho and g read from each H5,
  rho = 1000, g = 9.80665):**
  - `B55 = B55_norm * rho * omega`  [N*m/(rad/s)]  (peak ~3, matches BEMRosetta)
  - `F_exc = F_exc_norm * rho * g * a`  [N*m]  (per-amplitude ~174 N*m/m, matches BEMRosetta)
- **Mask rule:** points with `B55 <= 1e-04 N*m*s/rad` are treated as
  reactive-limited and omitted. On the 4-12 band all five flaps clear this
  threshold, so no points are masked.

## Results summary
- **Peak capture efficiency:**
  - **VGM-0: eta ~ 34 %** at T ~ 0.84 s (omega ~ 7.5 rad/s) — the flat flap is the
    strongest absorber (largest pitch excitation moment).
  - **VGM-10/20/45/90: eta ~ 7-9 %**, peaking at shorter periods (T ~ 0.55-0.7 s,
    omega ~ 9-11 rad/s).
- eta tracks the controller's P_capture peak; P_opt decreases monotonically with
  increasing T across this band, so eta is shaped primarily by P_capture.
- **eta is amplitude-invariant** (both P_capture and P_opt scale as a^2); the
  percentages are unchanged by H. Only absolute powers scale with H^2
  (P_capture ~ 0.26 W peak, P_opt ~ 0.3-2.7 W at H = 0.05 m).

## Caveats
- **eta-peak resolution sensitivity:** the VGM-0 eta peak near omega ~ 7.5 rad/s
  sits on the steep leading edge of the B55 ramp (B55 roughly doubles between
  omega = 7.0 and 7.5). At the 0.5 rad/s grid spacing this edge is under-resolved,
  so the exact peak height (~34 %) is grid-sensitive; the shape and location are
  robust. Refining the grid near omega ~ 7 would pin the peak value.
- **CG- vs hinge-referenced:** P_opt/eta here use CG-referenced free-flap pitch
  hydro, not the hinge-referenced flap. `F_exc` is the raw un-hinge-referred pitch
  moment and `alpha` is signed positive to paper over the resulting phase/sign
  mismatch.

## Follow-up (next milestone)
- Recompute P_opt and eta from the **hinge-referenced** coefficients
  (`hinged_vgoswec_*.h5`), removing the `alpha` fudge.
- Implement true complex-conjugate control (theoretical eta_max reference) with
  hinge-referenced K_r / B_r, then causal approximations (Korde) and constrained
  MPC (Ringwood). Resonance markers return once resonance is defined consistently
  in the hinge frame.

## Reproduce
```bash
python3 scripts/capture_efficiency_sweep.py
# Regenerates analysis/passive_guarded/capture_efficiency_VGM{0,10,20,45,90}.csv
# and analysis/passive_guarded/figures/capture_efficiency_*.png
# over omega = 4..12 rad/s at H = 0.05 m.
```