# End-of-day summary — 2026-09-18

**Session outcome:** passive / `opt_passive` campaign **closed and committed**;
CC + ff+PID **sweep-method unification landed** (PR #63); both unified campaigns
**launched at end of session and still running**.

This file is written to be self-contained. If the chat session is lost, this
document plus the linked files is sufficient to resume without re-deriving
anything.

---

## 1. Where things stand

| Stage | Status |
|---|---|
| Free-decay validation | **Closed** (2026-09-17) |
| passive / `opt_passive` sweep | **Closed and committed** (0.25 s grid, both arms) |
| Sweep-method unification (code + docs) | **Merged** — PR #63, `36a3cde` |
| CC campaign (unified method) | **Running** — launched end of session |
| ff+PID campaign (unified method) | **Queued behind CC** |
| #50 literature review | Next, after the reruns land |

Remote `main` is at `36a3cde`. Everything below is pushed.

---

## 2. Passive campaign closed

The passive / `opt_passive` sweep completed on the shared `0.25 s` grid for both
arms across all five flaps, and was committed in `4abc04f`.

Two things were resolved along the way:

1. **`analysis/passive/*.csv` had never been tracked.** `.gitignore` carried a
   blanket `*.csv` with per-directory un-ignore exceptions, and
   `analysis/passive/` had no exception. The negations are now recursive
   (`!analysis/**/*.csv`, `!analysis/**/*.png`), so new campaign directories are
   tracked by default.
2. **The long-period `P_capture` excursion is grid-independent.** Re-running on
   the committed `0.25 s` grid reproduced the same behaviour seen on the finer
   diagnostic grid — `P_capture` rises from `8.02e-02` at `T = 4.00 s` to
   `4.17e-01` at `T = 4.25 s` for VGM-0 `passive` while `B55` falls. It is a
   property of the passive arm, not of grid spacing, and it sits entirely inside
   the masked region (`T >= 3.0 s` for VGM-0), so committed η is unaffected.

Shared grid points also matched the earlier fine-grid run digit-for-digit, which
is a clean determinism check on the pipeline.

---

## 3. Why CC and ff+PID needed re-running

Both arms used a fixed `DURATION_S = 171.0` with a half-record steady-state
slice, while the passive arm had already moved to cycle-scaled duration and
whole-cycle averaging. Two measured diagnostics settled the question.

### Long period — VGM-90 CC, `T = 5.00 s`, `design_omega = 1.25663706`

| case | window | mean `power_w` |
|---|---|---:|
| 171 s (committed) | half-record | −2.98142124e-03 |
| 760 s | half-record | −2.8183e-04 |
| 760 s | final 20 whole cycles | −2.8398e-04 |

The 171 s value reproduces the committed CSV exactly. Extending to 150 cycles
shrinks the magnitude ~10.6×. With `P_converted ≈ 7.64e-02` and
`P_injected ≈ 7.94e-02`, `P_net` is under 1% of gross flow — a
catastrophic-cancellation residual converging toward zero, not toward a
meaningful operating point.

### Short period — VGM-0 CC, `T = 1.50 s`, `design_omega = 4.18879020`

| case | window | mean `power_w` | vs committed |
|---|---|---:|---:|
| 171 s | half-record | 2.34265974e+00 | exact match |
| 235 s | half-record | 2.32631337e+00 | −0.70% |
| 235 s | final 20 whole cycles | 2.34327305e+00 | **+0.03%** |

Two windows on the **same settled** record differ by 0.73%. That isolates a pure
partial-cycle averaging bias, independent of settling, and it is
period-dependent — it varies across the x-axis of every `η(T)` plot.

**Headline finding:** the `2.34 W` CC power-hull peak is confirmed safe to
`0.03%`. The rerun is justified on **rigor and uniformity**, not on correcting
the physics. This mirrors the passive arm's measured `0.15–0.45%` deltas.

---

## 4. What PR #63 changed

Full method note: [`docs/SWEEP_METHOD.md`](SWEEP_METHOD.md) (now the canonical
reference; `docs/PASSIVE_CAMPAIGN_METHOD.md` is a compatibility pointer).

- **New `scripts/sweep_method.py`** — shared helper imported by all three sweep
  scripts: `duration_for_period`, `build_period_grid`, `whole_cycle_tail_slice`,
  provenance read/write, shared constants.
- **Per-arm derived settle counts.** CC sets `B_r = B55(ω₀)` and therefore does
  **not** get the `opt_passive` damping doubling, so `ζ_cl ≈ ζ_freedecay` rather
  than `2ζ`. VGM-90 binds at 256 cycles to 1% residual:

  | Arm | `N_SETTLE` | `N_AVG` | `N_CYCLES` | Duration rule |
  |---|---:|---:|---:|---|
  | passive / `opt_passive` | 130 | 20 | 150 | `10 + 150·T` |
  | CC | 260 | 20 | 280 | `10 + 280·T` |
  | ff+PID | 260 | 20 | 280 | `10 + 280·T` |

  ff+PID inherits 260 as a conservative bound, documented explicitly as
  inherited rather than derived (empirical PID gains give no clean `ζ_cl`; the
  passive-safety fallback bounds it below by passive behaviour).
- **`dt = 0.01 s`** written into scratch YAML for all arms.
- **`--period-step`** on all three sweeps, default `0.25`.
- **Provenance columns** `duration_s`, `dt_s`, `period_step_s`, `n_settle`,
  `n_avg` on all arms, with legacy-CSV tolerance.
- **New `reactive_cancellation_limited` guard for CC** — set when
  `P_converted > 0` and `|P_capture| / P_converted < 1e-2`. Motivated by
  `analysis/cc/capture_efficiency_VGM90.csv`, where 13 of 27 points had a
  sub-1% residual with randomly alternating sign, all `masked = false` because
  `B55` stayed above the `1e-4` threshold. The existing guards covered the
  denominator (`masked`) and `η > 1` (`linear_popt_invalid`); nothing covered a
  numerator below its own noise floor. Honoured by
  `three_regime_comparison.py` (both hulls) and `cc_vs_ffpid_comparison.py`.
- **Doc reconciliation.** `analysis/FINDINGS_3REGIME.md` §5 rewrote
  "why fixed-passive was pruned (degenerate)" — which contradicted the committed
  passive CSVs — into "why fixed-passive is dominated off resonance", keeping the
  `B_pto` vs `|Z_intrinsic|` ratio table and the B55 lobe-misalignment argument.
  A stale-data banner was added for the CC / ff+PID numbers.
- **`docs/SWEEP_METHOD.md` fixes the garbled `N_SETTLE` justification.** The old
  text said `B_opt = B55(ω₀)` "exactly doubles the system damping". It does not
  by itself; the doubling comes from the PTO damping **adding to** the plant's
  existing radiation damping, giving `≈ 2·B55`. The conclusion `ζ_cl ≈ 2ζ` was
  right, the one-line justification was not — and the CC derivation depends on
  that distinction.
- **`scripts/sweep_kpkd_vgoswec.sh`** carries a provenance note recording that
  the ff+PID gains were selected under the old `DURATION=171` / half-record
  method and were **not** re-optimized. Gains unchanged; formal optimization
  remains #54 scope. Kpkd sweeps are explicitly **not** being re-run.

`python3 -m unittest discover tests` passes — 26 tests. The `WARN` / `ERROR`
lines in that output are tests deliberately exercising the free-decay fallback
and `--strict` rejection paths, not failures.

---

## 5. What is running

```bash
python3 -u scripts/cc_capture_efficiency_sweep.py 2>&1 | tee /tmp/cc_sweep.log
python3 -u scripts/capture_efficiency_sweep.py 2>&1 | tee /tmp/ffpid_sweep.log
```

Each arm is 27 periods × 5 flaps = 135 solver runs. Total simulated time per arm
is `Σ(10 + 280·T) ≈ 143,100 s`, against 154,575 s for the passive campaign which
took roughly 85 minutes wall. **Expect ~80 min per arm, ~2.7 h total.**

Outputs:

- `analysis/cc/capture_efficiency_VGM{0,10,20,45,90}.csv` + figures
- `analysis/passive_guarded/capture_efficiency_VGM{0,10,20,45,90}.csv` + figures

---

## 6. Next session — resume here

### Step 1: check the logs

```bash
tail -40 /tmp/cc_sweep.log
tail -40 /tmp/ffpid_sweep.log
```

Two specific things to look for:

1. Any `Steady-state averaging window exceeds record length` or
   `undersampled` error — would indicate a duration/window mismatch.
2. Whether CC long-period points now come back flagged
   `reactive_cancellation_limited=true`, as predicted. Check with:

```bash
awk -F, 'FNR>1 && $12=="true" {print FILENAME, "T="$1}' \
  analysis/cc/capture_efficiency_VGM*.csv
```

### Step 2: sanity-check the headline

The VGM-0 CC peak at `T = 1.50 s` should land near `2.343 W` (the diagnostic
predicted `+0.03%` vs the committed `2.34265974e+00`):

```bash
awk -F, 'FNR>1 && $1=="1.50" {print $1, $3}' analysis/cc/capture_efficiency_VGM0.csv
```

A materially different value means something in the port is wrong and should be
investigated before committing.

### Step 3: regenerate derived figures and commit

```bash
python3 scripts/cc_vs_ffpid_comparison.py --plot-only
python3 scripts/three_regime_comparison.py --plot-only
git add analysis/ && git commit -m "results: CC + ff+PID campaigns under unified sweep method"
git push origin main
```

### Step 4: refresh the hand-written numbers

**This is the one thing that does not regenerate itself.** The tables and prose
in `analysis/FINDINGS_3REGIME.md` are hand-written, not generated:

- §1 crossover-period table
- §2 resonance-hump table
- §4a power hull table
- §4b efficiency hull table
- §4c divergence analysis ("17 of 27 period points")

`analysis/three_regime/operating_envelope.csv` and
`operating_envelope_efficiency.csv` **do** regenerate, so refresh the markdown
tables from those. Then remove the stale-data banner at the top of the file.

Also refresh [`docs/PROJECT_STATE.md`](PROJECT_STATE.md) to mark the reruns
landed, and consider a `docs/RESULTS_CAMPAIGN_2026-09-19.md` campaign record for
the unified-method campaigns, mirroring the free-decay one.

### Step 5: then #50

Literature positioning / related-work verification is the gate before manuscript
drafting begins.

---

## 7. Paper-data coverage

After the reruns are committed, every simulation-side artifact the paper needs is
in the repo and regenerable from committed CSVs via `--plot-only`:

| Artifact | Source | Status |
|---|---|---|
| Free-decay validation (ω_n, ζ) | `docs/freedecay_validation.csv` + `docs/img/` | committed |
| passive + opt_passive | `analysis/{passive,opt_passive}/` | committed |
| CC | `analysis/cc/` | running |
| ff+PID | `analysis/passive_guarded/` | queued |
| CC vs ff+PID overlays | derived, `--plot-only` | after rerun |
| Three-regime relay + both envelopes | derived, `--plot-only` | after rerun |

All three controller arms will then share one documented method, with per-arm
settle counts derived from the validated free-decay `ζ` — a direct downstream use
of the free-decay campaign.

---

## 8. Open items (none blocking)

1. **Free-decay ζ printout differs slightly from the recorded S2 table.** This
   session's test output shows VGM-0 `52.3`, VGM-45 `36.8`, VGM-90 `28.8`,
   against `52.8 / 36.7 / 28.6` recorded in
   [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md) §S2
   and used for the `N_SETTLE` derivations. Sub-1% and does not change any
   binding case (VGM-90 still binds; 256 cycles → `N_SETTLE = 260` holds), but
   worth reconciling so one number is authoritative before publication.
2. **`--strict` writes artifacts before failing** — `freedecay_validation.py`
   writes `docs/freedecay_validation.csv` before exiting non-zero. It should
   refuse to write at all.
3. **Vestigial `hydro.rho` key in `config/*.yaml`** — no consumer;
   de-normalization is pinned to the H5-stored `rho`. Remove or comment.
4. **VGM-20 above-trend ζ** — appears in both independently-processed datasets,
   most plausibly a physical 20°-geometry effect. Worth a look before
   publication.
5. **`T = 2.50 s` retuning effect** — VGM-90 `opt_passive` shows a 4.4× single-point
   jump that survived every numerical audit and traces to `design_omega` choice
   alone (2.3× from tuning). Documented in `docs/SWEEP_METHOD.md` history and
   still open for investigation.
