# `opt_passive` sweep data — status banner

> **⚠ Superseded pending re-run.**
>
> The committed CSVs in this directory were generated **before** the 2026-09-19
> impedance-basis fix. At that time, `opt_passive` gain computation silently fell
> back to the CG-referenced `hydro.h5_file` instead of the hinge-referenced
> `hydro.impedance_h5_file`, and the analytic model also omitted the measured
> gravity-buoyancy restoring couple `K_gb`.
>
> As a result, the committed `analysis/opt_passive/capture_efficiency_VGM*.csv`
> files should be treated as **invalid pending the owner re-run**.
>
> The time-domain plant itself was not changed. After merge, regenerate this
> directory with:
>
> ```bash
> python3 scripts/passive_vs_optpassive_sweep.py
> ```
>
> Canonical technical record: [`../../docs/IMPEDANCE_BASIS.md`](../../docs/IMPEDANCE_BASIS.md).
