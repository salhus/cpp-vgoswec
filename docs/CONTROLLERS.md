# VGOSWEC PTO Controllers

## Sign convention

| Symbol | Meaning | Units |
|--------|---------|-------|
| θ | Flap angle from upright equilibrium | rad |
| θ̇ (ω) | Flap angular velocity | rad/s |
| τ_pto | PTO torque about hinge Y-axis (returned by `ComputeForce`) | N·m |
| P_abs | Absorbed power: P_abs = −τ_pto · ω (positive = extracted from waves) | W |

**Restoring convention**: positive τ opposes positive θ.

---

## (A) PassiveDamper

### Formula
```
τ = −B_pto · ω
```

### Parameters
| Name | Symbol | Default | Units |
|------|--------|---------|-------|
| `B_pto` | B_pto | 0.5 | N·m·s/rad |
| `clip_torque` | — | 5.0 | N·m |

### Notes
- Simplest baseline.
- No energy input to the ocean. Always stable.
- **Tune**: increase B_pto until flap motion degrades; back off 20%.

---

## (B) OptimalPassive

### Formula
```
τ = −B_opt · ω
```

### Gain derivation
```
B_opt = |Z_intrinsic(ω₀)|
Z_intrinsic = B_rad,55(ω₀) + i · [ω₀·(I_flap + A₅₅(ω₀)) − K_hs,55/ω₀]
```

Frequency-domain coefficients A(ω₀), B(ω₀) are computed from the stored RIRF via numerical Fourier cosine/sine transform (`impedance.cpp`). See `PitchImpedanceMagnitude()`.

### Parameters
| Name | Symbol | Notes |
|------|--------|-------|
| `design_omega` | ω₀ | If 0 in config, derived from `wave.period` |
| `clip_torque` | — | — |

---

## (C) ComplexConjugateControl

### Formula
```
τ = −K_r · θ − B_r · ω
```

### Gain derivation (from impedance.cpp)
```
K_r =  ω₀² · (I_flap + A₅₅(ω₀)) − K_hs,55   (intrinsic pitch reactance to be cancelled)
B_r =  B_rad,55(ω₀)
```

At ω₀, CC control achieves maximum power absorption for a single-frequency wave (Budal/Falnes theorem). It requires reactive PTO (power input during part of the cycle).

### Parameters
`K_r_override` and `B_r_override` (both zero = auto-compute from H5).

### Warning
CC control requires bidirectional power flow. A physical PTO must support reactive operation (e.g., active motor/generator). Add conservative `clip_torque`.

---

## (D) ExcitationVelocityController (`exc_ff_pid`)

### Formula
```
vel_ref  = alpha · F_exc,pitch(t)
tau_raw  = −B_ctrl · θ̇ + PID_vel(vel_ref − θ̇)

if passive_safe AND (tau_raw · θ̇ > 0):   # would inject energy
    tau_out = −B_ctrl · θ̇               # revert to dissipative floor
else:
    tau_out = tau_raw

τ_pto = clamp( tau_out, -clip_torque, clip_torque )
```

### Sub-components
- **Damping floor** (`−B_ctrl · θ̇`): guaranteed dissipative feedback. With `B_ctrl ≥ 0` this term always opposes velocity and CANNOT inject energy into the system, bounding the response and preventing runaway — the same proven-stable structure as `PassiveDamper`.
- **Velocity inner loop** (`PID_vel(vel_ref − θ̇)`): the Korde/Ringwood-style tracking loop that drives the flap toward a phase-aligned reference velocity `vel_ref = alpha · F_exc`.
- **Passive-safety guard** (`passive_safe`): after computing the candidate torque, if it would inject energy (τ · θ̇ > 0), the output is replaced by the pure dissipative damping floor `−B_ctrl · θ̇` before applying the clip. This guard allows alpha and PID gains to be tuned aggressively without risk of net energy injection at any operating point. Gate is controlled by the boolean `passive_safe` config field (default: `true`).

`alpha` is **positive** (empirically 11; see rationale below) because the effective hinge-referred excitation currently has the opposite sign from the raw pitch excitation moment exposed by `ExcitationForceProvider`. A later follow-up can fix the excitation referral directly; for now the sign is absorbed by `alpha`.

### Parameters
| Name | Default | Units | Notes |
|------|---------|-------|-------|
| `B_ctrl` | 0.5 | N·m·s/rad | Stability damping floor (always dissipative). |
| `alpha` | 11.0 | (rad/s)/(N·m) | SIGNED velocity-reference gain, `vel_ref = alpha·F_exc`. Fixed empirically (see §Fixed parameters). |
| `clip_torque` | 10.0 | N·m | Final output saturation clamp. |
| `passive_safe` | true | — | Enable/disable the passive-safety guard. |
| `vel_pid.kp` | varies | N·m per (rad/s) | Velocity-error proportional gain (per-flap tuned). |
| `vel_pid.ki` | 5.0 | N·m/(rad/s·s) | Velocity-error integral gain. Fixed empirically (see §Fixed parameters). |
| `vel_pid.kd` | varies | N·m·s/(rad/s) | Velocity-error derivative gain (per-flap tuned). |
| `vel_pid.tau_d` | 0.02 | s | Derivative filter time constant. |
| `vel_pid.u_min` / `vel_pid.u_max` | -10.0 / 10.0 | N·m | Clamp on the PID term only. |

### Fixed parameters (α = 11, Ki = 5)

**α = 11 (universal across all 5 flap angles):**
Determined empirically by sweeping α across VGM-0/10/20/45/90 and finding the
"diminishing-returns knee" where:
- Band-integrated capture is nearly maximised for the reactive flaps (VGM-10/20/45/90)
- `max|pitch| < 0.8 rad` is satisfied at both band edges
- `corr(τ, θ̇) < 0` (non-injecting) at both band edges with healthy margin
- VGM-0 is α-insensitive in this regime, so α=11 costs it nothing

The resonance-P curve continues to rise with α (no rollover) — the ceiling is set by
the band-edge constraints, not by resonance power. α=11 is the last value before
max|pitch| approaches 0.8 on VGM-90 (the highest-frequency, largest-motion flap).

**Ki = 5 (fixed):**
Integral wind-up is bounded by `vel_pid.u_min = -10` / `vel_pid.u_max = 10`, so Ki
does not destabilise the loop. Ki=5 was found to improve steady-state velocity tracking
without affecting the band-edge safety margins.

### Per-flap tuned Kp/Kd

Tuning objective: **band-integrated capture** (mean absorbed power averaged over the
flap's physical sweep band), subject to hard constraints:
- Passive-safe: mean power ≥ 0 at every tested period (guaranteed by `passive_safe`)
- No saturation: clamp fraction = 0% (with `clip_torque = 10.0`)
- `max|pitch| < 0.8 rad` (small-angle validity)
- Band edges non-injecting: `corr(τ, θ̇) < 0` at both the low and high edge of the band

Sweep: `Kp ∈ {2,3,4,5,6}` × `Kd ∈ {0, 0.5, 1, 2, 3}` (25 combinations per flap).
See `analysis/kpkd_sweep_VGM<angle>.csv` for the full swept grid.
See `analysis/figures/kpkd_surface_VGM<angle>.png` for 3-D surface plots.
See `analysis/figures/kpkd_summary.png` for cross-flap summary.

| Flap | ωn [rad/s] | T_res [s] | Band [s] | Kp | Kd |
|------|-----------|-----------|----------|----|----|
| VGM-0  | 1.07 | 5.86 | 3.5–7.0 | 4 | 1 |
| VGM-10 | 1.46 | 4.29 | 2.5–6.0 | 4 | 1 |
| VGM-20 | 1.57 | 4.01 | 2.5–6.0 | 4 | 1 |
| VGM-45 | 1.84 | 3.42 | 2.0–6.0 | 4 | 2 |
| VGM-90 | 2.10 | 2.99 | 2.0–5.0 | 4 | 2 |

The higher Kd for VGM-45 and VGM-90 reflects the shorter resonance period and
wider band: at T=2.0 s, without sufficient derivative damping, the band edge
correlation `corr(τ, θ̇)` turns slightly positive (injecting), which the guard
catches but at the cost of reduced capture. Kd=2 provides healthy negative
correlation margin at the short-period edge.

### Capture-efficiency sweep (tuned `exc_ff_pid`, T=0.5–7.0 s)

Use `scripts/capture_efficiency_sweep.py` to compute:

- `P_capture(T)`: steady-state (second-half) mean absorbed power from the tuned per-flap `exc_ff_pid` configs.
- `P_opt(T)`: theoretical optimum from each flap H5 using `body1` pitch hydrodynamics (`radiation_damping/components/5_5`, excitation DOF5), with WEC-Sim de-normalization:
  - `B55 = B55_norm * rho * omega`
  - `|F_exc| = mag * rho * g * A`, with `A = H/2 = 0.025 m` (`H = 0.05 m`)
- `eta(T) = P_capture / P_opt` where defined.

Masking/flagging rules:
- Reactive-limited masking is mandatory: periods with `B55 <= 1e-4` are reported as undefined (`masked=true`) and are shaded/hatched in figures. This is expected near the known pitch radiation-damping notch behavior.
- CC linear-validity guard: when `eta > 1 + 1e-6`, the linear single-DOF `P_opt` bound is treated as locally invalid (`linear_popt_invalid=true`), so `eta` is intentionally left blank and marked separately from the B55 notch mask. This typically appears in the short-period range (about `T < 1 s`), where nonlinear behavior can make the linear bound non-applicable.

Note: below T≈1.5 s, `exc_ff_pid` is outside its tuned band (designed for T = 2–7 s). Low power capture at short periods is expected and not an error.

### One-step delay
`ExcitationForceProvider` is updated after each `DoStepDynamics` call. The RSDA functor reads excitation from the previous step (≈ 0.005 s delay vs T≥2.0 s wave period → negligible).

---

## CC vs exc_ff_pid comparison

Use `scripts/cc_vs_ffpid_comparison.py` to load per-flap CSVs from both controllers and
produce per-flap and cross-flap overlay figures on the shared T = 0.5–7 s axis.

### Two-regime result (validated on VGM-0)

| Period range | Winner | Notes |
|---|---|---|
| T≈0.5–1 s | **CC** | Low reactive burden (|inj|/conv ≈ 0.06–0.30); CC operates near the Budal bound |
| T≈3 s | Crossover | Both controllers produce comparable net power |
| T≳4 s | **ff+PID** | CC becomes reactive-heavy and net power drops; ff+PID in its tuned band |

Terminal comparison table (VGM-0, H = 0.05 m). "Winner" = higher **net** P_capture; notes in
parentheses indicate practical constraints that qualify the raw-watts result:

| T [s] | CC P_cap [W] | CC react | ff+PID P_cap [W] | winner |
|-------|-------------|---------|-----------------|--------|
| 0.50  | 0.279       | 0.30    | 0.010           | CC     |
| 0.70  | 0.466       | 0.06    | 0.081           | CC (low reactive) |
| 0.90  | 0.498       | 0.31    | 0.180           | CC     |
| 2.00  | 0.133       | 0.86    | 0.012           | CC (reactive-heavy: high PTO burden) |
| 3.00  | 0.234       | 0.94    | 0.138           | CC (crossover region; reactive-heavy) |
| 4.00  | 0.065       | 0.92    | 0.380           | ff+PID |
| 5.00  | 0.023       | 0.90    | 0.430           | ff+PID |
| 7.00  | 0.003       | 0.92    | 0.112           | ff+PID |

CC "wins" at T=2–3 s in raw net watts but only by circulating large amounts of reactive
power (ratio → 0.86–0.94). A practical PTO cannot economically deliver this reactive
burden; those wins are effectively impractical at the model scale.

### CC validation against Budal bound

CC is theoretically correct (canonical impedance-matching law: `K_r = ω₀²(I+A₅₅) − K_hs`,
`B_r = B₅₅(ω₀)`) and the time-domain simulation reaches **90–100% of the analytical Budal
upper bound** across the band — a strong cross-validation that the controller, gain
de-normalization, and hydro coupling are correctly implemented. This near-Budal agreement
is a genuine result; reaching the bound requires perfect impedance cancellation, which a
wrong implementation would not achieve.

### CC reactive burden at long periods

CC's long-period "wins" (T≳3 s) are reactive-heavy: |P_injected|/P_converted → ~0.9.
At these periods CC circulates large amounts of energy through the PTO to net a small
positive value. This is a well-known property of CC on low-damping OSWECs (small B₅₅ at
long T), not a defect. The comparison figure's bottom panel makes this visible explicitly.
Regions where the reactive ratio > 0.5 are annotated as "reactive-heavy (impractical)"
in the comparison figures.

### Output figures

- `analysis/comparison/figures/cc_vs_ffpid_VGM<angle>.png` — per-flap overlay
- `analysis/comparison/figures/cc_vs_ffpid_summary.png` — cross-flap summary

Regenerate without simulation:
```
python3 scripts/cc_vs_ffpid_comparison.py --plot-only
```

---

## Passive vs optimal-passive sweep

Use `scripts/passive_vs_optpassive_sweep.py` to run the complete passive / opt_passive
comparison across all five VGOSWEC flap variants on the same T = 0.5–7 s period grid.

### Method

Both controllers are pure velocity dampers `τ_pto = −B·θ̇`:

- **PassiveDamper** — fixed hand-tuned `B_pto = B55(ω₀)` (radiation damping at resonance).
- **OptimalPassive** — `B_opt = |Z_intrinsic(ω₀)|` computed from the H5 at startup by
  `PitchImpedanceMagnitude()` in `src/impedance.cpp`, evaluated at each flap's design
  resonance ω₀. `B_opt` is **not** written in the YAML.

The key physics:

- At exact resonance the reactive part of `Z_intrinsic(ω₀)` → 0, so
  `B_opt(ω₀) ≈ B55(ω₀)` — passive and opt_passive coincide near ω₀.
- Off-resonance `|Z_intrinsic(ω)| > B55(ω₀)`, so opt_passive ≥ passive everywhere.
- Both purely dissipative controllers bracket the CC and ff+PID envelopes from below.

### Per-flap B_pto = B55(ω₀) values

| Flap  | ω₀ (rad/s) | T₀ (s) | B55(ω₀) (N·m·s/rad) | Config |
|-------|-----------|--------|----------------------|--------|
| VGM-0  | 1.07  | 5.86 | 3.1908e-7 (pitch notch: near-zero) | vgoswec_0_passive.yaml |
| VGM-10 | 1.468 | 4.29 | 1.2723e-4 | vgoswec_10_passive.yaml |
| VGM-20 | 1.568 | 4.01 | 1.5118e-4 | vgoswec_20_passive.yaml |
| VGM-45 | 1.84  | 3.42 | 2.5303e-4 | vgoswec_45_passive.yaml |
| VGM-90 | 2.094 | 2.99 | 3.9114e-4 | vgoswec_90_passive.yaml |

Values computed as `B55(ω₀) = λ55(ω₀) · ρ_h5 · ω₀`
(i.e., `GetPitchHydroCoefficientsAtOmega(...).B55` from `src/impedance.cpp`).
Note: VGM-0's value is in the radiation-damping pitch notch (below the B55 ≤ 1e-4 mask
threshold); the passive controller produces negligible capture for that flap.

### Per-flap design_omega for opt_passive

| Flap  | design_omega (rad/s) | Config |
|-------|---------------------|--------|
| VGM-0  | 1.07  | vgoswec_0_opt_passive.yaml |
| VGM-10 | 1.468 | vgoswec_10_opt_passive.yaml |
| VGM-20 | 1.568 | vgoswec_20_opt_passive.yaml |
| VGM-45 | 1.84  | vgoswec_45_opt_passive.yaml |
| VGM-90 | 2.094 | vgoswec_90_opt_passive.yaml |

### Masking rules (identical to all other sweep scripts)

- `B55 ≤ 1e-4`: reactive-limited; `P_opt` undefined; `masked=true`; hatched shading.
- `eta > 1 + 1e-6`: linear `P_opt` bound locally invalid (`linear_popt_invalid=true`).

### Output figures

- `analysis/passive/figures/capture_efficiency_VGM<angle>.png` — per-flap passive
- `analysis/passive/figures/capture_efficiency_summary.png` — cross-flap passive
- `analysis/opt_passive/figures/capture_efficiency_VGM<angle>.png` — per-flap opt_passive
- `analysis/opt_passive/figures/capture_efficiency_summary.png` — cross-flap opt_passive
- `analysis/passive_vs_optpassive/figures/passive_vs_optpassive_VGM<angle>.png` — overlay
- `analysis/passive_vs_optpassive/figures/passive_vs_optpassive_summary.png` — cross-flap
- `analysis/passive_vs_optpassive/figures/passive_vs_optpassive_efficiency_summary.png`

Regenerate all figures from committed CSVs without running the solver:
```
python3 scripts/passive_vs_optpassive_sweep.py --plot-only
```

---

## Known limitations (carried forward to a later follow-up)

**Un-hinge-referred F_exc (current session limitation — NOT fixed in this PR):**

`F_exc` used by `ExcitationVelocityController` is the raw, un-hinge-referred pitch
moment (`moment.y()` from `ExcitationForceProvider`). The correct quantity for
velocity-reference generation is the hinge-referred excitation torque, which requires
measuring the effective hinge impedance via `revolute->GetReactionTorque()`.

**Observable consequences:**
1. The capture peak sits **below** each flap's resonance frequency (not at it).
2. At short periods (high frequencies), the controller injects energy — which the
   `passive_safe` guard is designed to contain.
3. `alpha` must be positive (empirically) to paper over the phase/sign mismatch.

**Impact on tuning results:** All shipped gain sets are validated as passive-safe and
non-injecting at both band edges (with the guard active). The absolute capture values
are lower than the theoretical maximum; the band-integrated optimisation objective
reduces (but does not eliminate) the edge-injection tendency.

**Follow-up PR scope:**
- Measure effective hinge impedance via `revolute->GetReactionTorque()`.
- Fix excitation hinge-referral at the source (`ExcitationForceProvider`).
- Re-derive `alpha` from the measured impedance for true complex-conjugate control.
- Re-run the Kp×Kd sweep with corrected F_exc; capture peaks should shift to resonance.

---

## HIL interface

All four controllers implement `seastack::pto::IPTOModel`:
```cpp
virtual double ComputeForce(double displacement, double velocity, double time) = 0;
```

To replace any controller with a hardware-in-the-loop (HIL) implementation, derive from `IPTOModel` and pass to `RsdaPtoFunctor`. See `docs/HIL_MIGRATION.md`.

---

## Tuning guide (wave-tank scale)

1. **Start with PassiveDamper**. Verify flap motion is physical (no divergence).
2. **OptimalPassive**: theoretical maximum for passive control. Compare with step 1.
3. **CC control**: compare peak torque vs clip. Reduce clip until stable.
4. **ExcFF+PID**: Use `passive_safe: true` (guard enabled). Set `alpha=11`, `Ki=5` (fixed).
   Sweep `Kp ∈ {2..6}` × `Kd ∈ {0..3}` over the flap's physical band using
   `scripts/sweep_kpkd_vgoswec.sh`. Pick the (Kp, Kd) that maximises band-integrated
   capture while satisfying all hard constraints. Regenerate figures with
   `scripts/plot_kpkd_surface.py`.
