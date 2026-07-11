# End of Simulation Phase — 2026-07-11

The cpp-vgoswec VGOSWEC three-controller co-design **simulation phase is formally complete**. The next phase is **research/writing**, starting with the literature-review / related-work gate in issue **#50**.

## 1. Phase outcome / what was accomplished

- **Plant validation (foundation):** The C++ VGOSWEC plant is validated against WEC-Sim / Husain et al. (ASME JOMAE 145(3):030905) across **VGM-0/10/20/45/90**. In [`docs/freedecay_validation.md`](freedecay_validation.md), zero-crossing **ω_n** matches Table 2 within **±0.6%** at every flap angle, with the correct monotonic trend **1.07 → 1.46 → 1.57 → 1.84 → 2.10 rad/s**. The extracted **ζ** values match the paper's own Fig. 4 on a per-geometry basis (roughly **30–50×10⁻⁴**), with the documented finding that Table 2 appears to carry a **×10⁻³/×10⁻⁴ exponent discrepancy**.
- **Three-regime controller co-design relay:** The study is complete across all five flap variants on the shared **T = 0.5–7.0 s** grid at **H = 0.05 m**. The final relay is **CC → opt_passive → ff+PID**: CC wins the short-period band, opt_passive and ff+PID trade the resonance band, and ff+PID / opt_passive carry the long tail depending on objective and flap. [`analysis/FINDINGS_3REGIME.md`](../analysis/FINDINGS_3REGIME.md) and [`scripts/three_regime_comparison.py`](../scripts/three_regime_comparison.py) document the controller×geometry operating map, with flap vent angle sliding resonance from **T₀ = 2.99 s @ VGM-90** to **T₀ = 5.86 s @ VGM-0**.
- **Dual operating envelopes:** The master **power** operating hull is committed in [`analysis/three_regime/operating_envelope.csv`](../analysis/three_regime/operating_envelope.csv), peaking at **2.34 W** at **T = 1.5 s**, **VGM-0**, **CC**. The master **efficiency** hull is committed in [`analysis/three_regime/operating_envelope_efficiency.csv`](../analysis/three_regime/operating_envelope_efficiency.csv): CC reaches near-Budal performance at short periods (up to about **99%**), and the hull is explicitly mask-respecting so no **η > 1** spikes are retained. The key co-design result is that the **power** and **efficiency** schedules diverge at long periods: the power hull favors **VGM-0 + opt_passive** (largest raw excitation), while the efficiency hull favors **ff+PID on more-open flaps** (largest valid fraction of **P_opt**).
- **Honest framing:** Fixed-passive was pruned as a **degenerate** arm, not promoted as a meaningful operating regime. ff+PID is framed honestly as **tying opt_passive at resonance** rather than being universally optimal, and the shipped ff+PID gains are explicitly **empirical**, not formally optimized.
- **Reproducibility:** The simulation side is self-contained and regenerable from this repository via documented commands. [`docs/REPRODUCTION.md`](REPRODUCTION.md) provides the repo-wide dataset index, and [`docs/freedecay_validation.md`](freedecay_validation.md) includes the numbered **build → SEA-Stack free-decay runs → Python analysis** pipeline for the plant-validation foundation.

## 2. Merged PR trail for the phase

Key merged PRs that closed the simulation phase, in order:

- **#31** — ff+PID tuning, passive-safety guard, surface plots, and five-flap configs
- **#35 / #36 / #37** — hinge-referred impedance routing, hydrostatic/gain fixes for true CC, and the T-vs-ω axis correction
- **#49** — passive / opt_passive configs and shared-grid sweeps
- **#52** — three-regime relay consolidation and passive-arm pruning
- **#53** — efficiency operating hull and power-vs-efficiency divergence analysis
- **#55** — free-decay foundation framing and repo-wide reproduction index

## 3. Issue board state at phase close

At simulation-phase close, the board is consolidated to **3 open issues**, one per track:

- **#50** — literature positioning & related-work verification (**next-phase gate** for the first paper)
- **#54** — ff+PID gain optimization (**follow-on / second paper**)
- **#4** — ROS 2 HIL bridge (`RosPTOModel`) (**deployment track, parked**)

Issues closed during consolidation:

- **#29** — completed
- **#30** — completed
- **#41** — completed
- **#9** — consolidated into **#4**

## 4. Next phase

The **simulation phase is complete**. The critical path now shifts to **#50**, the deep-research literature review / related-work verification needed before manuscript drafting. Issues **#54** and **#4** remain future or parallel tracks; they are **not** simulation-phase blockers.
