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

## Hydrodynamics
- **Reference frame:** CG-referenced H5 files (`hydroData/vgoswec_{0,10,20,45,90}.h5`).
  Hinge-referenced files (prefixed `hinged_`) are NOT used by this benchmark.
- **P_opt:** computed from body1 pitch hydro (`radiation_damping/components/5_5`
  and `excitation/mag[dof=5,dir=0]`), de-normalized, at the same H = 0.05 m.
- **Mask rule:** points with `B55 <= 1e-04 N*m*s/rad` are treated as
  reactive-limited and omitted (P_opt undefined near resonance where B55 -> 0).

## Results summary
- Peak capture efficiency **eta ~ 8-13 %** across the five flap variants.
- Capture peaks track flap resonance: steeper flaps (higher omega_n) peak at
  shorter wave periods.
- **eta is amplitude-invariant** (both P_capture and P_opt scale as a^2), so the
  efficiency percentages are unchanged by the choice of H; only the absolute
  powers (P_capture ~ 0.49 W peak, P_opt ~ 1-2.7 W) scale with H^2.

## Known limitation
- `F_exc` is the raw un-hinge-referred pitch moment (`moment.y()` from
  `ExcitationForceProvider`). `alpha` is signed positive to paper over the
  resulting phase/sign mismatch. Consequence: the capture peak sits *below* each
  flap's resonance, and the controller would inject energy at short periods —
  which the passive-safety guard is designed to contain.
- Closing this gap (peak at resonance, higher capture) is the goal of the
  optimal-control follow-up: complex-conjugate (theoretical eta_max reference),
  then causal approximations (Korde) and constrained MPC (Ringwood).

## Reproduce
```bash
python3 scripts/capture_efficiency_sweep.py
# Regenerates analysis/capture_efficiency_VGM{0,10,20,45,90}.csv
# and analysis/figures/capture_efficiency_*.png at H = 0.05 m.
```
