# Capture-efficiency study — historical note

This file is retained as background for the older CC-vs-ff+PID comparison narrative.
For the **current** repository handoff and current numbers, use:

- [`../docs/STATUS.md`](../docs/STATUS.md)
- [`FINDINGS_3REGIME.md`](FINDINGS_3REGIME.md)
- `analysis/three_regime/operating_envelope.csv`
- `analysis/three_regime/operating_envelope_efficiency.csv`

## Current committed headline facts

- The three-regime campaign is the active source of truth.
- The committed unified-method CC headline is **2.44488972 W at T = 1.5 s, VGM-0**.
- The old repository-wide "clean CC → opt_passive → ff+PID relay" framing is no longer
  accurate after the hinge-basis correction.

## Reproducing the current post-processing

```bash
python3 scripts/retabulate_hydro_columns.py --verify
python3 scripts/three_regime_comparison.py --plot-only
python3 scripts/cc_capture_efficiency_sweep.py --plot-only
python3 scripts/capture_efficiency_sweep.py --plot-only
python3 scripts/cc_vs_ffpid_comparison.py --plot-only
```
