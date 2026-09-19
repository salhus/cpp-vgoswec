# End-of-day summary — 2026-09-19

**Session outcome:** the impedance-basis audit is now landed in code, tests, configs, and docs. The time-domain plant remains untouched. The one campaign invalidated by the audit is **`opt_passive`**, which must be re-run by the owner after merge.

---

## 1. Full-day status snapshot

| track | status |
|---|---|
| Free-decay validation | **closed** (still the plant-validation foundation) |
| CC + ff+PID unified-method campaigns | **landed earlier today** in `458a333` |
| PR #65 masking split + figure regeneration | **landed earlier today** in `6cf32c1` |
| Impedance-basis audit | **fixed in code/docs/config/tests** in this PR |
| `opt_passive` committed CSVs | **invalid pending re-run** |
| `exc_ff_pid` under new impedance framing | untested |

---

## 2. Earlier 2026-09-19 work that remains current

Two unrelated but still-current pieces of work landed before the impedance audit and need to stay in the record:

1. **Unified sweep-method campaigns landed (`458a333`).**
   - CC and ff+PID now share the documented `10 + 280·T`, final-20-whole-cycles method.
   - The CC headline moved from `2.34265974 W` to `2.44488972 W` at **VGM-0, `T = 1.50 s`** under the unified method.
   - **This new headline is NOT yet confirmed as settled.** The 430 s vs 760 s check is still outstanding.

2. **PR #65 masking split + regenerated figures (`6cf32c1`).**
   - `_power_excluded` and `_eta_excluded` were split.
   - plotting gained `--show-all`.
   - derived figures were regenerated on top of that change.

Also still current: `reactive_cancellation_limited` now fires in flap order:

- VGM-90 from `T = 3.75 s`
- VGM-45 from `T = 4.50 s`
- VGM-20 from `T = 5.50 s`
- VGM-10 from `T = 6.00 s`
- VGM-0 never

---

## 3. What the impedance audit proved

Canonical technical record: [`IMPEDANCE_BASIS.md`](IMPEDANCE_BASIS.md).

### Defect 1 — `K_hs55` was not de-normalized

`src/impedance.cpp` de-normalized `A55`, `B55`, and `Fexc55`, but left `K_hs55` as the raw BEMIO `linear_restoring_stiffness` value. The fix is `raw * rho * g`.

### Defect 2 — `opt_passive` was computing gains from the CG H5

The non-circular evidence is the spring-sweep `I + A55` comparison:

- hinged H5 reproduces the measured **3.8×** geometric variation to within about **3%**
- CG H5 cannot reproduce that variation at all

All five `vgoswec_*_opt_passive.yaml` files now explicitly set:

```yaml
hydro:
  h5_file: hydroData/vgoswec_*.h5
  impedance_h5_file: hydroData/hinged_vgoswec_*.h5
```

The `impedance_h5_file -> h5_file` fallback is still supported for backward compatibility, but it is now **explicitly logged once** so a silent basis mismatch cannot recur.

### Defect 3 — the analytic model omitted the gravity-buoyancy restoring couple

The plant oscillates even with `external_stiffness: 0.0`, so the analytic model was missing a positive restoring term. Spring-sweep x-intercepts gave:

`K_gb = 0.867 ± 0.032 N·m/rad`

That is now exposed as:

```yaml
hinge:
  gravity_buoyancy_stiffness: 0.867
```

and the model now uses:

`K_hs_eff = K_hs55 + C_ext + K_gb`

### Defect 4 — comments carried the wrong `I_hinge`

Code/runtime were already correct; comments were not. The stale `0.652` is now `0.6788 kg·m²`.

---

## 4. Corrected-model validation and honesty note

Using hinged-frame `A55(omega)` with `K_eff = 6.57 + 0.867 = 7.437 N·m/rad`, the corrected single-DOF model predicts free-decay `omega_n` within **3%** for all five flaps.

That agreement is useful, but it is **partly circular** because `K_gb` itself was extracted from free-decay spring-sweep runs.

So the argument must be ordered as:

1. **lead with the non-circular `I + A55` basis comparison**;
2. then show the corrected `omega_n` agreement as a consistency check;
3. keep the residual `~1.4%` bias framed honestly as a single-DOF-vs-coupled-plant limitation.

---

## 5. Per-arm impact matrix

| arm | impact |
|---|---|
| `passive` | unaffected |
| `cc` | committed results remain valid; configs were already hinge-referenced |
| `opt_passive` | **invalid pending re-run** |
| `exc_ff_pid` | untested under this audit |

The owner should be able to `git pull` and immediately re-run the `opt_passive` campaign.

---

## 6. Files changed conceptually by this audit

- `src/impedance.*` — fixed `K_hs55` de-normalization and added `K_gb` to `K_hs_eff`
- `src/config_loader.*` — parsed `hinge.gravity_buoyancy_stiffness`
- `src/demo_vgoswec.cpp` — plumbed the new term, made fallback explicit, made `--hydro-report` use `impedance_h5_file`, expanded diagnostics
- `config/vgoswec_*.yaml` — added `gravity_buoyancy_stiffness`; all `opt_passive` configs now set `impedance_h5_file`; stale `I_hinge` comments corrected
- tests — regression coverage for de-normalization, stiffness composition, free-decay agreement, and config guards
- docs / analysis notes — reconciled to the new basis explanation

---

## 7. Open items carried forward

1. **Highest priority:** ff+PID guard-fire instrumentation now exists in `ExcitationVelocityController::ComputeForce` and `demo_vgoswec` prints the guard-fire / clip fractions after each `exc_ff_pid` run. What remains is the actual VGM-0 `T = 4.50 s` run and interpretation: if the guard fires near 100% of the time, the long-period band is the passive-safety floor rather than feedforward control, and the claim *"ff+PID carries the long-period tail"* must be rewritten.
2. The `2.44488972 W` headline is still unconfirmed as settled (`430 s` vs `760 s` check still needed).
3. Sweep scripts still tabulate `F_exc_Nm` / `B55_Nmsrad` from **CG** H5 files while `P_capture` is measured in the hinge DOF. `P_opt = F^2/(8B)` is basis-invariant so `eta` is only mildly affected, but `masked` is not. Hinge-basis re-tabulation is still needed as post-processing.
4. `analysis/FINDINGS_3REGIME.md` hand-written tables are still stale.
5. There remains a uniform `~1.4%` residual between corrected analytic `omega_n` and free-decay (`single-DOF analytic model` vs `coupled plant`).
6. `[impedance] INFO: legacy A55-match rho=...` still prints more often than intended and should become truly once-per-process.

---

## 8. Resume point

After this PR merges, the next concrete owner action is:

```bash
python3 scripts/passive_vs_optpassive_sweep.py
```

Then refresh any derived `opt_passive` plots/tables that consume the committed CSVs.
