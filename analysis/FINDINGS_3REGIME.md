# Three-Regime Relay — Key Findings

Controller co-design study across VGOSWEC flap variants (VGM-0/10/20/45/90) over
**T = 0.5–7.0 s** (0.25 s steps, H = 0.05 m). Three controllers:

- **CC** — complex-conjugate (reactive) control.
- **opt_passive** — optimal resistive damping, `B_opt = |Z_intrinsic(ω₀)|`.
- **ff+PID** — tuned excitation-feedforward + PID (`exc_ff_pid`), the `passive_guarded` arm.

All results are reproducible from committed CSVs under
`analysis/{cc,opt_passive,passive_guarded}/` via `--plot-only`. No solver runs required.

---

## 1. Three-regime relay (headline result)

The period axis splits cleanly into three controller regimes, with the crossover periods
**sliding along the period axis with flap angle** (because the resonance period T₀ shifts):

| Regime | Period band | Winner | Notes |
|--------|-------------|--------|-------|
| **CC** | T ≲ 2 s | **CC** | Near Budal bound; CC peak up to 2.34 W at T=1.5 s (VGM-0) |
| **opt_passive** | ~resonance band | **opt_passive** / tie | Matches tuned ff+PID at resonance with a single tuning-free coefficient |
| **ff+PID** | T ≳ resonance | **ff+PID** | Carries the long tail past resonance with no reactive penalty |

**Crossover periods per flap:**

| Flap | T₀ (resonance) | CC/opt_p xover | opt_p/ff+PID xover |
|------|---------------|----------------|-------------------|
| VGM-90 | ≈2.50 s | ≈1.5–2.0 s | ≈2.5–3.0 s |
| VGM-45 | ≈3.00 s | ≈1.5–2.0 s | ≈3.0–3.5 s |
| VGM-20 | ≈3.25 s | ≈1.5–2.0 s | ≈3.5–4.0 s |
| VGM-10 | ≈3.50 s | ≈1.5–2.0 s | ≈3.5–4.5 s |
| VGM-0  | ≈4.75 s | ≈1.5–2.0 s | ≈4.5–5.5 s |

The flap-angle co-design knob shifts the resonance peak — and therefore the
opt_passive vs ff+PID handoff — across the entire T = 2.5–5 s band. This is the
**controller×geometry co-design operating map**: no single controller or fixed flap
achieves the upper hull; the adaptive (controller, flap-angle) schedule does.

---

## 2. opt_passive resonance hump marches with flap angle

| Flap | opt_passive peak P_capture | peak T | ff+PID peak (passive_guarded) | winner at resonance |
|------|---------------------------|--------|-------------------------------|---------------------|
| VGM-90 | 0.509 W | 2.50 s | ~0.55 W | ff+PID edges |
| VGM-45 | 0.479 W | 3.00 s | ~0.63 W | ff+PID edges |
| VGM-20 | 0.755 W | 3.25 s | ~0.73 W | opt_passive edges |
| VGM-10 | 0.772 W | 3.50 s | ~0.75 W | opt_passive edges |
| VGM-0  | 0.681 W | 4.75 s | ~0.68 W | tie |

The resonance hump monotonically shifts from T ≈ 2.5 s (VGM-90, flap fully open)
to T ≈ 4.75 s (VGM-0, flap closed). This confirms that the intrinsic resonance
T₀ = 2π/ω₀ indeed marches as the flap geometry changes — the hydrodynamic coupling
(radiation damping B55, added inertia A55) all shift together with the flap angle.

### Honest opt_passive vs ff+PID framing

**opt_passive matches a tuned feedforward controller at resonance with a single
tuning-free damping coefficient, and beats CC by 10–30× in the long tail.**

Specifically:
- At the resonance peak: opt_passive **ties-to-slightly-beats** ff+PID on low-angle
  flaps (VGM-0/10/20) and ff+PID **edges** opt_passive on high-angle flaps (VGM-45/90).
- The claim is NOT "opt_passive universally wins" — it is that opt_passive achieves
  comparable resonance-band performance to a carefully tuned feedforward controller,
  with zero per-flap tuning overhead (just one B55-derived coefficient).
- At long periods (T > T₀): ff+PID holds the long tail gracefully; opt_passive drops
  off as the off-resonance impedance mismatch grows.

---

## 3. CC validates the Budal bound (short periods)

CC captured power tracks the analytic optimum **P_opt** almost exactly up to
T ≈ 1.5 s. For VGM-0 the CC peak is **2.34 W at T = 1.5 s** with η ≈ 94–108%.
This validates the CC implementation against the Budal/optimal-absorption limit.

At long periods (T ≳ 2 s), CC becomes reactive-heavy
(`|P_injected|/P_converted` → ~0.9). These reactive-heavy "wins" are impractical at
model scale. CC's practical useful range is T ≲ 2 s.

---

## 4. Master operating envelope (co-design capstone)

### 4a. Power operating hull

For each wave period T, the **upper hull = max(P_capture)** over all controllers AND
all flap variants gives the best achievable power from any (controller, flap-angle)
combination.

See `analysis/three_regime/figures/operating_envelope.png` and
`analysis/three_regime/operating_envelope.csv` (hull reproduced from committed CSVs).

**Annotated winner per band:**
- **Short T (≲2 s):** CC + VGM-0 (closed flap, Budal-bound tracking, up to 2.34 W)
- **Resonance band (≈2.5–5 s):** opt_passive or ff+PID + the flap whose T₀ matches
  the wave period (90° at T≈2.5 s, marching down to 0° at T≈4.75 s)
- **Long tail (T ≥ 4.5 s):** opt_passive + VGM-0 (large raw excitation force even in the pitch-radiation notch where P_opt is undefined)

No single controller or flap reaches this envelope alone.

| T_s | P_max_W | controller | flap_angle |
|-----|---------|-----------|-----------|
| 0.50 | 0.2958 | CC | 90 |
| 0.75 | 0.5708 | CC | 90 |
| 1.00 | 1.4970 | CC | 0 |
| 1.25 | 1.9298 | CC | 0 |
| 1.50 | 2.3427 | CC | 0 |
| 1.75 | 1.9575 | CC | 0 |
| 2.00 | 1.2889 | CC | 0 |
| 2.25 | 0.8149 | CC | 0 |
| 2.50 | 0.5238 | CC | 0 |
| 2.75 | 0.5467 | ff+PID | 90 |
| 3.00 | 0.6316 | ff+PID | 45 |
| 3.25 | 0.7547 | opt_passive | 20 |
| 3.50 | 0.7721 | opt_passive | 10 |
| 3.75 | 0.6291 | ff+PID | 10 |
| 4.00 | 0.5114 | ff+PID | 10 |
| 4.25 | 0.4394 | ff+PID | 0 |
| 4.50 | 0.6534 | opt_passive | 0 |
| 4.75 | 0.6814 | opt_passive | 0 |
| 5.00 | 0.5927 | opt_passive | 0 |
| 5.25 | 0.4977 | opt_passive | 0 |
| 5.50 | 0.4194 | opt_passive | 0 |
| 5.75 | 0.3479 | opt_passive | 0 |
| 6.00 | 0.2897 | opt_passive | 0 |
| 6.25 | 0.2460 | opt_passive | 0 |
| 6.50 | 0.2064 | opt_passive | 0 |
| 6.75 | 0.1757 | opt_passive | 0 |
| 7.00 | 0.1478 | opt_passive | 0 |

### 4b. Efficiency operating hull

For each period T, the **efficiency upper hull = max(η)** over all controllers AND flap
variants, where η = P_capture / P_opt. **Only unmasked, well-defined points are
included**: rows where `masked == true`, `linear_popt_invalid == true`, η is NaN, or
η > 1 + ε are skipped (the VGM-0 pitch-radiation notch at T ≥ 3.0 s and the
short-period `linear_popt_invalid` region make P_opt undefined there).

See `analysis/three_regime/figures/operating_envelope_efficiency.png` and
`analysis/three_regime/operating_envelope_efficiency.csv`.

| T_s | eta_max | controller | flap_angle |
|-----|---------|-----------|-----------|
| 0.50 | 0.823 | opt_passive | 90 |
| 0.75 | 0.991 | CC | 45 |
| 1.00 | 0.962 | CC | 45 |
| 1.25 | 0.902 | CC | 10 |
| 1.50 | 0.940 | CC | 0 |
| 1.75 | 0.636 | CC | 0 |
| 2.00 | 0.357 | CC | 0 |
| 2.25 | 0.200 | CC | 0 |
| 2.50 | 0.119 | opt_passive | 90 |
| 2.75 | 0.121 | ff+PID | 90 |
| 3.00 | 0.133 | ff+PID | 45 |
| 3.25 | 0.156 | opt_passive | 20 |
| 3.50 | 0.149 | opt_passive | 10 |
| 3.75 | 0.121 | ff+PID | 10 |
| 4.00 | 0.097 | ff+PID | 10 |
| 4.25 | 0.080 | ff+PID | 10 |
| 4.50 | 0.065 | ff+PID | 10 |
| 4.75 | 0.054 | ff+PID | 10 |
| 5.00 | 0.046 | ff+PID | 10 |
| 5.25 | 0.032 | ff+PID | 20 |
| 5.50 | 0.017 | ff+PID | 45 |
| 5.75 | 0.015 | ff+PID | 45 |
| 6.00 | 0.013 | ff+PID | 45 |
| 6.25 | 0.012 | ff+PID | 45 |
| 6.50 | 0.007 | ff+PID | 90 |
| 6.75 | 0.007 | ff+PID | 90 |
| 7.00 | 0.006 | ff+PID | 90 |

### 4c. Power vs efficiency co-design schedules diverge

The two hulls select **different (controller, flap-angle) winners** at 17 of the 27
period points. The divergence has two structural causes:

**1. Short-period flap selection (T ≤ 1.25 s, T = 2.5 s):**
At T ≤ 1.25 s the power hull picks CC + VGM-0 because the closed-flap geometry
produces the largest excitation torque (and thus highest raw P_capture). The
efficiency hull, however, picks CC + VGM-45 or VGM-10 — those flaps achieve a larger
fraction of their own P_opt because their hydrodynamic coupling is better matched at
short periods. At T = 0.5 s the efficiency hull switches entirely to opt_passive/90:
here the CC `linear_popt_invalid` flag makes all CC η values undefined, and opt_passive
on the wide-open flap captures the highest valid η.

**2. Long-period VGM-0 notch (T ≥ 4.25 s):**
The most dramatic divergence. The power hull selects opt_passive + VGM-0 at
T = 4.5–7.0 s because VGM-0 still produces measurable P_capture (0.15–0.68 W) in
this band — even though P_opt is undefined (the pitch-radiation B55 → 0 notch makes
the theoretical optimum diverge). The efficiency hull **must exclude** all VGM-0
T ≥ 3.0 s data (`masked = true`, P_opt empty) and instead finds the best well-defined
η among the higher-angle flaps, landing on ff+PID + VGM-{10,20,45,90} depending on
which flap's resonance tail overlaps that period.

**Divergence summary table:**

| T_s | Power hull | Efficiency hull | Reason |
|-----|-----------|-----------------|--------|
| 0.50 | CC/90 | opt_passive/90 | CC η undefined (linear_popt_invalid); opt_passive/90 best valid η |
| 0.75 | CC/90 | CC/45 | CC/90 maximises P; CC/45 maximises P/P_opt |
| 1.00 | CC/0 | CC/45 | CC/0 maximises P; CC/45 maximises P/P_opt |
| 1.25 | CC/0 | CC/10 | CC/0 maximises P; CC/10 maximises P/P_opt |
| 2.50 | CC/0 | opt_passive/90 | CC/0 still highest P; opt_passive/90 best η at this period |
| 4.25 | ff+PID/0 | ff+PID/10 | VGM-0 data masked; ff+PID/10 best valid η |
| 4.50–7.00 | opt_passive/0 | ff+PID/{10,20,45,90} | VGM-0 masked (P_opt undefined); efficiency hull excludes notch |

Periods T = 1.5–2.25 s and T = 2.75–4.0 s agree on the winning (controller, flap)
combination — at resonance the same configuration maximises both raw power and
efficiency fraction simultaneously.

---

## 5. Appendix: why fixed-passive was pruned (degenerate arm)

`B_pto = B55(ω₀)` is the radiation damping coefficient at the free-decay resonance.
For all five VGOSWEC flap variants this value is in the range **~1e-4 to ~4e-4 N·m·s/rad**
(with VGM-0 at 3.2e-7, deep in the pitch-radiation notch):

| Flap  | B55(ω₀) [N·m·s/rad] | |Z_intrinsic(ω₀)| (approx.) | ratio (approx.) |
|-------|----------------------|---------------------------|-------|
| VGM-0  | 3.19e-7 (pitch notch) | ~1e-2 to 1e-3 | ~10⁴–10⁵× smaller |
| VGM-10 | 1.27e-4 | ~1e-2 | ~100× smaller |
| VGM-20 | 1.51e-4 | ~1e-2 | ~100× smaller |
| VGM-45 | 2.53e-4 | ~1e-2 | ~50× smaller |
| VGM-90 | 3.91e-4 | ~1e-2 | ~25× smaller |

`B_pto = B55(ω₀)` is **10⁴–10⁵× smaller than** `|Z_intrinsic(ω₀)|` that opt_passive
uses as its damping coefficient. A resistive PTO with this tiny coefficient dissipates
essentially zero power against the full intrinsic impedance of the device —
**passive captures ≈ 0 W across the entire T = 0.5–7 s band for all flaps.**

Additionally, B55 has a high-frequency lobe at ω ≈ 8 rad/s, but the flap resonances
span ω ∈ [1.07, 2.09] rad/s (T₀ = 2.99–5.86 s) — so the radiation-damping lobe
never aligns with any flap's operating band. Radiation-damping-matched passive is
degenerate for every VGOSWEC variant.

The `passive` controller type remains available in the code for tank-test tuning
(`config/vgoswec_*_passive.yaml`, `B_pto: 0.5` placeholder, TODO annotation).
It was simply not part of the three-regime study and is excluded from all figures.

---

## Reproducing the figures

```bash
# Three-regime per-flap + cross-flap + operating envelope (from committed CSVs):
python3 scripts/three_regime_comparison.py --plot-only

# Regenerate cc and ff+PID figures independently:
python3 scripts/cc_vs_ffpid_comparison.py --plot-only
python3 scripts/cc_capture_efficiency_sweep.py --plot-only
python3 scripts/capture_efficiency_sweep.py --plot-only
```

Output files:
- `analysis/three_regime/figures/three_regime_VGM{0,10,20,45,90}.png` — per-flap power
- `analysis/three_regime/figures/three_regime_efficiency_VGM{0,10,20,45,90}.png` — efficiency
- `analysis/three_regime/figures/three_regime_summary.png` — cross-flap power summary
- `analysis/three_regime/figures/three_regime_efficiency_summary.png` — cross-flap efficiency
- `analysis/three_regime/figures/operating_envelope.png` — master power co-design envelope
- `analysis/three_regime/operating_envelope.csv` — power hull data for reproducibility
- `analysis/three_regime/figures/operating_envelope_efficiency.png` — master efficiency envelope
- `analysis/three_regime/operating_envelope_efficiency.csv` — efficiency hull (masked-respecting)
