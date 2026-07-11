# Capture-Efficiency Study — Key Findings

**See [`analysis/FINDINGS_3REGIME.md`](FINDINGS_3REGIME.md) for the consolidated
three-regime relay findings (CC → opt_passive → ff+PID).**

Controller comparison across VGOSWEC flap variants (VGM-0/10/20/45/90) over a shared
wave-period grid **T = 0.5–7.0 s** (0.25 s steps, H = 0.05 m). Three controllers:

- **CC** — complex-conjugate (reactive) control.
- **opt_passive** — optimal resistive damping at resonance, `B_opt = |Z_intrinsic(ω₀)|`.
- **ff+PID** — tuned excitation-feedforward + PID (`exc_ff_pid`), designed for T = 2–7 s.

All results are reproducible from the committed CSVs under
`analysis/{cc,opt_passive,passive_guarded}/` via each script's `--plot-only` mode.
No solver runs are required to regenerate the figures.

Naming convention: `P_injected_W` (reactive power returned to the fluid),
`P_converted_W` (gross PTO conversion), and captured power
`P_capture_W = P_converted_W − P_injected_W`.

---

## 1. Two-regime result (headline)

CC and ff+PID cleanly split the period axis:

- **CC dominates short periods** (T ≈ 0.5–3 s).
- **ff+PID dominates long periods** (T ≳ 3 s).
- **Crossover ≈ T ≈ 3.2 s** (VGM-0), marked on the per-flap comparison figures.

The achievable operating envelope is the **upper hull** of the two controllers — CC's
short-period peak *plus* ff+PID's long-period tail — which neither controller reaches alone.

## 2. CC matches the theoretical optimum at short periods

CC captured power tracks the analytic optimum **P_opt** almost exactly up to T ≈ 1.5 s.
For VGM-0 the CC peak is **2.34 W at T = 1.5 s** with efficiency η ≈ 94–108% (within
numerical tolerance of the bound). This validates the CC implementation against the
Budal/optimal-absorption limit.

## 3. CC's long-period "wins" are reactive-heavy (impractical)

The CC reactive ratio `|P_injected| / P_converted` (VGM-0) crosses the 0.5 "impractical"
threshold near **T ≈ 1.2 s** and climbs to **~0.9 by T ≈ 3 s**. So even where CC's captured
power remains nonzero at mid periods, it is paying a large reactive penalty. CC's *practical*
useful range is therefore narrower than its raw captured-power curve suggests.

## 4. ff+PID is the practical long-period absorber

ff+PID peaks around **T ≈ 3.3–3.5 s** and degrades gracefully out to 7 s with **no**
reactive-heavy penalty. Efficiency is modest (~10–15%) but honest and physically realizable.

## 5. Flap-angle ordering is systematic

Across VGM-0 → VGM-90 the peak captured power and the CC efficiency roll-off shift
monotonically. **VGM-0** is the strongest overall and holds efficiency to the longest
periods; higher flap angles roll off earlier and capture less. The same ordering appears
in both the power and efficiency views.

## 6. Tuned-band caveat (not an anomaly)

Below T ≈ 1.5 s, ff+PID is outside its tuned design band (T = 2–7 s). The isolated
VGM-0 ff+PID point near T ≈ 0.75 s (η ≈ 26%) sits below CC and reflects this out-of-band
behavior — expected, not an error.

---

## 7. Capstone: adaptive control + flap-angle schedule

The two controllers are **complementary**, and — critically — the *optimal flap angle also
sweeps with period*. Combining control-mode switching with a flap-angle schedule yields a
single adaptive strategy whose envelope beats any fixed configuration.

### ff+PID captured power by flap angle (W) — winner per period

| T (s) | VGM-0 | VGM-20 | VGM-90 | Best |
|------:|------:|-------:|-------:|:----:|
| 2.50  | 0.006 | 0.302  | 0.446  | **90°** |
| 2.75  | 0.046 | 0.369  | 0.547  | **90°** |
| 3.00  | 0.138 | 0.519  | 0.351  | **20°** |
| 3.25  | 0.195 | **0.712** | 0.238 | **20°** |
| 3.50  | 0.246 | 0.626  | 0.181  | **20°** |
| 3.75  | 0.313 | 0.510  | 0.144  | **20°** |
| 4.00  | 0.379 | 0.408  | 0.119  | 20° / 0° |
| 4.25  | 0.439 | 0.337  | 0.105  | **0°** |
| 4.50  | **0.480** | 0.280 | 0.093 | **0°** |
| 5.00  | 0.430 | 0.203  | 0.075  | **0°** |
| 6.00  | 0.216 | 0.122  | 0.048  | **0°** |
| 7.00  | 0.109 | 0.084  | 0.034  | **0°** |

The single highest long-period capture point is **VGM-20: 0.712 W at T = 3.25 s**.

### The 4-phase adaptive schedule

Optimal operation traverses **control mode _and_ flap angle** as the wave period grows —
the flap opens then re-closes (0° → 90° → 20° → 0°):

| Phase | Period band | Control | Flap angle | Rationale |
|:-----:|:-----------:|:-------:|:----------:|-----------|
| 1 | T ≲ 1.5 s      | **CC**     | **0° (closed)**      | Tracks P_opt, η ≈ 94–108%; VGM-0 CC peak 2.34 W @ 1.5 s |
| 2 | T ≈ 2.5–2.75 s | **ff+PID** | **90° (open)**       | After CC→ff+PID handoff, fully-open flap wins (0.45→0.55 W) |
| 3 | T ≈ 3.0–4.0 s  | **ff+PID** | **20° (part-closing)** | Global ff+PID max — VGM-20 0.712 W @ 3.25 s |
| 4 | T ≳ 4.25 s     | **ff+PID** | **0° (closed again)** | VGM-0 retakes lead (0.48 W @ 4.5 s) and holds longest tail |

**Approximate switch periods:** CC→ff+PID + open near **T ≈ 2 s**; 90°→20° near **T ≈ 3 s**;
→0° near **T ≈ 4.1 s**.

**Physical picture:** operate CC with the flap closed at short periods; as the period grows,
open the valves to hand off to ff+PID and open the flap, then progressively re-close the flap
(90° → 20° → 0°) as the period increases further. The optimal flap angle sweeps smoothly
open-and-back-closed, and the achievable capture envelope is the upper hull across all four
modes.

---

## Reproducing the figures

```bash
# Three-regime (CC / opt_passive / ff+PID) per-flap + cross-flap + operating envelope:
python3 scripts/three_regime_comparison.py --plot-only

# Individual controller sweeps:
python3 scripts/capture_efficiency_sweep.py     --plot-only   # analysis/passive_guarded/figures/
python3 scripts/cc_capture_efficiency_sweep.py  --plot-only   # analysis/cc/figures/
python3 scripts/cc_vs_ffpid_comparison.py       --plot-only   # analysis/comparison/figures/
```

## Deferred / next phase

- Literature cross-check (Issue #50): verify CC/opt_passive results against Falnes/Ringwood
  textbook; confirm variable-geometry OSWEC operating-map novelty; check excitation-FF
  velocity-tracking prior art.
- Optional refactor: unify per-script power/efficiency ceiling helpers into one shared
  module so matched ceilings cannot drift.
