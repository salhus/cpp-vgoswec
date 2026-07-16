# Project State — Session Handoff

**Last updated: 2026-07-11** · Refresh this file at each phase boundary so any new session can resume exactly here.

---

## 1. Current status — resume banner

The **simulation phase is complete** — see [`docs/EOD_SUMMARY_2026-07-11.md`](EOD_SUMMARY_2026-07-11.md) for the formal phase-close record. The project is now entering the **paper / writing phase**, gated on the literature review in issue **#50**. A presentation of the three control-law block diagrams and the three-regime co-design story was **well received; reviewers want to see the paper**, which is why the writing phase is starting now.

---

## 2. What is done (link — do not re-derive)

- **Plant validation (foundation):** validated vs WEC-Sim / Husain & Ogden et al. (ASME JOMAE 145(3):030905) — ω_n within ±0.6% (Table 2), ζ vs Fig. 4 (~30–50×10⁻⁴); Table 2 ×10⁻³/×10⁻⁴ exponent-discrepancy finding documented. See [`docs/freedecay_validation.md`](freedecay_validation.md).
- **Three-regime co-design relay:** CC → opt_passive → ff+PID across VGM-0/10/20/45/90 on shared T = 0.5–7 s grid at H = 0.05 m; resonance slides with flap angle (T₀ 2.99 s @ VGM-90 → 5.86 s @ VGM-0). See [`analysis/FINDINGS_3REGIME.md`](../analysis/FINDINGS_3REGIME.md) and [`scripts/three_regime_comparison.py`](../scripts/three_regime_comparison.py).
- **Dual operating envelopes:** power hull (peak 2.34 W at T = 1.5 s, VGM-0, CC) and mask-respecting efficiency hull (CC near-Budal ~99% at short T); the power and efficiency co-design schedules diverge at long T — power favors VGM-0 opt_passive (largest excitation); efficiency favors ff+PID on more-open flaps (largest fraction of P_opt). See [`analysis/three_regime/operating_envelope.csv`](../analysis/three_regime/operating_envelope.csv) and [`operating_envelope_efficiency.csv`](../analysis/three_regime/operating_envelope_efficiency.csv).
- **Reproducibility:** every dataset regenerable from documented commands. See [`docs/REPRODUCTION.md`](REPRODUCTION.md).

---

## 3. Paper plan / positioning

### Working thesis / novelty framing
The contribution is **not** a new control law. Two of the three controllers are textbook-mature:

- **Optimal-passive** (`B_opt = |Z_intrinsic(ω₀)|`, optimal resistive loading) — foundational result; Falnes; covered as the passive baseline in Ringwood's reviews.
- **Complex-conjugate / reactive impedance matching** — the classical theoretical optimum / Budal bound; Falnes, Ringwood 2014. Its non-causality and reactive-power requirements are extensively documented in the literature.

The third, **ff+PID** (excitation feedforward + velocity-tracking PID + passive-safety guard), is an engineered causal scheme positioned in the Fusco & Ringwood excitation-feedforward / velocity-reference lineage and the passivity-guarded control literature (Bacelli, Faedo, Ringwood).

The **real novelty is the controller × variable-geometry (flap-angle) operating map** — the regime relay over (wave period × flap vent angle × controller).

### Honest-framing rules to preserve in the manuscript
- Regime ordering is physically expected → frame as **systematic simulated quantification**, not discovery.
- Fixed-passive was pruned as degenerate → do not promote it as a meaningful arm.
- ff+PID "ties opt_passive at resonance" — do **not** claim it is universally optimal.
- ff+PID uses **empirical (not formally optimized) gains**; formal gain optimization is the #54 second-paper scope.

### Known limitation to disclose
ff+PID tracks the raw un-hinge-referred pitch excitation with a signed `alpha` absorbing the phase/sign mismatch — see [`docs/CONTROLLERS.md`](CONTROLLERS.md) §Known limitations. Decide in the manuscript whether to fix hinge-referencing or pre-empt it in the limitations section.

### Maturity caveat
The maturity placements above are drawn from general knowledge of the Ringwood / Fusco / Faedo body of work, **not a live citation check**. Every citation and novelty claim **must** be verified against the actual papers as part of issue **#50** before submission. Do not cite a Ringwood reference without confirming its exact framing.

---

## 4. Presentation decisions (captured so the talk is reproducible)

- Three control-law block diagrams (opt_passive, CC, ff+PID) share one template: wave → F_exc source, magenta PTO block, summing junction, `G(s)` plant, `D(s)` kinematics feedback.
- **`G(s) = 1/(ms²+cs+k)` is a deliberate schematic simplification** for the talk; the real simulated plant carries frequency-dependent added mass A₅₅(ω) and radiation-damping memory B_rad,55(ω) — state this caveat verbally or in a footnote so it does not contradict the WEC-Sim validation.
- **Do NOT combine all three into one diagram** (too dense) — keep three separate slides or a staged build/morph where only the PTO block changes panel-to-panel. Add a summary slide ("same plant G(s), three PTO laws → three operating regimes") with an operating-envelope thumbnail.
- The CC / opt_passive gains are evaluated at a design frequency ω₀ (not general Laplace s) — keep s-vs-ω notation honest in captions and any spoken clarification.

---

## 5. Open tracks / issue board

| Issue | Track | Status |
|-------|-------|--------|
| **#50** | Literature positioning & related-work verification | **First-paper critical path / next action** |
| **#54** | ff+PID gain optimization | Follow-on / second paper |
| **#4** | ROS 2 HIL bridge (`RosPTOModel`) | Deployment track — parked |

**Closed during consolidation:** #29, #30, #41 (completed); #9 (consolidated into #4).

---

## 6. Immediate next actions

1. **Kick off #50** — deep-research literature review to produce the related-work section skeleton + novelty verdict; this is the gate before any manuscript drafting begins.
2. **Refresh this file** at each subsequent phase boundary (end of lit review, start of drafting, etc.).
