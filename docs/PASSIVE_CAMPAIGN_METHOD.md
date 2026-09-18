# Passive / opt_passive campaign method

This note documents the simulation method used by
`scripts/passive_vs_optpassive_sweep.py` for the passive / `opt_passive`
capture-efficiency sweep.

## Method summary

- Shared period grid by default: `T = 0.5–7.0 s` in `0.25 s` steps. The sweep
  also exposes `--period-step` for diagnostic uniform re-grids; the committed
  default remains the shared 27-point grid used by the CC and tuned
  `exc_ff_pid` sweeps.
- Wave ramp: `RAMP_S = 10.0 s`.
- Settling window discarded: `N_SETTLE = 130` cycles.
- Steady-state window averaged: `N_AVG = 20` whole cycles.
- Total simulated cycles per period: `N_CYCLES = 150`.
- Duration rule: `duration(T) = 10 + 150·T` seconds.
- Sweep timestep: `dt = 0.01 s`.
- Steady-state power metric: mean `power_w` over the final `20` whole cycles.

## Why cycle-based duration

The old fixed-duration method used `171 s` for every point on the period grid.
That gives radically different cycle counts across the sweep:

- `T = 0.5 s` → `171 / 0.5 = 342` cycles
- `T = 7.0 s` → `171 / 7.0 ≈ 24` cycles

Simulation requirements scale with wave period, so simulation duration should
scale with wave period too. A period-aware duration gives every point the same
transient-settling allowance and the same steady-state averaging length in
cycles, rather than over-resolving the short-period end while under-resolving
the long-period end.

## Why whole-cycle averaging

The steady-state metric is the mean of the periodic `power_w` signal. If the
averaging window spans an exact whole number of wave cycles, the partial-cycle
bias in the mean is identically zero. If instead the window is a fixed fraction
of samples from a record whose duration is not an integer multiple of the wave
period, the window ends mid-cycle and leaves a residual that depends on the
period.

That is why whole-cycle averaging is the more rigorous and defensible method:
the partial-cycle residual is identically zero rather than merely small, and it
matches the period-aware duration rule so every point is compared on the same
cycle count.

Measured old-vs-new `P_capture` for VGM-90 `opt_passive` showed that the
previous results were **not materially wrong**:

| T [s] | old | new | delta |
|---:|---:|---:|---:|
| 2.25 | 1.15509970e-01 | 1.15774391e-01 | +0.23% |
| 2.50 | 5.08708353e-01 | 5.07947697e-01 | −0.15% |
| 2.75 | 2.03070970e-01 | 2.02150933e-01 | −0.45% |

So the method change is justified on **rigor, determinism, and defensibility**,
not on having corrected a significant physics error.

The η-audit also came back clean: scanning all ten committed passive /
`opt_passive` CSVs returned **no** η > 1 points anywhere. The earlier idea that
partial-cycle averaging might be a plausible contributor to spurious η > 1
flags is therefore **not supported by the data**.

## How `N_SETTLE = 130` was derived

The transient decays geometrically cycle-to-cycle. For closed-loop damping ratio
`ζ_cl`, the residual amplitude after one cycle is

`exp(-2·π·ζ_cl)`.

So the cycles required to reach residual tolerance `tol` are

`ln(1 / tol) / (2·π·ζ_cl)`.

This is independent of wave period. The required settle cycles are set by the
closed-loop damping ratio alone.

At resonance under `opt_passive`, the reactive part of `Z_intrinsic` vanishes,
so

`B_opt = B55(ω₀)`,

which exactly doubles the system damping:

`ζ_cl ≈ 2·ζ_freedecay`.

The free-decay `ζ` values below are the validated standard-config values from
[`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md). This
derivation is only possible because the free-decay campaign validated `ζ`; this
is a direct downstream use of that result and is part of the justification for
doing the free-decay campaign in the first place.

| Flap | ζ_freedecay ×10⁻⁴ | ζ_cl ≈ 2ζ | cycles to 1% | cycles to 0.1% |
|---|---:|---:|---:|---:|
| VGM-0 | 52.8 | 0.0106 | 69 | 104 |
| VGM-10 | 38.1 | 0.0076 | 96 | 145 |
| VGM-20 | 47.5 | 0.0095 | 77 | 116 |
| VGM-45 | 36.7 | 0.0073 | 100 | 150 |
| VGM-90 | 28.6 | 0.0057 | 129 | 193 |

VGM-90 is the binding case at `129` cycles to `1%` residual because it is the
most lightly damped geometry. `N_SETTLE = 130` is chosen to clear it.

This is the resonant worst case. Off resonance, `B_opt = |Z_intrinsic(ω)| ≫
B55(ω₀)`, so damping is much higher and settling is much faster. Therefore
`130` cycles is conservative everywhere except at resonance, where it is
approximately exact for the worst geometry.

## Why `N_AVG = 20` is sufficient

Whole-cycle averaging makes the bias exactly zero rather than merely small. The
averaging window therefore only needs to suppress numerical noise and any small
residual non-periodicity left after the settling window. `20` cycles is ample
for that purpose. More cycles would add computation without improving the mean
in any physically meaningful way.

## Why `dt = 0.01 s`

The sweep timestep is coarsened from `0.005 s` to `0.01 s`.

| T [s] | steps/cycle @ dt=0.01 |
|---:|---:|
| 0.5 | 50 |
| 1.0 | 100 |
| 2.0 | 200 |
| 7.0 | 700 |

`50` steps/cycle at the worst case (`T = 0.5 s`) is comfortable for resolving a
sinusoid and its squared quantity (`power`). By contrast, `dt = 0.05 s` was
considered and rejected:

- it gives only `10` steps/cycle at `T = 0.5 s`
- that is too coarse to represent the peak amplitude of a sinusoid
- because power scales with velocity squared, the amplitude error roughly
  doubles in `P_capture`
- the short-period end (`T = 0.5–1.5 s`) is where the CC power hull peaks
  (`2.34 W` at `T = 1.5 s`, VGM-0), so this is exactly the wrong region to lose
  accuracy

Two further constraints also argue against `dt = 0.05 s`:

1. The radiation convolution is integrated on the RIRF time grid, so coarsening
   past that sample spacing undersamples the convolution memory. This is
   consistent with the `ω_nyquist = π/dt` warning in `src/impedance.cpp`.
2. With low damping and a hinge spring, a coarse step risks integrator energy
   drift over the long records used in this campaign.

The free-decay sensitivity check showed that changing `dt` from `0.005` to
`0.0005` moved `ζ` by only about `7%`, establishing that `0.005` was already
inside the converged band. `0.01` therefore remained a plausible campaign
choice while halving the step count, but that still needed checking in the
low-damping regime near the mask threshold.

That follow-up check has now been done at the demanding case
**T = 2.50 s, VGM-90 `opt_passive`, `design_omega = 2.51327412`**, where
`B55 ≈ 4.11e-4` (only ~4× the `1e-4` mask threshold):

| dt | `P_capture` [W] |
|---:|---:|
| 0.01 | 5.079e-01 |
| 0.005 | 5.099e-01 |

These are **0.4% apart**, so `dt = 0.01 s` is confirmed converged in the
demanding low-damping case, not just in the high-damping `T = 7.0 s` check.

## Resulting durations

The duration rule is

`duration(T) = 10 + 150·T`.

Representative values are:

| T [s] | duration [s] |
|---:|---:|
| 0.5 | 85.0 |
| 1.0 | 160.0 |
| 2.0 | 310.0 |
| 3.0 | 460.0 |
| 5.0 | 760.0 |
| 5.86 | 889.0 |
| 7.0 | 1060.0 |

`T = 5.86 s` and `T = 3.0 s` are the VGM-0 and VGM-90 resonance periods,
respectively. Both receive the full `150` simulated cycles under this rule.

## T = 2.50 s retuning effect (open investigation)

One feature survived every numerical audit unchanged: at **T = 2.50 s**,
VGM-90 `opt_passive` gives `P_capture = 5.08e-01 W` against neighbours of
`1.16e-01 W` at `T = 2.25 s` and `2.02e-01 W` at `T = 2.75 s` — a **4.4×**
jump at a single grid point.

Established facts:

- **Not a denominator or masking artifact.** `B55` is smooth and monotone
  through the spike: `3.66e-4 → 4.11e-4 → 4.11e-4` at
  `T = 2.25 / 2.50 / 2.75 s`. `P_capture` itself spikes.
- **Not a timestep artifact.** The `dt = 0.01` vs `0.005` check above agrees to
  0.4%.
- **Not an averaging artifact.** The spike survived the PR #61 method change
  with only sub-percent movement.
- **It is a controller-tuning effect.** At `T = 2.50 s`, holding the
  hydrodynamics fixed but changing only `design_omega` gives:
  - `design_omega = 2.094` (flap-resonance default) → `P_capture = 0.218 W`
  - `design_omega = 2.51327412` (`2π / 2.5`, used by the sweep) → `P_capture = 0.510 W`

That is a **2.3×** power change from damper tuning alone, at a period well off
the flap's own resonance (~3.0 s). A similar bump appears in VGM-45
`opt_passive` near `T = 3.0 s`, and VGM-90 `passive` shows a smaller bump near
`T = 2.75 s` in the summary figure.

This remains **open for investigation**: why does
`B_opt = |Z_intrinsic(ω)|` produce such a strong response at that particular
frequency in the low-damping region?

## Reproduction command

```bash
python3 scripts/passive_vs_optpassive_sweep.py
```

For a finer diagnostic uniform grid without changing the default committed
behavior:

```bash
python3 scripts/passive_vs_optpassive_sweep.py --period-step 0.1
```

For figures only, reusing the committed CSVs:

```bash
python3 scripts/passive_vs_optpassive_sweep.py --plot-only
```
