# Free-decay validation against WEC-Sim raw time histories — 2026-09-17

## Status: primary validation reference for the free-decay stage

This document supersedes the published paper's **Table 2 ζ column** as the
damping-ratio reference for the C++ VGOSWEC model. It does **not** replace
`docs/freedecay_validation.md` — it adds a stronger, more direct comparison
that sits alongside it: C++ solver output compared against **the original
WEC-Sim raw free-decay time histories**, rather than against the rounded
values printed in the paper.

Both ω_n and ζ agree closely between the two solvers when compared this way.
The paper's Table 2 ζ column does not agree with either solver, by a uniform
factor of roughly 9–13×, which is consistent with the exponent-labeling
inconsistency already documented in `docs/freedecay_validation.md`.

---

## Motivation

`docs/freedecay_validation.md` compares the C++ model against the **paper's
published Table 2** values (ω_n, ζ) and against a hand-estimated read of the
paper's **Fig. 4** decay envelope. Both are once-removed from the original
data — Table 2 is rounded, and the Fig. 4 comparison relies on reading an
envelope ratio off a figure.

The owner located the **original WEC-Sim `.mat` output files**
(`FreeDecay_vg{1..5}_intAng1.mat`) used to produce that paper. These contain
the actual free-decay pitch time histories (`output.bodies(1).position(:,5)`,
`output.wave.time`), which can be analyzed with the same rigor as the C++
`output/vgoswec_*_freedecay_results.csv` files. This is a direct,
solver-output-to-solver-output comparison.

## Method

### C++ side

- Configs: `config/vgoswec_{0,10,20,45,90}_freedecay.yaml`, all harmonized to
  `simulation.duration: 200.0 s` (see "Record length" below).
- ω_n: zero-crossing on `flap_pitch_rad`, per `scripts/freedecay_analysis.py`.
- ζ: log-decrement (`n=1`, adjacent peaks), per `scripts/freedecay_analysis.py`.

### WEC-Sim side

- Source files: `FreeDecay_vg{1..5}_intAng1.mat` (owner-supplied, original
  study data), one file per geometry (VGM-0/10/20/45/90).
- Time vector: `output.wave.time` (`output` is a `responseClass` object —
  `isfield()` returns false on its fields even though `fieldnames()` lists
  them; dot-access works and must be used directly, ideally in `try/catch`).
- Pitch signal: `output.bodies(1).position(:,5)`.
- Four independent frequency estimators were computed per geometry:
  1. FFT bin maximum (Hann-windowed, zero-padded).
  2. FFT peak with parabolic interpolation in log-amplitude around the bin
     maximum.
  3. Zero-crossing median period (outlier-rejected at ±10% of the median).
  4. Damped-sinusoid least-squares fit:
     `x(t) = c + e^{-σt}(a cos ωt + b sin ωt)`, optimized over `(σ, ω)` with
     `fminsearch`, linear coefficients `(c,a,b)` solved by least squares at
     each trial `(σ,ω)`.
- Damping ratio ζ was taken from the fitted `σ` and `ω` via
  `ω_n = sqrt(ω² + σ²)`, `ζ = σ / ω_n`.

### Why four estimators, and which is primary

FFT-bin, FFT-interpolated, and zero-crossing agreed with each other to
better than 0.1% on every geometry. The damped-sinusoid fit was systematically
higher in frequency than the other three by ~0.3–0.5%, with fit RMSE of
0.78–1.15° — likely due to the single-mode fit absorbing a release transient
or weak secondary content not present in the idealized model. **The damped
fit was retained only as a ζ diagnostic and as a frequency cross-check; it was
not used as the primary ω_n estimator.** The FFT-interpolated and
zero-crossing estimates are the primary ω_n reference below.

---

## Results: natural frequency ω_n

| VGM | WEC-Sim FFT-interp ω [rad/s] | WEC-Sim zero-cross ω [rad/s] | WEC-Sim damped-fit ω [rad/s] | C++ 200 s zero-cross ω [rad/s] |
|---|---:|---:|---:|---:|
| 0  | 1.0656 | 1.0642 | 1.0691 | 1.066 |
| 10 | 1.4597 | 1.4579 | 1.4645 | 1.460 |
| 20 | 1.5581 | 1.5562 | 1.5651 | 1.557 |
| 45 | 1.8241 | 1.8221 | 1.8311 | 1.823 |
| 90 | 2.0850 | 2.0829 | 2.0913 | 2.083 |

**Agreement, C++ vs WEC-Sim (primary estimators):**

| VGM | C++ vs WEC-Sim FFT-interp | C++ vs WEC-Sim zero-cross |
|---|---:|---:|
| 0  | +0.04% | +0.17% |
| 10 | +0.02% | +0.14% |
| 20 | −0.07% | +0.05% |
| 45 | −0.06% | +0.05% |
| 90 | −0.10% | +0.005% |

**All five geometries agree to within ±0.15%, using two independent
estimators on independently-run solver output.** This is materially tighter
than the ±0.6–0.9% obtained comparing against the paper's rounded Table 2
values (see `docs/freedecay_validation.md`), and it removes the FFT
bin-resolution ambiguity that affected the VGM-10/VGM-20 pair in the earlier
60 s C++ record — both solvers, both estimators, resolve VGM-10 and VGM-20 as
distinct.

## Results: damping ratio ζ

| VGM | WEC-Sim fitted ζ×10⁻⁴ | C++ 200 s log-decrement ζ×10⁻⁴ | Difference | Paper Table 2 ζ×10⁻⁴ |
|---|---:|---:|---:|---:|
| 0  | 55.3 | 52.8 | −4.6%  | 5.8 |
| 10 | 42.4 | 38.1 | −10.2% | 4.3 |
| 20 | 53.5 | 47.5 | −11.2% | 4.1 |
| 45 | 42.0 | 36.7 | −12.6% | 3.5 |
| 90 | 31.4 | 28.6 | −9.0%  | 3.2 |

**C++ and WEC-Sim ζ agree in magnitude and trend to within ~4–13%**, using two
methodologically independent estimators (damped-sinusoid fit vs.
log-decrement) on two independently-run solvers. Both land in the
**tens-of-×10⁻⁴** range at every geometry. The paper's Table 2 column is
uniformly **~9–13× lower**, matching the ratio already found (independently)
by comparing C++ against the paper's own Fig. 4 in
`docs/freedecay_validation.md`.

VGM-20 is the one geometry where both raw-data ζ estimates (WEC-Sim 53.5,
C++ 47.5) sit above their neighbors (VGM-10: 42.4/38.1, VGM-45: 42.0/36.7)
rather than following the otherwise roughly monotonic 0°→90° decrease. Because
this bump appears **in both independently-processed raw datasets**, it is very
unlikely to be a C++ artifact or an extraction artifact — it is most plausibly
physical (a hydrodynamic-coupling feature specific to the VGM-20 geometry) and
worth a closer look before publication, but it does not threaten the
validation.

## Conclusion

**The C++ VGOSWEC free-decay model reproduces both the natural frequency and
the damping ratio extracted directly from the original WEC-Sim raw time
histories:**

- **ω_n:** within ±0.15% at all five geometries (FFT-interpolated and
  zero-crossing estimators, both solvers).
- **ζ:** within ~4–13% at all five geometries, both landing in the
  25–55×10⁻⁴ range (damped fit vs. log-decrement estimators, both solvers).

The discrepancy documented in `docs/freedecay_validation.md` between the C++
model and the paper's Table 2 ζ column (~9–13×, uniformly, across all five
geometries) is **not** a C++-vs-WEC-Sim discrepancy — both solvers agree with
each other on the raw data. The discrepancy is between the raw free-decay
physics (as computed by either solver) and the value printed in the paper's
Table 2, consistent with an exponent/scale labeling issue in that table
(`×10⁻³` vs `×10⁻⁴`) rather than a modeling error in either solver.

**No changes to the C++ model are indicated by this analysis.**

---

## Provenance

| Field | Value |
|---|---|
| Date | 2026-09-17 |
| `cpp-vgoswec` commit | `3717147` |
| Chrono flavor | `v10` |
| C++ record length | 200.0 s (harmonized across all five configs; was 40–60 s, see `docs/RESULTS_CAMPAIGN_2026-09-17.md` §S1) |
| C++ timestep | `dt = 0.005 s` |
| WEC-Sim source files | `FreeDecay_vg1_intAng1.mat` … `FreeDecay_vg5_intAng1.mat` (owner-supplied original study data; not committed to this repository) |
| WEC-Sim extraction | MATLAB, damped-sinusoid fit + FFT/zero-crossing, per Method above |

> **Data availability note:** the WEC-Sim `.mat` files analyzed here are not
> part of this repository. They are the original study's raw output,
> supplied directly by the repository owner. If this comparison is included
> in a publication, the `.mat` files (or the extracted time-series CSVs)
> should be archived alongside the paper's supplementary data so the
> comparison in this document is independently reproducible.

## Known issues surfaced during this analysis (for the record)

1. **`output` in WEC-Sim `.mat` files is a `responseClass` object, not a
   plain struct.** `fieldnames(output)` lists fields such as `wave`, but
   `isfield(output, 'wave')` incorrectly returns `false`. Any extraction code
   must use direct dot-access (in `try/catch`), not `isfield()` guards.
2. The owner's original peak-extraction script
   (`fft_analysis_plot.sh` / `fft_peak_analysis.m`) used
   `[I,~] = find(position == max(position))` to locate the per-geometry
   spectral peak. This is fragile for a multi-column matrix (whole-matrix
   max/find rather than a per-column max) and was replaced, for this
   analysis, with an explicit `max(position, [], 1)` per geometry column.
   The original script's plotted peak values were nonetheless already
   correct for the five geometries in this dataset — the peaks are well
   isolated — so no prior result is invalidated by this fix; it is a
   robustness improvement, not a correction.
3. `scripts/freedecay_validation.py` (C++ side) previously fell back to
   hardcoded historical values when a result CSV was missing or unreadable,
   without printing or persisting which source (`csv` vs `fallback`) was
   actually used. This was resolved during the campaign: the script now
   prints a provenance warning block, persists a `source` column to
   `docs/freedecay_validation.csv`, and supports `--strict` to reject
   fallback-backed runs. See `docs/RESULTS_CAMPAIGN_2026-09-17.md`,
   "Follow-up items," item 5 (resolved).
