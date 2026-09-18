# Results campaign — 2026-09-17

**Scope:** free-decay plant validation of the C++ VGOSWEC model.
**Outcome:** free-decay validation stage **closed**. No C++ model change indicated.

This document is the campaign record for the 2026-09-17 free-decay work. It
captures what was re-run, what changed, what was discovered, and what remains
as follow-up. The physics conclusions live in:

- [`docs/freedecay_wecsim_rawdata_validation.md`](freedecay_wecsim_rawdata_validation.md) — **primary** ω_n / ζ reference (WEC-Sim raw `.mat` vs C++)
- [`docs/freedecay_validation.md`](freedecay_validation.md) — full free-decay validation narrative, Table 2 / Fig. 4 comparisons

---

## Summary

The free-decay stage previously rested on comparison against the **published
paper's Table 2 and Fig. 4** (Ogden et al., ASME JOMAE 145(3):030905). Table 2
is rounded; the Fig. 4 comparison required reading a decay envelope off a
plotted figure. Both are once-removed from the original data.

During this campaign the owner located the **original WEC-Sim `.mat` free-decay
outputs** used to produce that paper. This enabled a direct
solver-output-to-solver-output comparison, which is now the primary reference
for both metrics.

| Metric | C++ vs WEC-Sim raw data | C++ vs paper Table 2 |
|---|---:|---:|
| ω_n | **within ±0.15%** | within ±0.9% |
| ζ | **within ~4–13%** | ~9–13× discrepancy |

The Table 2 ζ discrepancy is **not** a C++-vs-WEC-Sim disagreement — both
solvers agree with each other on the raw data. It is a discrepancy between the
raw free-decay physics (as computed by either solver) and the value printed in
the paper's Table 2, consistent with a `×10⁻³` vs `×10⁻⁴` exponent labeling
issue in that column.

> **MATLAB / WEC-Sim work is complete.** The raw-data extraction described in
> S3 closes the MATLAB side of the validation. No further WEC-Sim `.mat`
> processing is planned; subsequent campaigns are C++-only.

---

## S1. Record-length harmonization (40–60 s → 200 s)

### Problem

The free-decay configs carried inconsistent record lengths, with
`config/vgoswec_0_freedecay.yaml` at:

```yaml
duration: 60.0       # [s] >= 5×Ts ≈ 29 s to observe several free-decay cycles
```

The `5×Ts` rationale is sound for *observing* decay, but it produced two
problems:

1. **FFT bin-resolution collision.** For a ~55 s record, `Δω ≈ 0.11 rad/s` per
   bin. VGM-10 (≈1.46 rad/s) and VGM-20 (≈1.56 rad/s) are separated by roughly
   one bin, so naive FFT peak-picking placed both in the same bin and returned
   an identical `1.517 rad/s` for the two geometries. Zero-crossing separated
   them correctly, but the FFT column was visibly wrong.
2. **Not comparable to Fig. 4.** The paper's Fig. 4 envelope spans ~200 s. Log
   decrementing a 60 s C++ record against a 200 s figure envelope is not an
   apples-to-apples read.

### Change

All five configs harmonized to:

```yaml
duration: 200.0      # [s] matches paper Fig. 4 record length
```

Timestep unchanged at `dt = 0.005 s`.

### Result

FFT and zero-crossing now resolve VGM-10 and VGM-20 as distinct under both
estimators. The Fig. 4 envelope comparison became a like-for-like read.

> **Note:** the config change was made during the campaign but was not committed
> until 2026-09-17 (`config: harmonize free-decay record length to 200 s across
> all geometries`). Between the campaign and that commit, the repository
> documented a 200 s campaign while `config/` still specified 60 s — a clean
> checkout would have regenerated the superseded short records. Resolved.

---

## S2. Result set — 200 s standard config

Commit `3717147`, `CHRONO_FLAVOR=v10`, `dt = 0.005 s`, 200 s records.

| Config | C++ ZC ω_n [rad/s] | C++ FFT ω_n [rad/s] | C++ ζ×10⁻⁴ |
|---|---:|---:|---:|
| VGM-0  | 1.066 | 1.079 | 52.8 |
| VGM-10 | 1.460 | 1.460 | 38.1 |
| VGM-20 | 1.557 | 1.555 | 47.5 |
| VGM-45 | 1.823 | 1.840 | 36.7 |
| VGM-90 | 2.083 | 2.094 | 28.6 |

These are now the embedded fallback constants in
`scripts/freedecay_analysis.py`.

> ⚠️ **VGM-0 ζ provenance trap.** The previous embedded value was `49.9×10⁻⁴`,
> which is the **refined-timestep** (`dt = 0.0005 s`) result, not the
> standard-config one. Mixing a sensitivity-check value into the standard
> result table understated VGM-0 ζ by ~5%. The standard-config value is
> **52.8×10⁻⁴**. The refined-timestep result is retained in
> `docs/freedecay_validation.md` as a numerical-dissipation sensitivity check
> only and must not be mixed into the standard table.

---

## S3. WEC-Sim raw-data extraction

Source: `FreeDecay_vg{1..5}_intAng1.mat` (owner-supplied original study data;
**not committed** to this repository).

- Time vector: `output.wave.time`
- Pitch signal: `output.bodies(1).position(:,5)`

Four independent frequency estimators were computed per geometry (FFT bin max,
FFT with parabolic interpolation, zero-crossing median, damped-sinusoid
least-squares fit). The first three agreed to better than 0.1%; the damped fit
ran systematically ~0.3–0.5% high and was retained as a ζ diagnostic and
frequency cross-check only.

Full method, per-geometry tables, and the MATLAB-side gotchas are in
[`docs/freedecay_wecsim_rawdata_validation.md`](freedecay_wecsim_rawdata_validation.md).

**This completes the MATLAB/WEC-Sim validation work.** The extracted reference
values are now embedded as constants in `scripts/freedecay_validation.py`, so
the comparison is reproducible from this repository without re-running any
MATLAB.

---

## S4. Tooling hardening

Following the campaign, `scripts/freedecay_validation.py`,
`scripts/freedecay_analysis.py`, and `scripts/plot_freedecay_validation.py` were
updated so the readout cannot drift out of sync with the data again:

- **Computed tolerance bounds.** The `±0.6%` ω_n claim was hardcoded in a print
  statement (and was an f-string interpolating nothing). All headline bounds are
  now derived from the analyzed rows.
- **Provenance tracking.** The per-angle `csv` vs `fallback` source is now shown
  in the console table, printed as an explicit warning block, and persisted as a
  `source` column in `docs/freedecay_validation.csv`.
- **`--strict` flag.** Exits non-zero if any geometry falls back to embedded
  values.
- **`--run` failure propagation.** `_run_simulation()`'s return value is no
  longer discarded; captured stderr is surfaced on failure.
- **WEC-Sim reference constants** added, with a new comparison table and
  computed `±0.15%` / `~4–13%` headline bounds.
- **LF line endings** for `docs/freedecay_validation.csv` via an explicit
  `lineterminator="\n"` on the `csv.DictWriter`.

---

## Verification

```bash
python3 scripts/freedecay_validation.py --make-figures --paper-fig-zeta
python3 scripts/plot_freedecay_validation.py
```

Confirmed on 2026-09-17:

1. ω_n tolerance line prints a **computed** ±0.9% against Table 2 — not the
   stale hardcoded ±0.6%.
2. `Source` column reads `csv` for all five geometries.
3. WEC-Sim comparison table prints with computed headline bounds of **±0.15%**
   (ω_n) and **~4–13%** (ζ).
4. Removing `output/vgoswec_20_freedecay_results.csv` produces a visible
   `VGM-20 (fallback)` warning, writes `source=fallback` for that row, and
   `--strict` exits `1`.

---

## Follow-up items

None of these block the free-decay stage. All are tracked here for the record.

1. **VGM-20 above-trend ζ.** Both raw datasets place VGM-20 ζ above its
   neighbours (WEC-Sim 53.5, C++ 47.5, vs VGM-10 at 42.4/38.1 and VGM-45 at
   42.0/36.7), breaking the otherwise monotonic 0°→90° decrease. Because it
   appears in **both independently-processed** datasets it is most plausibly
   physical — a hydrodynamic-coupling feature of the 20° geometry — rather than
   an extraction artifact. Worth a closer look before publication.
2. **`--strict` writes artifacts before failing.** A `--strict` run that detects
   fallback rows still writes `docs/freedecay_validation.csv` before exiting
   non-zero, leaving a `source=fallback` row in the tracked CSV. It should
   refuse to write artifacts at all.
3. **`[impedance] INFO: legacy A55-match rho=...` log spam.** This was being
   printed on repeated hydro lookups despite being a static property of the H5
   file. Purely log noise — the printed value is a diagnostic, not an input to
   any computation. Carried over from `docs/EOD_SUMMARY_2026-09-16.md`.
4. **Vestigial `hydro.rho` key in `config/*.yaml`.** The configs carry
   `rho = 1025 kg/m³`, parsed into `SimConfig::rho` by `config_loader.cpp`, but
   nothing downstream consumes it. De-normalization is pinned to the H5-stored
   `rho` (see "Density basis" below). The key is dead config and is misleading
   on inspection; either remove it or comment it as unused.

### Resolved during this campaign

- **Silent fallback substitution** — the analysis script substituted hardcoded
  historical values when a result CSV was missing or unreadable, with no
  indication in the output or the CSV. Now surfaced via the `source` column,
  an explicit warning block, and `--strict` (see S4).
- **CRLF line endings in `docs/freedecay_validation.csv`** — Python's
  `csv.writer` defaults to `lineterminator="\r\n"` per RFC 4180, which reached
  the worktree unmodified on Linux. Fixed by passing `lineterminator="\n"`.
  (Git had been normalizing to LF on the way into the index, so the committed
  blob was always correct; the CRLF was a worktree-only artifact.)
- **`docs/freedecay_validation.csv` was untracked** — `.gitignore` carried a
  blanket `*.csv` with un-ignore exceptions only under `analysis/**`, so the
  summary CSV listed as a pipeline artifact in `docs/REPRODUCTION.md` had never
  been committed. A `!docs/*.csv` exception was added and the CSV is now
  tracked.

---

## Density basis (`rho`) — verified correct

Checked during this campaign and recorded here so it is not re-raised as an
issue.

De-normalization of the BEM coefficients uses the `rho` **stored in the H5
file** (`simulation_parameters/rho`, = 1000 kg/m³ for the VGM BEM runs) as the
single source of truth:

```cpp
// src/impedance.cpp
double rho_eff = tables.h5_rho;   // active
```

`A55`, `B55`, and `Fexc55` are all formed from `rho_eff`, and the Python sweep
scripts read `rho` from each H5 the same way. This is the correct basis: the
BEM coefficients were computed at that density, so de-normalizing with it
recovers the dimensional values consistently, and it puts all five geometries
on one basis.

The `rho_eff_match` / `rho_legacy` value printed in the hydro diagnostic is a
**diagnostic back-out only** — an RIRF-derived estimate of the density implied
by the added-mass tables, used to confirm the de-normalization still
reconciles. It is explicitly labelled as such in `impedance.h` and is never
used in any computation:

```cpp
double rho_eff_match; ///< Legacy RIRF-derived rho (diagnostic only, not used)
```

The `rho = 1025` in `config/*.yaml` is a vestigial key with no consumer (see
follow-up item 4). **There is no density inconsistency in the physics, and
`P_opt` is on the correct basis.**

---

## Status

**The free-decay validation stage is closed.**

Both plant impedance components are validated against the original WEC-Sim raw
time histories: the reactive impedance (ω_n, driven by A55 and hinge stiffness)
to within ±0.15%, and the resistive impedance (ζ, i.e. radiation damping B55)
to within ~4–13%. This is the foundation the three-regime controller/flap
co-design study rests on.

The MATLAB/WEC-Sim side of the validation is likewise complete; the reference
values are embedded in the repository and require no further `.mat` processing.

Next: the passive campaign.
