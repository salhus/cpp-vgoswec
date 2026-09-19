# Shared capture-efficiency sweep method

This note is the **canonical simulation-method reference** for the three capture-efficiency sweep arms:

- `scripts/passive_vs_optpassive_sweep.py`
- `scripts/cc_capture_efficiency_sweep.py`
- `scripts/capture_efficiency_sweep.py` (`passive_guarded` / ff+PID)

The goal is **uniformity of method**, not identical record duration. Duration is a derived quantity from each arm's closed-loop damping.

## Shared method summary

Shared constants and rules:

- Default period grid: `T = 0.5–7.0 s` in `0.25 s` steps (`27` points)
- Optional diagnostic re-grid: `--period-step`, validated against the rounded shared grid
- Wave ramp: `RAMP_S = 10.0 s`
- Steady-state average: final `N_AVG = 20` **whole** wave cycles
- Duration rule: `duration(T) = RAMP_S + N_CYCLES·T`
- Sweep timestep: `dt = 0.01 s`, written into each scratch YAML
- CSV provenance columns: `duration_s`, `dt_s`, `period_step_s`, `n_settle`, `n_avg`

Per-arm cycle counts:

| Arm | `N_SETTLE` | `N_AVG` | `N_CYCLES` | Duration rule |
|---|---:|---:|---:|---|
| passive / `opt_passive` | 130 | 20 | 150 | `10 + 150·T` |
| CC | 260 | 20 | 280 | `10 + 280·T` |
| ff+PID (`passive_guarded`) | 260 | 20 | 280 | `10 + 280·T` |

## Why cycle-based duration and whole-cycle averaging

The old CC / ff+PID method used a fixed `171 s` record and averaged over the second half of the samples. That mixes very different cycle counts across the sweep and introduces a period-dependent partial-cycle averaging bias.

The unified method fixes both problems:

- every point gets the same settle allowance and averaging length **in cycles**;
- the average is taken over a whole-number wave window, so partial-cycle bias is removed by construction;
- all three arms now write the same method provenance into their CSVs.

This is a **rigor and defensibility** change. The passive/`opt_passive` arm already showed that the method update moved committed values only modestly, typically by about `0.15–0.45%`, so the issue is comparability, not a physics rewrite.

## Passive / `opt_passive`: why `N_SETTLE = 130`

The transient decays geometrically cycle-to-cycle. For closed-loop damping ratio `ζ_cl`, the residual amplitude after one cycle is `exp(-2·π·ζ_cl)`, so the cycles required to reach residual tolerance `tol` are:

`ln(1 / tol) / (2·π·ζ_cl)`

At resonance under `opt_passive`, the reactive part of `Z_intrinsic` vanishes, so `B_opt = |Z_intrinsic(ω₀)| = B55(ω₀)`. The damping **doubling** does **not** come from that equality by itself; it comes from the PTO damping **adding to** the plant's existing radiation damping, giving total resistive damping of approximately `B55 + B_opt ≈ 2·B55`. Therefore `ζ_cl ≈ 2·ζ_freedecay` at resonance.

Using the validated free-decay `ζ` values from [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md):

| Flap | `ζ_freedecay ×10⁻⁴` | `ζ_cl ≈ 2ζ` | cycles to 1% | cycles to 0.1% |
|---|---:|---:|---:|---:|
| VGM-0 | 52.8 | 0.0106 | 69 | 104 |
| VGM-10 | 38.1 | 0.0076 | 96 | 145 |
| VGM-20 | 47.5 | 0.0095 | 77 | 116 |
| VGM-45 | 36.7 | 0.0073 | 100 | 150 |
| VGM-90 | 28.6 | 0.0057 | 129 | 193 |

VGM-90 binds, so the passive / `opt_passive` arm uses `N_SETTLE = 130` and `N_CYCLES = 150`.

## CC: why `N_SETTLE = 260`

CC does **not** get the passive-arm damping doubling. In `src/demo_vgoswec.cpp` / `src/impedance.h`, CC sets `B_r = B55(ω₀)`. That cancels the reactive part but only adds a resistive term equal to the plant radiation damping itself, so the resonance-scale closed-loop damping remains `ζ_cl ≈ ζ_freedecay`, not `2ζ_freedecay`.

Using the same `1%` residual criterion with the validated free-decay `ζ` values:

| Flap | `ζ ×10⁻⁴` | cycles to 1% |
|---|---:|---:|
| VGM-0 | 52.8 | 139 |
| VGM-10 | 38.1 | 192 |
| VGM-20 | 47.5 | 154 |
| VGM-45 | 36.7 | 200 |
| VGM-90 | 28.6 | 256 |

VGM-90 binds, so the CC arm uses:

- `N_SETTLE = 260`
- `N_AVG = 20`
- `N_CYCLES = 280`
- `duration(T) = 10 + 280·T`

Representative CC durations:

| T [s] | duration [s] |
|---:|---:|
| 0.5 | 150.0 |
| 1.5 | 430.0 |
| 3.0 | 850.0 |
| 5.0 | 1410.0 |
| 7.0 | 1970.0 |

## ff+PID: why it also uses `N_SETTLE = 260`

For `exc_ff_pid`, `ζ_cl` is not analytically clean: the gains are empirical, and the controller combines excitation feedforward, velocity-tracking PID, and a passive-safety guard. This arm therefore does **not** get an invented closed-form settle derivation.

Instead it inherits the **same conservative bound as CC**:

- `N_SETTLE = 260`
- `N_AVG = 20`
- `N_CYCLES = 280`

This is justified because:

1. the passive-safety fallback bounds the arm below by passive behaviour, so the CC-derived settle count is conservative for the guarded controller too; and
2. the short-period diagnostic below confirms adequacy in the band where ff+PID carries the envelope.

## CC diagnostics from the committed-method audit

These checks were already performed and must **not** be re-run as part of this PR. They establish why the method unification is necessary.

### Long period — VGM-90 CC, `T = 5.00 s`, `design_omega = 1.25663706`

| case | window | mean `power_w` |
|---|---|---:|
| 171 s (committed) | half-record | −2.98142124e-03 |
| 760 s | half-record | −2.8183e-04 |
| 760 s | final 20 whole cycles | −2.8398e-04 |

The `171 s` value reproduces the committed CSV exactly. Extending the run to `150` cycles shrinks the magnitude by about `10.6×`. Here `P_converted ≈ 7.64e-02` and `P_injected ≈ 7.94e-02`, so `P_net` is less than `1%` of the gross power flow: a catastrophic-cancellation residual converging toward zero, not toward a meaningful long-period CC operating point.

### Short period — VGM-0 CC, `T = 1.50 s`, `design_omega = 4.18879020`

| case | window | mean `power_w` | vs committed |
|---|---|---:|---:|
| 171 s | half-record | 2.34265974e+00 | exact match |
| 235 s | half-record | 2.32631337e+00 | −0.70% |
| 235 s | final 20 whole cycles | 2.34327305e+00 | +0.03% |

This is the opposite regime: the headline `2.34 W` CC peak is confirmed safe to `0.03%`. The method change is therefore justified on **rigor and uniformity**, not on correcting the short-period CC physics.

## CC cancellation guard

CC already carried two validity guards:

- `MASK_B55_THRESHOLD` for the denominator-side `P_opt` mask;
- `linear_popt_invalid` for `η > 1` cases.

The unified method adds a third guard for the numerator-side catastrophic-cancellation regime:

- `reactive_cancellation_limited = true` when `P_converted > 0` and `|P_capture| / P_converted < 1e-2`

These rows are excluded from:

- CC efficiency output (`η` left blank)
- CC plots
- CC vs ff+PID overlays
- three-regime overlays
- power and efficiency envelope selection

Like the existing `masked` handling, they are visualised with hatched exclusion spans and comparison scripts tolerate legacy CSVs that do not yet carry the column.

## Why `dt = 0.01 s`

The sweep timestep is shared across all three arms.

| T [s] | steps/cycle @ `dt = 0.01 s` |
|---:|---:|
| 0.5 | 50 |
| 1.0 | 100 |
| 2.0 | 200 |
| 7.0 | 700 |

`50` steps/cycle at the shortest-period end is sufficient for the sweep, while halving step count relative to `0.005 s`. The passive / `opt_passive` audit confirmed this at the demanding low-damping case **VGM-90 `opt_passive`, `T = 2.50 s`**:

| dt | `P_capture` [W] |
|---:|---:|
| 0.01 | 5.079e-01 |
| 0.005 | 5.099e-01 |

These differ by about `0.4%`, so `dt = 0.01 s` is converged for campaign use.

## Reproduction commands

```bash
python3 scripts/cc_capture_efficiency_sweep.py
python3 scripts/capture_efficiency_sweep.py
python3 scripts/passive_vs_optpassive_sweep.py
```

For a diagnostic re-grid without changing the committed default:

```bash
python3 scripts/cc_capture_efficiency_sweep.py --period-step 0.1
python3 scripts/capture_efficiency_sweep.py --period-step 0.1
python3 scripts/passive_vs_optpassive_sweep.py --period-step 0.1
```

For figures only, reusing committed CSVs:

```bash
python3 scripts/cc_capture_efficiency_sweep.py --plot-only
python3 scripts/capture_efficiency_sweep.py --plot-only
python3 scripts/passive_vs_optpassive_sweep.py --plot-only
```

## `opt_passive` anomaly note (2026-09-19 impedance audit)

The conspicuous **VGM-90 `opt_passive` spike at `T = 2.50 s`** in the committed CSVs is now explained and should be treated as stale pending the owner re-run.

- Before the impedance-basis fix, `opt_passive` gains were computed from the **CG-referenced** H5 while the physical torque was applied in the hinge DOF.
- On that wrong basis, the spurious impedance resonance sits near **`T₀ = 2.61 s`**, and the shared sweep grid point at **`T = 2.50 s`** is the nearest sample, artificially minimizing `|Z|` and lightening the damper.
- After the hinge-basis correction (`hydro.impedance_h5_file = hinged_*`, `K_hs_eff = K_hs55 + C_ext + K_gb`), expect the resonance hump to move back toward **`T ~ 3.0 s`** and cease to appear as an isolated anomaly.

See [`IMPEDANCE_BASIS.md`](IMPEDANCE_BASIS.md) for the full defect record.
