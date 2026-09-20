# Three-Regime Relay — Key Findings

Controller co-design study across VGOSWEC flap variants (VGM-0/10/20/45/90) over
**T = 0.5–7.0 s** (0.25 s steps, H = 0.05 m). Three controllers:

- **CC** — complex-conjugate (reactive) control.
- **opt_passive** — optimal resistive damping, `B_opt = |Z_intrinsic(ω₀)|`.
- **ff+PID** — tuned excitation-feedforward + PID (`exc_ff_pid`), the `passive_guarded` arm.

All results are reproducible from committed CSVs under
`analysis/{cc,opt_passive,passive_guarded}/` via `--plot-only`. No solver runs required.

> **Basis-correction note (2026-09-19 follow-up):** all three controller trees now
> carry hinge-referenced hydro-derived columns (`B55_Nmsrad`, `F_exc_Nm`, `P_opt_W`,
> `eta`, `masked`) via `scripts/retabulate_hydro_columns.py --verify`. This removes
> the mixed CG-vs-hinge efficiency comparison that previously distorted the
> three-regime efficiency hull. The power hull, which depends only on `P_capture_W`,
> is unchanged when comparing pre- and post-retabulated input CSVs; the efficiency
> hull is the quantity that materially changes.

> **Method-unification status note (important):** the committed **CC** and
> **ff+PID** numbers in this file predate the shared sweep-method unification.
> Code and docs now target the common method documented in
> [`../docs/SWEEP_METHOD.md`](../docs/SWEEP_METHOD.md), but the owner still needs
> to re-run those two campaigns. Until that rerun lands, treat CC / ff+PID
> numerical values here as the pre-unification record rather than silently fresh
> campaign output.

> **Validated-plant foundation:** The controller/flap co-design results below
> rest on the free-decay WEC-Sim plant validation in
> [`../docs/freedecay_validation.md`](../docs/freedecay_validation.md), which
> verifies both the reactive plant impedance (**ω_n**) and the resistive
> radiation-damping response (**ζ / B55**) across VGM-0/10/20/45/90.

---

## 1. Regenerated hull schedule (updated headline result)

With every efficiency number on the same hinge-referenced basis, the repository-wide
headline is no longer a clean **CC → opt_passive → ff+PID** relay. The regenerated
operating envelopes now read:

| Period band | Power-hull winner | Efficiency-hull winner | Notes |
|--------|-------------|--------|-------|
| **0.50 s** | **CC / VGM-0** | **opt_passive / VGM-90** | CC maximises raw power; opt_passive has the best normalized η |
| **0.75 s** | **CC / VGM-90** | **opt_passive / VGM-0** | Same low-period normalization split |
| **1.00–1.25 s** | **CC** | **CC** | Efficiency prefers a different CC flap than raw power |
| **1.50–2.50 s** | **CC / VGM-0** | **CC / VGM-0** | CC owns both hulls through the short-period band |
| **2.75–4.50 s** | **ff+PID** | **ff+PID** | ff+PID owns the mid-band hull after the basis fix |
| **4.75–5.25 s** | **opt_passive / VGM-0** | **opt_passive / VGM-0** | Narrow VGM-0 window where tuned passive retakes both hulls |
| **5.50–6.75 s** | **ff+PID / VGM-0** | **ff+PID / VGM-0** | ff+PID carries most of the long tail |
| **7.00 s** | **opt_passive / VGM-0** | **opt_passive / VGM-0** | Final single-point opt_passive re-entry |

The co-design point remains: no single controller or single flap reaches the full
upper hull. What changed is **which controller owns the shared efficiency hull once
all three arms are compared on a common basis**.

---

## 2. Resonance-band comparison after the basis correction

At each flap’s intrinsic resonance period T₀, the current committed campaigns give:

| Flap | T₀ | opt_passive P_capture | ff+PID P_capture | opt_passive η | ff+PID η | winner at resonance |
|------|--------|------------------|------------------|---------------|-----------|---------------------|
| VGM-90 | 2.50 s | 0.200 W | 0.447 W | 0.046 | 0.104 | ff+PID |
| VGM-45 | 3.00 s | 0.363 W | 0.625 W | 0.076 | 0.131 | ff+PID |
| VGM-20 | 3.25 s | 0.276 W | 0.708 W | 0.056 | 0.144 | ff+PID |
| VGM-10 | 3.50 s | 0.325 W | 0.741 W | 0.064 | 0.147 | ff+PID |
| VGM-0  | 4.75 s | 0.607 W | 0.474 W | 0.110 | 0.086 | opt_passive |

The resonance hump monotonically shifts from T ≈ 2.5 s (VGM-90, flap fully open)
to T ≈ 4.75 s (VGM-0, flap closed). This confirms that the intrinsic resonance
T₀ = 2π/ω₀ indeed marches as the flap geometry changes — the hydrodynamic coupling
(radiation damping B55, added inertia A55) all shift together with the flap angle.

### Revised opt_passive vs ff+PID framing

The basis-corrected envelopes do **not** support the older claim that opt_passive
generally ties or beats ff+PID at resonance. In the current committed campaigns:

- **ff+PID wins the resonance-period comparison for VGM-90/45/20/10**, on both raw
  captured power and normalized efficiency.
- **opt_passive wins the VGM-0 resonance point** (`T = 4.75 s`) and also the adjacent
  `T = 5.00–5.25 s` envelope points.
- Beyond that narrow VGM-0 window, **ff+PID carries most of the long tail** on both
  the power and efficiency hulls.

---

## 3. CC validates the Budal bound (short periods)

CC still anchors the short-period band. Both regenerated hulls are CC-led from
**T = 1.0 s through T = 2.5 s**, and the power peak is **2.44488972 W at T = 1.5 s**
for VGM-0.

After the hinge-basis retabulation, the CC CSVs still contain **14 rows with
η > 1 + 1e-6**. Those rows are now treated honestly as reported findings — not
silently masked away — and they continue to be excluded from the efficiency hull by
the existing `eta > 1 + ε` validity rule.

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
- **Short T (1.0–2.5 s):** CC, mostly VGM-0 after the first two points
- **Mid-band (2.75–4.5 s):** ff+PID, with the winning flap marching 90° → 45° → 10° → 0°
- **VGM-0 shoulder (4.75–5.25 s):** opt_passive + VGM-0
- **Long tail (5.5–6.75 s):** ff+PID + VGM-0, before a final opt_passive/0 re-entry at 7.0 s

No single controller or flap reaches this envelope alone.

| T_s | P_max_W | controller | flap_angle |
|-----|---------|-----------|-----------|
| 0.50 | 0.3169 | CC | 0 |
| 0.75 | 0.5837 | CC | 90 |
| 1.00 | 1.5284 | CC | 10 |
| 1.25 | 1.9995 | CC | 0 |
| 1.50 | 2.4449 | CC | 0 |
| 1.75 | 2.1683 | CC | 0 |
| 2.00 | 1.4413 | CC | 0 |
| 2.25 | 0.9138 | CC | 0 |
| 2.50 | 0.5886 | CC | 0 |
| 2.75 | 0.5467 | ff+PID | 90 |
| 3.00 | 0.6316 | ff+PID | 45 |
| 3.25 | 0.7221 | ff+PID | 10 |
| 3.50 | 0.7413 | ff+PID | 10 |
| 3.75 | 0.6291 | ff+PID | 10 |
| 4.00 | 0.5114 | ff+PID | 10 |
| 4.25 | 0.4418 | ff+PID | 0 |
| 4.50 | 0.4813 | ff+PID | 0 |
| 4.75 | 0.6074 | opt_passive | 0 |
| 5.00 | 0.6850 | opt_passive | 0 |
| 5.25 | 0.4755 | opt_passive | 0 |
| 5.50 | 0.3135 | ff+PID | 0 |
| 5.75 | 0.2613 | ff+PID | 0 |
| 6.00 | 0.2172 | ff+PID | 0 |
| 6.25 | 0.1809 | ff+PID | 0 |
| 6.50 | 0.1521 | ff+PID | 0 |
| 6.75 | 0.1288 | ff+PID | 0 |
| 7.00 | 0.1250 | opt_passive | 0 |

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
| 0.50 | 0.813 | opt_passive | 90 |
| 0.75 | 0.862 | opt_passive | 0 |
| 1.00 | 0.945 | CC | 90 |
| 1.25 | 0.941 | CC | 10 |
| 1.50 | 0.965 | CC | 0 |
| 1.75 | 0.697 | CC | 0 |
| 2.00 | 0.399 | CC | 0 |
| 2.25 | 0.227 | CC | 0 |
| 2.50 | 0.135 | CC | 0 |
| 2.75 | 0.118 | ff+PID | 90 |
| 3.00 | 0.131 | ff+PID | 45 |
| 3.25 | 0.147 | ff+PID | 10 |
| 3.50 | 0.147 | ff+PID | 10 |
| 3.75 | 0.122 | ff+PID | 10 |
| 4.00 | 0.097 | ff+PID | 10 |
| 4.25 | 0.082 | ff+PID | 0 |
| 4.50 | 0.088 | ff+PID | 0 |
| 4.75 | 0.110 | opt_passive | 0 |
| 5.00 | 0.123 | opt_passive | 0 |
| 5.25 | 0.085 | opt_passive | 0 |
| 5.50 | 0.055 | ff+PID | 0 |
| 5.75 | 0.046 | ff+PID | 0 |
| 6.00 | 0.038 | ff+PID | 0 |
| 6.25 | 0.032 | ff+PID | 0 |
| 6.50 | 0.026 | ff+PID | 0 |
| 6.75 | 0.022 | ff+PID | 0 |
| 7.00 | 0.022 | opt_passive | 0 |

### 4c. Power vs efficiency co-design schedules diverge

The two hulls now select different `(controller, flap-angle)` winners at only **4 of
the 27** period points: **T = 0.50, 0.75, 1.00, 1.25 s**.

That divergence is now entirely a **short-period normalization effect**:

- At **0.50 s** and **0.75 s**, CC still maximises raw captured power, but
  opt_passive has the larger well-defined `η = P_capture / P_opt`.
- At **1.00 s** and **1.25 s**, both hulls stay within CC, but the efficiency hull
  prefers a different flap angle than the power hull.

Every period from **1.50 s onward** now has the **same controller winner** on both the
power and efficiency hulls.

| T_s | Power hull | Efficiency hull | Reason |
|-----|-----------|-----------------|--------|
| 0.50 | CC/0 | opt_passive/90 | CC maximises raw power; opt_passive/90 has the best valid η |
| 0.75 | CC/90 | opt_passive/0 | CC maximises raw power; opt_passive/0 has the best valid η |
| 1.00 | CC/10 | CC/90 | Same controller, different flap for P vs P/P_opt |
| 1.25 | CC/0 | CC/10 | Same controller, different flap for P vs P/P_opt |

---

## 5. Appendix: why fixed-passive is dominated off resonance

`B_pto = B55(ω₀)` is the radiation damping coefficient at the free-decay resonance.
For all five VGOSWEC flap variants this value is in the range **~1e-4 to ~4e-4 N·m·s/rad**
(with VGM-0 at 3.2e-7, deep in the pitch-radiation notch):

| Flap  | B55(ω₀) [N·m·s/rad] | |Z_intrinsic(ω₀)| (approx.) | ratio (approx.) |
|-------|----------------------|-----------------------------|-----------------|
| VGM-0  | 3.19e-7 (pitch notch) | ~1e-2 to 1e-3 | ~10⁴–10⁵× smaller |
| VGM-10 | 1.27e-4 | ~1e-2 | ~100× smaller |
| VGM-20 | 1.51e-4 | ~1e-2 | ~100× smaller |
| VGM-45 | 2.53e-4 | ~1e-2 | ~50× smaller |
| VGM-90 | 3.91e-4 | ~1e-2 | ~25× smaller |

This is why fixed-passive is the **retained non-adaptive lower bound**, not why it
is discarded. Because `B_pto = B55(ω₀)` is far smaller than the off-resonant
`|Z_intrinsic(ω)|` values that govern the tuned `opt_passive` arm, fixed-passive
is expected to be **dominated away from resonance**. That is exactly what the
committed passive CSVs now show:

- at **VGM-10, `T = 3.25 s`**, passive reaches about **12%** while `opt_passive`
  reaches about **15.5%**;
- at **VGM-90, `T = 0.50 s`**, passive reaches about **10.7%** while
  `opt_passive` reaches about **85.5%**.

Near resonance the gap can be modest; off resonance it can be dramatic. That is
the useful physics of the passive arm: it quantifies the cost of **not**
retuning the resistive load with wave period.

Additionally, B55 has a high-frequency lobe at ω ≈ 8 rad/s, but the flap resonances
span ω ∈ [1.07, 2.09] rad/s (T₀ = 2.99–5.86 s) — so the radiation-damping lobe
never aligns with any flap's operating band. So radiation-damping-matched
passive remains a structurally weak choice for this device family except close
to its own design point. That is why `opt_passive` and the adaptive arms own the
envelope, while fixed-passive remains the honest non-adaptive comparator.

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
