# Passive vs optimal-passive damper — background note

For the current repository handoff, the authoritative sources are:

- [`../docs/STATUS.md`](../docs/STATUS.md)
- `analysis/passive/capture_efficiency_VGM*.csv`
- `analysis/opt_passive/capture_efficiency_VGM*.csv`
- `analysis/three_regime/operating_envelope.csv`

This file is retained only as qualitative background for why `opt_passive` should meet
or exceed fixed `passive` away from each flap's design resonance.

## Physics retained from the original note

- `passive` uses a fixed damping coefficient `B_pto = B55(ω₀)`.
- `opt_passive` uses the impedance-matched resistive term `B_opt = |Z_intrinsic(ω)|`.
- At exact resonance, the two coincide.
- Away from resonance, `opt_passive` is the tighter passive reference.

For current quantitative results, prefer the committed CSVs over any hand-written table.

## Reproducing current figures

```bash
python3 scripts/passive_vs_optpassive_sweep.py --plot-only
```
