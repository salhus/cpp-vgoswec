# Repository status / handoff (2026-09-20)

This is the primary handoff document for resuming work on `salhus/cpp-vgoswec` from a fresh chat session.

## 1. Project state

For the **three-regime controller-comparison campaign**, the **simulation and data-generation phase is complete**. Remaining work is post-processing interpretation, documentation, and any follow-on analysis.

Committed source CSV trees now present:

- `analysis/cc/` — complex-conjugate controller
- `analysis/opt_passive/` — optimal passive damper
- `analysis/passive/` — fixed passive damper
- `analysis/passive_guarded/` — tuned `exc_ff_pid` (ff+PID)

Each tree contains complete per-flap CSVs for **VGM-0/10/20/45/90**: 5 files per tree, **27 period points** each, covering **T = 0.50 s to 7.00 s in 0.25 s steps**.

Repository verification performed in this checkout:

- `python3 scripts/retabulate_hydro_columns.py --verify`
  - exits `0`
  - reports **0 rows changed** across all 20 CSVs
  - hash-verifies non-target columns
  - reports **`cc: 14`** remaining `eta > 1` findings
- `python3 -m pytest tests/ -q`
  - **44 passed, 40 subtests passed**

`python3 scripts/three_regime_comparison.py --plot-only` is **locally deterministic** in this checkout: two consecutive runs produced byte-identical outputs to each other. However, with the sandbox's freshly installed `matplotlib 3.11.2`, the regenerated PNG bytes did **not** match the committed PNG bytes even though the envelope CSV contents stayed unchanged. Treat the committed **CSVs** as the source of truth; figure-byte reproducibility appears environment-sensitive.

### Important scope caveat

The "complete" claim above applies to the **three-regime comparison campaign** specifically.

Other committed analysis paths still need care before reuse:

- `analysis/comparison/` — derived CC-vs-ff+PID figures only
- `analysis/passive_vs_optpassive/` — derived passive-vs-opt-passive figures only
- `analysis/figures/` — Kp×Kd figure outputs
- `analysis/kpkd_sweep_VGM*.csv` — explicitly documented synthetic tuning-grid data

Those paths were **not** regenerated as part of the hinge-basis correction campaign. In this checkout they do not carry enough committed provenance to independently re-audit the basis from artifacts alone, so they should be treated as convenience outputs, not primary evidence.

## 2. The basis correction

Originally, several hydro-derived post-processing columns were tabulated on a **CG-referenced** impedance basis:

- `B55_Nmsrad`
- `F_exc_Nm`
- `P_opt_W`
- `eta`
- `masked`
- `linear_popt_invalid`

They are now **hinge-referenced**, re-derived by `scripts/retabulate_hydro_columns.py` from `hydroData/hinged_vgoswec_*.h5` **without re-running any simulation**.

Columns that are **simulation outputs** and are **never touched by retabulation**:

- `P_capture_W`
- `P_converted_W`
- `P_injected_W`
- `reactive_cancellation_limited`

Current repository state verifies **14** remaining `cc` rows with `eta > 1`. Earlier correction notes for this campaign reported **34** such rows before the hinge-basis fix, with a maximum near **8.48**; this checkout directly verifies only the post-fix state.

## 3. The 14 remaining `eta > 1` CC rows

These are a **finding, not a bug**.

`P_opt = F_exc^2 / (8 * B55)` is the optimal **passive** absorption reference. The CC controller is **reactive**, so it is not bounded by that passive reference.

Current behavior:

- `scripts/retabulate_hydro_columns.py --verify` reports the rows
- efficiency plots render them with a distinct marker style
- `analysis/three_regime/operating_envelope_efficiency.csv` records when a higher-`eta` CC point was excluded from the hull with `eta_gt1_excluded = true`
- the efficiency hull `max()` intentionally excludes those rows instead of silently masking them

Do **not** add a masking rule to hide them.

## 4. Current headline result

The older repository-wide **CC → opt_passive → ff+PID** relay framing did **not** survive the basis correction.

Current committed hulls from:

- `analysis/three_regime/operating_envelope.csv`
- `analysis/three_regime/operating_envelope_efficiency.csv`

are:

- **CC** owns the short-period power hull through **T = 2.5 s**
  - headline peak: **2.44488972 W at T = 1.5 s, VGM-0**
- **ff+PID** owns most of the mid-band:
  - **T = 2.75–4.5 s**
- **ff+PID** also owns most of the long tail:
  - **T = 5.5–6.75 s**
- **opt_passive** holds a narrow **VGM-0** window at:
  - **T = 4.75–5.25 s**
  - plus **T = 7.0 s**
- **opt_passive** wins the efficiency hull at:
  - **T = 0.50 s**
  - **T = 0.75 s**

At each flap's resonance `T₀`, the committed CSVs show:

- **ff+PID beats opt_passive on VGM-90 / 45 / 20 / 10**
- **opt_passive wins only VGM-0**

For any future restatement, point readers to the two envelope CSVs above rather than to a hand-written table.

## 5. ff+PID guard instrumentation

PR #68 added guard/clip counters in **`src/active_pto.cpp`**.

Important correction: there is **no** `src/excitation_velocity_controller.cpp` in this repository. That was a prior misidentification and wasted debugging time.

The owner-validated measurement carried forward for the three-regime narrative is:

- at **T = 4.50 s**, the ff+PID passive-safety guard fires **15.48%** of steps
- clipping is **0%**

That result is the basis for treating the long-period ff+PID tail as genuine feedforward action rather than the passive-safe dissipative floor. The raw simulation log for that measurement is **not** committed in the repository, so this specific percentage is recorded here as a carried-forward result rather than something re-verifiable from a clean checkout without re-running simulations.

## 6. Closed questions — do not reopen

1. **`config/vgoswec_*_exc_ff_pid.yaml` intentionally do not set `impedance_h5_file`.**
   - This is correct for the excitation-force-based feedback controller.
   - It should continue using the CG-basis `h5_file`.
   - Inline comments were added to the five configs so nobody "fixes" this later.
2. **14 CC rows with `eta > 1`**
   - Accepted as a property of comparing a reactive controller to a passive bound.
   - Not a defect.
3. **The `2.44488972 W` settling check (`430 s` vs `760 s`)**
   - Accepted.
   - The difference is not significant.
4. **The residual `~1.4%` mismatch between analytic `omega_n` and free-decay**
   - Accepted.
   - Too small to matter.

## 7. Verification from a clean checkout

```bash
python3 scripts/retabulate_hydro_columns.py --verify   # exits 0; reports cc: 14 eta>1 findings
python3 -m pytest tests/ -q                            # all pass
python3 scripts/three_regime_comparison.py --plot-only
git diff --stat analysis/
```

What to expect:

- `retabulate_hydro_columns.py --verify`
  - no data drift
  - non-target-column hash verification
  - `cc: 14` remaining `eta > 1` findings
- `pytest`
  - clean pass
- `three_regime_comparison.py --plot-only`
  - should not move either envelope CSV
  - figure PNG byte output may depend on the local plotting stack

### Invariant to preserve

`analysis/three_regime/operating_envelope.csv` depends only on **`P_capture_W`**. Post-processing-only changes must therefore **never** move the power hull.

Historical caveat: the hull *did* change during PR #69, but that happened because the previously committed hull predated the `1263869` sweep rerun. Retabulation itself does **not** touch captured power.

## 8. Suggested next steps

Options for the next session:

- Audit the non-three-regime analysis paths listed above before reusing their figures in any write-up.
- Decide whether the current efficiency-hull exclusion rule for `eta > 1` should remain as-is for publication, even though the rows are now visible and explicitly recorded.
- Revisit `analysis/FINDINGS_3REGIME.md` only if its narrative drifts from the envelope CSVs again; the CSVs should remain authoritative.

## 9. Where to start reading

- **Primary handoff:** `docs/STATUS.md` (this file)
- **Repository overview:** `README.md`
- **Analysis tree map:** `analysis/README.md`
- **Current three-regime narrative:** `analysis/FINDINGS_3REGIME.md`
- **Historical EOD context:** `docs/EOD_SUMMARY_2026-09-19.md`
