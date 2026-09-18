# Project State — Session Handoff

**Last updated: 2026-09-18** · Refresh this file at each phase boundary so any new session can resume exactly here.

---

## 1. Current status — resume banner

The **simulation phase is complete** — see [`docs/EOD_SUMMARY_2026-07-11.md`](EOD_SUMMARY_2026-07-11.md) for the formal phase-close record. The project is now entering the **paper / writing phase**.

The **free-decay validation stage is closed** as of 2026-09-17, and with it the **MATLAB / WEC-Sim validation work**. The WEC-Sim reference values are embedded as constants in `scripts/freedecay_validation.py`, so no further `.mat` processing is required — subsequent campaigns are C++-only. See [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md).

---

## Recent sessions / campaign record

- [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md) — free-decay closure record, authoritative handoff for the 200 s WEC-Sim-raw-data validation campaign.
- [`docs/EOD_SUMMARY_2026-09-16.md`](EOD_SUMMARY_2026-09-16.md) — immediately preceding end-of-day summary leading into the final free-decay closure work.

---

## 2. What is done (link — do not re-derive)

- **Plant validation (foundation):** primary reference is now the direct WEC-Sim raw-time-history comparison, with C++ 200 s free-decay records agreeing on **ω_n within ±0.15%** and **ζ within ~4–13%** across VGM-0/10/20/45/90. Both solvers place ζ in the 25–55×10⁻⁴ range; the paper's Table 2 ζ column is uniformly ~9–13× lower, consistent with a `×10⁻³`/`×10⁻⁴` exponent labeling issue in that table rather than a modeling error in either solver. Primary reference: [`docs/freedecay_wecsim_rawdata_validation.md`](freedecay_wecsim_rawdata_validation.md); full narrative: [`docs/freedecay_validation.md`](freedecay_validation.md). **No C++ model change is indicated by the free-decay evidence.**
- **Density basis verified:** BEM de-normalization is correctly pinned to the H5-stored `rho`; the `rho_legacy` figure in the hydro diagnostic is a labelled back-out with no consumer, and `hydro.rho` in `config/*.yaml` is a vestigial unused key. `P_opt` is on the correct basis. See "Density basis" in [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md).
- **Three-regime co-design relay:** CC → opt_passive → ff+PID across VGM-0/10/20/45/90 on shared T = 0.5–7 s grid at H = 0.05 m; resonance slides with flap angle (T₀ 2.99 s @ VGM-90 → 5.86 s @ VGM-0).
- **Dual operating envelopes:** power hull (peak 2.34 W at T = 1.5 s, VGM-0, CC) and mask-respecting efficiency hull (CC near-Budal ~99% at short T); the power and efficiency co-design schedules differ.
- **Reproducibility:** every dataset regenerable from documented commands. See [`docs/REPRODUCTION.md`](REPRODUCTION.md).

---

## 3. Paper plan / positioning

### Working thesis / novelty framing
The contribution is **not** a new control law. Two of the three controllers are textbook-mature:

- **Optimal-passive** (`B_opt = |Z_intrinsic(ω₀)|`, optimal resistive loading) — foundational result; Falnes; covered as the passive baseline in Ringwood's reviews.
- **Complex-conjugate / reactive impedance matching** — the classical theoretical optimum / Budal bound; Falnes, Ringwood 2014. Its non-causality and reactive-power requirements are extensively documented.

The third, **ff+PID** (excitation feedforward + velocity-tracking PID + passive-safety guard), is an engineered causal scheme positioned in the Fusco & Ringwood excitation-feedforward / velocity-reference lineage.

The **real novelty is the controller × variable-geometry (flap-angle) operating map** — the regime relay over (wave period × flap vent angle × controller).

### Honest-framing rules to preserve in the manuscript
- Regime ordering is physically expected → frame as **systematic simulated quantification**, not discovery.
- Fixed-passive is retained as the non-adaptive lower bound: it is dominated by
  `opt_passive` by construction off resonance, and the gap between the two arms
  quantifies the value of frequency-dependent retuning. It is also the only arm
  here that does **not** require wave-frequency knowledge; CC, `opt_passive`,
  and tuned `exc_ff_pid` all do.
  Representative gaps: VGM-10 at `T = 3.25 s` runs about `12%` (`passive`) vs
  `15.5%` (`opt_passive`), while VGM-90 at `T = 0.50 s` runs about `10.7%` vs
  `85.5%`. Physical reading: retuning buys little near resonance and a great
  deal off it.
- ff+PID "ties opt_passive at resonance" — do **not** claim it is universally optimal.
- ff+PID uses **empirical (not formally optimized) gains**; formal gain optimization is the #54 second-paper scope.

### Known limitation to disclose
ff+PID tracks the raw un-hinge-referred pitch excitation with a signed `alpha` absorbing the phase/sign mismatch — see [`docs/CONTROLLERS.md`](CONTROLLERS.md) §Known limitations. Decide in the drafting phase how prominently to disclose this.

### Maturity caveat
The maturity placements above are drawn from general knowledge of the Ringwood / Fusco / Faedo body of work, **not a live citation check**. Every citation and novelty claim **must** be verified against the literature before submission (#50).

---

## 4. Presentation decisions (captured so the talk is reproducible)

- Three control-law block diagrams (opt_passive, CC, ff+PID) share one template: wave → F_exc source, magenta PTO block, summing junction, `G(s)` plant, `D(s)` kinematics feedback.
- **`G(s) = 1/(ms²+cs+k)` is a deliberate schematic simplification** for the talk; the real simulated plant carries frequency-dependent added mass A₅₅(ω) and radiation-damping memory B_rad,55(ω).
- **Do NOT combine all three into one diagram** (too dense) — keep three separate slides or a staged build/morph where only the PTO block changes panel-to-panel. Add a summary slide ("same plant, three PTO laws").
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

1. **Passive-campaign write-up** — carry the measured period-step, timestep, and
   retuning findings into the paper-facing narrative and keep the fixed-passive
   framing honest.
2. **Kick off #50** — deep-research literature review to produce the related-work section skeleton + novelty verdict; this is the gate before any manuscript drafting begins.
3. **Refresh this file** at each subsequent phase boundary (end of lit review, start of drafting, etc.).

### Minor / non-blocking cleanups

Tracked as follow-up items in [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md); none affect results:

- `--strict` writes `docs/freedecay_validation.csv` before exiting non-zero; it should refuse to write artifacts at all.
- Vestigial `hydro.rho` key in `config/*.yaml` has no consumer; remove or comment as unused.
- VGM-20 sits above the ζ trend in **both** raw datasets — most plausibly physical, worth a look before publication.
