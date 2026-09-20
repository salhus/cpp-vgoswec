# Analysis directory map

**Start with [`../docs/STATUS.md`](../docs/STATUS.md).** It is the primary handoff for the
current repository state.

For the **three-regime controller-comparison campaign**, the committed source data lives in
four per-controller trees:

- `analysis/passive/` — fixed passive damper CSVs + figures
- `analysis/opt_passive/` — optimal passive damper CSVs + figures
- `analysis/cc/` — complex-conjugate controller CSVs + figures
- `analysis/passive_guarded/` — tuned `exc_ff_pid` (ff+PID) CSVs + figures

Each tree contains five committed per-flap CSVs (`VGM-0/10/20/45/90`) with the shared
period grid **T = 0.50..7.00 s in 0.25 s steps**.

## Current source-of-truth outputs

- `analysis/three_regime/operating_envelope.csv`
- `analysis/three_regime/operating_envelope_efficiency.csv`
- `analysis/FINDINGS_3REGIME.md`

The envelope CSVs are the authoritative summary of the current committed campaign.

## Post-processing basis / retabulation workflow

Hydro-derived columns are now hinge-referenced across all four source CSV trees:

- `B55_Nmsrad`
- `F_exc_Nm`
- `P_opt_W`
- `eta`
- `masked`
- `linear_popt_invalid` (for CC CSVs)

Re-tabulate or verify without re-running simulations:

```bash
python3 scripts/retabulate_hydro_columns.py --verify
```

This script re-derives those columns from `hydroData/hinged_vgoswec_*.h5` and does **not**
touch simulation-output columns such as `P_capture_W`, `P_converted_W`, `P_injected_W`, or
`reactive_cancellation_limited`.

## Other committed analysis paths

- `analysis/comparison/` — derived CC-vs-ff+PID figures
- `analysis/passive_vs_optpassive/` — derived passive-vs-opt-passive figures
- `analysis/figures/` — Kp×Kd surface figures
- `analysis/kpkd_sweep_VGM*.csv` — **synthetic** tuning-grid data, not direct solver output

These paths are useful, but they are not the primary evidence base for the current
three-regime handoff.

## Reproducing current committed post-processing

```bash
python3 scripts/retabulate_hydro_columns.py --verify
python3 scripts/three_regime_comparison.py --plot-only
python3 scripts/cc_vs_ffpid_comparison.py --plot-only
python3 scripts/passive_vs_optpassive_sweep.py --plot-only
```
