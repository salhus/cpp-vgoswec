# End-of-day summary — 2026-09-17

**Session outcome:** free-decay validation stage **closed**; MATLAB/WEC-Sim
validation work **complete**; passive-campaign method reworked and documented;
full passive/opt_passive sweep **launched and still running at end of session**.

This file is written to be self-contained. If the chat session is lost, this
document plus the linked files is sufficient to resume without re-deriving
anything.

---

## 0. Resume here tomorrow

The passive sweep was launched at roughly 17:45 local and takes **~85 minutes**.
It will have finished long before the next session.

**First actions, in order:**

```bash
cd ~/projects/cpp-vgoswec
git status                       # sweep writes into analysis/ — expect dirty tree
tail -40 /tmp/passive_sweep.log  # confirm it completed, look for tracebacks
grep -c '^\[ok\] wrote' /tmp/passive_sweep.log
```

Expect **10 CSVs + 18 figures** = 28 `[ok] wrote` lines. Fewer means it died
partway; the log has the failing command and its stderr.

Then verify the new method actually applied:

```bash
head -2 analysis/opt_passive/capture_efficiency_VGM90.csv
```

The header must now include `duration_s,dt_s,n_settle,n_avg`, and the `T=0.50`
row must read `duration_s = 85.0`, `dt_s = 0.01`, `n_settle = 130`,
`n_avg = 20`. If those columns are absent the sweep did not rerun that pair.

Then the two analysis questions (see §5 for full commands):

1. **η > 1 audit** — did whole-cycle averaging remove the spurious points?
2. **Old vs new `P_capture` delta** — how much was the averaging bias worth?
   Baseline for VGM-90 opt_passive was saved to `/tmp/vgm90_opt_OLD.csv`.
   ⚠️ `/tmp` may not survive a reboot — if it is gone, recover the old values
   from git: `git show HEAD:analysis/opt_passive/capture_efficiency_VGM90.csv`.

---

## 1. Free-decay stage — CLOSED

Primary record: [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md)

Both plant impedance components are validated against the **original WEC-Sim raw
time histories** (not the published table, not a figure read):

| Metric | C++ vs WEC-Sim raw | C++ vs paper Table 2 |
|---|---:|---:|
| ω_n (reactive: A55 + hinge stiffness) | **±0.15%** | ±0.9% |
| ζ (resistive: radiation damping B55) | **~4–13%** | ~9–13× |

The Table 2 ζ gap is **not** a solver disagreement — both solvers agree with each
other on the raw data. It is consistent with a `×10⁻³` vs `×10⁻⁴` exponent
labeling error in that column of the paper.

**No C++ model change is indicated.** This is the foundation the three-regime
co-design study rests on.

### MATLAB / WEC-Sim work is finished

The extracted reference values are embedded as constants in
`scripts/freedecay_validation.py`. No further `.mat` processing is required for
any planned work. All subsequent campaigns are C++-only.

---

## 2. Repository hygiene — all clear

Completed this session:

- 200 s free-decay config harmonization committed (`f8c936f`) — previously the
  repo documented a 200 s campaign while `config/` still said 60 s.
- `docs/freedecay_validation.csv` now tracked via a `!docs/*.csv` exception
  (`7840f42`); it had been silently excluded by a blanket `*.csv` ignore despite
  being listed as a pipeline artifact in `docs/REPRODUCTION.md`.
- `.gitignore` duplicate entries removed (`1b2fa00`).
- CRLF writer fix (`9da411f`, `1131e4d`).
- **Both stashes cleared.** Figure stash popped and committed; the stale GUI WIP
  stash was dropped after review — it reverted C++20→17 while keeping the
  GCC-13 `std::format` guard that only makes sense under C++20, and silently
  added `CMAKE_CXX_EXTENSIONS ON`. Diff preserved at `/tmp/old_gui_wip.patch`
  (may not survive reboot; it was superseded work and is not needed).
- `git stash list` is empty. Working tree was clean before the sweep started.

---

## 3. Two fictitious issues retired

Both had been recorded in the docs as real defects. Neither was. This section
exists so they are not re-raised.

### 3.1 The `rho` 1025-vs-1000 "discrepancy" — NOT a defect

Previously written up as "the next item to resolve," affecting `P_opt` and
therefore every capture-efficiency denominator. **It affects nothing.**

De-normalization is pinned to the H5-stored density as the single source of
truth:

```cpp
// src/impedance.cpp
double rho_eff = tables.h5_rho;   // = 1000 for the VGM BEM runs
...
coeffs.A55    = mu55 * rho_eff;
coeffs.B55    = std::max(0.0, lambda55 * rho_eff * omega0);
coeffs.Fexc55 = ex55 * rho_eff * tables.g;
```

This is the **correct** basis: the BEM coefficients were computed at that
density, so de-normalizing with it recovers dimensional values consistently and
puts all five geometries on one basis. The Python sweep scripts read `rho` from
each H5 identically.

The `rho_legacy` / `rho_eff_match` figure in the hydro diagnostic printout is an
**RIRF-derived back-out used only to confirm the de-normalization reconciles**.
It is labelled as such in the header and never enters a computation:

```cpp
double rho_eff_match; ///< Legacy RIRF-derived rho (diagnostic only, not used)
```

The `rho: 1025.0` key in `config/*.yaml` is parsed into `SimConfig::rho` and then
consumed by nothing. It is vestigial dead config — misleading on inspection, but
inert. Tracked as a minor cleanup only.

### 3.2 CRLF in `docs/freedecay_validation.csv` — worktree-only

Python's `csv.writer` defaults to `lineterminator="\r\n"` per RFC 4180, so the
file arrived in the worktree with CRLF. But git was normalizing to LF on the way
into the index, so **the committed blob was always correct**. The fix
(`lineterminator="\n"`) is still worth having to stop local diff noise, but this
was never a repository-state problem.

---

## 4. Passive campaign method — reworked (PR #61, merged `ec56b4f`)

Full reasoning: [`docs/PASSIVE_CAMPAIGN_METHOD.md`](PASSIVE_CAMPAIGN_METHOD.md)

### What was wrong

`scripts/passive_vs_optpassive_sweep.py` used a fixed `DURATION_S = 171.0` and
averaged power over a fixed *sample fraction*:

```python
return float(np.mean(pw[len(pw) // 2:]))
```

Three problems:

1. **Inconsistent cycle counts.** 171 s is 342 cycles at T = 0.5 s but only 24
   at T = 7 s — simultaneously wasteful and under-resolved.
2. **Systematic period-dependent bias.** 171 s is not an integer multiple of most
   grid periods, so the averaging window ended mid-cycle, leaving a partial-cycle
   residual in the mean of a periodic signal. This is a *bias*, not noise, and it
   varies across the x-axis of every η(T) plot. Plausible contributor to spurious
   η > 1 flags.
3. **Oversampled timestep.** `dt = 0.005 s` gives 1400 steps/cycle at T = 7 s.

### What changed

| | before | after |
|---|---|---|
| duration | fixed 171 s | `10 + 150·T` (85 s → 1060 s) |
| averaging | `pw[len(pw)//2:]` | final `N_AVG·T` seconds, whole cycles, sliced by **time** |
| timestep | 0.005 s (from config) | 0.01 s (written into scratch config) |
| provenance | none | `duration_s`, `dt_s`, `n_settle`, `n_avg` columns |

Constants: `RAMP_S = 10.0`, `N_SETTLE = 130`, `N_AVG = 20`, `N_CYCLES = 150`,
`TIMESTEP_S = 0.01`. **No duration cap** — every period gets the full 150 cycles.

`--plot-only` remains backward-compatible with CSVs lacking the new columns.
Four unit tests added in `tests/test_passive_vs_optpassive_sweep.py`; all pass.

### Why N_SETTLE = 130 — the derivation

This is the part worth preserving. Transient amplitude decays as `exp(-2πζ_cl)`
per cycle, so cycles-to-settle is `ln(1/tol) / (2πζ_cl)` — **independent of
period**, set purely by closed-loop damping.

At resonance under `opt_passive`, the reactive part of `Z_intrinsic` vanishes, so
`B_opt = |Z(ω₀)| = B55(ω₀)` — the controller exactly **doubles** the damping.
Hence `ζ_cl ≈ 2·ζ_freedecay`, using the ζ values validated this morning:

| Flap | ζ_freedecay ×10⁻⁴ | ζ_cl ≈ 2ζ | cycles→1% | cycles→0.1% |
|---|---:|---:|---:|---:|
| VGM-0 | 52.8 | 0.0106 | 69 | 104 |
| VGM-10 | 38.1 | 0.0076 | 96 | 145 |
| VGM-20 | 47.5 | 0.0095 | 77 | 116 |
| VGM-45 | 36.7 | 0.0073 | 100 | 150 |
| **VGM-90** | **28.6** | **0.0057** | **129** | **193** |

VGM-90 binds at 129 cycles (lightest damping) → `N_SETTLE = 130`.

This is the **resonant worst case**. Off-resonance `B_opt = |Z(ω)| ≫ B55(ω₀)`,
damping is far higher and settling collapses to a few cycles — so 130 is
conservative everywhere except exactly where it needs to be tight.

`N_AVG = 20` suffices because whole-cycle averaging makes the bias **identically
zero**, not merely small; the window only needs to suppress numerical noise.

> **Note the dependency:** this derivation is only possible because the free-decay
> campaign validated ζ. It is a direct downstream payoff from that work and is
> worth citing as justification for the effort spent there.

### Why dt = 0.01, and why not 0.05

Steps per cycle at `dt = 0.01`: 50 @ T=0.5 s, 100 @ T=1.0, 700 @ T=7.0.

`dt = 0.05` was **considered and rejected**:
- Only 10 steps/cycle at T = 0.5 s — cannot represent a sinusoid's peak; and
  since power goes as velocity **squared**, amplitude error roughly doubles in
  `P_capture`. Worse, T = 0.5–1.5 s is where the CC power hull peaks (2.34 W at
  T = 1.5 s, VGM-0) — the worst place to lose accuracy.
- The radiation convolution is integrated on the RIRF time grid; coarsening past
  its sample spacing undersamples the convolution memory (cf. the
  `ω_nyquist = π/dt` warning in `src/impedance.cpp`).
- Low damping + hinge spring + long records ⇒ integrator energy-drift risk.

### Convergence and drift check — PASSED

VGM-90 opt_passive, T = 7.0 s, 1060 s record (5× longer than any prior run),
instantaneous states at t = 1060.000 s:

| | dt = 0.005 | dt = 0.01 | diff |
|---|---:|---:|---:|
| pitch [rad] | 0.05615591 | 0.05605291 | 0.18% |
| velocity [rad/s] | −0.04329637 | −0.04300112 | 0.68% |
| power [W] | 0.00133328 | 0.00131515 | 1.4% |

This is the **strictest** possible comparison — a single instantaneous sample
after 1060 s, so any accumulated phase drift lands in it. The cycle-averaged
`P_capture` the sweep actually uses will agree considerably more tightly.
Power error ≈ 2× velocity error, exactly as `P ∝ v²` predicts.

**No integrator drift**: the tail oscillates cleanly with no amplitude growth or
ratcheting. `dt = 0.01` is confirmed converged.

Also established: `dt = 0.005 → 0.0005` moved free-decay ζ by only ~7%, so 0.005
was already inside the converged band and 0.01 remains safely within it.

Runtime: 35 s wall for 1060 s at `dt = 0.01` (≈35× parallelism — `user 20m49s`
vs `real 35s`, so concurrent sweep runs would contend rather than help).

---

## 5. The running sweep — what to check

**Command used:**

```bash
python3 scripts/passive_vs_optpassive_sweep.py 2>&1 | tee /tmp/passive_sweep.log
```

**Scope:** 27 periods × 5 flaps × 2 controllers = **270 runs**, 154,575 simulated
seconds, ≈85 min wall.

**Iteration order** (matters for reading partial results): flap 0 → 10 → 20 → 45
→ 90; within each, `passive` then `opt_passive`. So VGM-90 opt_passive finishes
last.

> Progress note: `[ok] wrote` prints only after a full 27-period pair completes
> (~8.5 min each), and Python block-buffers stdout through `tee`. An empty log
> early on is normal. Use `python3 -u` next time for live output.

### Check 1 — provenance columns applied

```bash
head -2 analysis/opt_passive/capture_efficiency_VGM90.csv
head -2 analysis/passive/capture_efficiency_VGM0.csv
```

### Check 2 — η > 1 audit

```bash
awk -F, 'FNR>1 && $7!="" && $7+0>1 {print FILENAME, "T="$1, "eta="$7}' \
  analysis/passive/capture_efficiency_VGM*.csv \
  analysis/opt_passive/capture_efficiency_VGM*.csv
```

η > 1 is unphysical against the Budal bound. If whole-cycle averaging worked,
there should be **fewer** than before. Any survivors are most likely
mask-boundary artifacts where `B55` is near the `1e-4` threshold and `P_opt`
blows up — physics/masking, not averaging bias.

### Check 3 — old vs new `P_capture` delta

This quantifies what the bias was worth, and is the headline result of the
method change.

```bash
diff <(cut -d, -f1,3 /tmp/vgm90_opt_OLD.csv) \
     <(cut -d, -f1,3 analysis/opt_passive/capture_efficiency_VGM90.csv)
```

Old baseline reference point: **VGM-90 opt_passive, T = 0.50 s, η = 82.32%**,
`P_capture = 2.32311101e-01 W`, `P_opt = 2.82206595e-01 W`.

If `/tmp` was cleared, recover old values with:

```bash
git show HEAD:analysis/opt_passive/capture_efficiency_VGM90.csv | head -3
```

(valid only before committing the new CSVs).

### Expected quirk — VGM-90 near its own resonance

`B55(ω₀) = 3.91e-4 N·m·s/rad` for VGM-90 is only ~4× the `1e-4` mask threshold.
`P_opt = F_exc²/(8·B55) ≈ 4.7 W` there — well above the 2.34 W power-hull peak —
so **η at VGM-90 resonance will read low**, and nearby points may cross the mask
boundary. This is expected, not a bug. The VGM-90 efficiency curve will look
sparse near T ≈ 3 s.

### If the sweep failed partway

`run_capture_sweep` raises on the first non-zero solver exit and includes the
failing command's stdout/stderr. Partial CSVs are **not** written — CSVs are
written per flap+controller pair only after all 27 periods succeed, so
`analysis/` will hold a mix of new and old files. Check `duration_s` presence to
tell them apart.

---

## 6. State of the docs

| File | Status |
|---|---|
| [`docs/RESULTS_CAMPAIGN_2026-09-17.md`](RESULTS_CAMPAIGN_2026-09-17.md) | Free-decay closure record. `rho` issue replaced with verified "Density basis" section. |
| [`docs/PROJECT_STATE.md`](PROJECT_STATE.md) | Refreshed. Next actions: passive campaign → #50. |
| [`docs/PASSIVE_CAMPAIGN_METHOD.md`](PASSIVE_CAMPAIGN_METHOD.md) | **New.** Duration/averaging/timestep derivation. |
| [`docs/REPRODUCTION.md`](REPRODUCTION.md) | Passive section updated for the new method. |
| [`docs/freedecay_wecsim_rawdata_validation.md`](freedecay_wecsim_rawdata_validation.md) | Primary ω_n / ζ reference. Unchanged. |

No known fictitious or stale issues remain in the documentation.

---

## 7. Open items

### Next session
1. **Read the sweep results** — §5 checks 1–3.
2. **Commit the new CSVs and figures** once reviewed, with a note that they were
   produced under the 150-cycle / whole-cycle / `dt = 0.01` method.
3. **Decide the fixed-passive question.** `PROJECT_STATE.md` records fixed-passive
   as "pruned as degenerate." The sweep regenerates both arms — worth confirming
   from the new data whether that call still holds, since the averaging fix
   changes the comparison.

### Then
4. **Kick off #50** — literature positioning / related-work verification. This is
   the first-paper critical path and gates manuscript drafting.

### Minor, non-blocking
- `--strict` in `freedecay_validation.py` writes artifacts before exiting
  non-zero; should refuse to write at all.
- `[impedance] INFO: legacy A55-match rho=...` prints once per hydro-sweep row —
  observed firing far more than the "32×" previously documented. Pure log noise
  (the value is diagnostic), but it bloats captured stderr across 270 runs.
  Resolve `rho` once at load.
- Vestigial `hydro.rho` in `config/*.yaml` — no consumer; remove or comment.
- VGM-20 sits above the ζ trend in **both** independently-processed datasets —
  most plausibly physical (20°-geometry hydrodynamic coupling), worth a look
  before publication.

---

## 8. Commit log for this session

| Commit | Content |
|---|---|
| `f8c936f` | 200 s free-decay config harmonization |
| `7840f42` | Track `docs/freedecay_validation.csv`; `.gitignore` exception |
| `1b2fa00` | `RESULTS_CAMPAIGN_2026-09-17.md`; `.gitignore` dedupe |
| `a19fbe7`, `e2c3887` | PR #60 — stale bounds, PROJECT_STATE, REPRODUCTION |
| `9da411f`, `1131e4d` | CRLF writer fix |
| `ba371ed` | Correct `rho` characterization in campaign record |
| `690d7d8` | Refresh PROJECT_STATE for free-decay closure |
| `ec56b4f` | PR #61 — passive sweep rework + method doc + tests |

Earlier in the day: PR #59 (tooling hardening — computed bounds, provenance,
`--strict`), PR #60 (doc closure).

---

## 9. Environment

```bash
chrono10 && seastack
```

- Chrono v10: `/home/shusain/project-chrono_v10/install/lib/cmake/Chrono`
- SEA-Stack: `/home/shusain/SEA-Stack/install/lib/cmake/SEAStack`
- Binary: `build/demo_vgoswec`
- The `chrono10` helper clears stale SEA-Stack env pinned to another Chrono
  build — always run the pair together.

VSG visualization env handling (`VSG_FILE_PATH`, font-existence warnings) lives
in `~/env/_chrono_common.sh` — see `docs/EOD_SUMMARY_2026-09-16.md` for the
two-copies-in-one-process diagnosis and fix.
