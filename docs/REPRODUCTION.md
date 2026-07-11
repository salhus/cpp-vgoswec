# Simulation reproduction index

This repository contains the full command chain needed to regenerate the
simulation-side datasets used in the VGOSWEC study. With the commands below,
the simulation results, summary CSVs, and figures are reproducible from this
repo alone; subsequent work can therefore be research/writing rather than
pipeline reconstruction.

## Solver prerequisite for `--run` / sweep commands

Any command below that launches `build/demo_vgoswec` requires the documented
SEA-Stack / Chrono build first:

```bash
source scripts/setup_env.sh
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="${CMAKE_PREFIX_PATH}"
cmake --build build -j$(nproc)
```

This produces `build/demo_vgoswec`. Headless workflows use `--no-viz`, so the
optional GUI / VSG stack is not required for CSV-only reproduction.

## Reproduction modes

- **Solver-invoking path**: the initial sweep or `--run` path calls
  `build/demo_vgoswec` and regenerates raw simulation outputs.
- **`--plot-only` path**: regenerates figures from committed CSVs **without**
  calling the solver.

## 1. Free-decay validation foundation

**Purpose:** regenerate the plant-validation basis used by the controller study.

```bash
# Clean-checkout, fully self-contained path: re-run the five free-decay cases,
# re-analyze ζ, then refresh the ω_n summary CSV/figure.
python3 scripts/freedecay_validation.py --run --make-figures
python3 scripts/plot_freedecay_validation.py

# If output/vgoswec_*_freedecay_results.csv already exist locally, reuse them:
python3 scripts/freedecay_validation.py --make-figures
python3 scripts/plot_freedecay_validation.py
```

- **Solver behavior**
  - `scripts/freedecay_validation.py --run --make-figures` invokes
    `build/demo_vgoswec` internally for
    `config/vgoswec_{0,10,20,45,90}_freedecay.yaml`.
  - The companion `scripts/plot_freedecay_validation.py` does **not** invoke
    the solver; it reuses `output/vgoswec_*_freedecay_results.csv` if present.
- **Inputs consumed**
  - Solver configs: `config/vgoswec_{0,10,20,45,90}_freedecay.yaml`
  - Shared analysis helpers: `scripts/freedecay_analysis.py`
  - Raw solver outputs: `output/vgoswec_*_freedecay_results.csv`
- **Outputs produced**
  - `output/vgoswec_{0,10,20,45,90}_freedecay_results.csv`
  - `docs/freedecay_validation.csv`
  - `docs/img/freedecay_validation.png`
  - `docs/img/freedecay_zeta_validation.png`
  - `docs/img/freedecay_zeta_decay_fit.png`

See also: [`docs/freedecay_validation.md`](freedecay_validation.md).

## 2. CC capture-efficiency sweep

```bash
# Re-run the CC sweep (invokes build/demo_vgoswec):
python3 scripts/cc_capture_efficiency_sweep.py

# Reuse committed CSVs and regenerate figures only:
python3 scripts/cc_capture_efficiency_sweep.py --plot-only
```

- **Solver behavior**
  - Default invocation runs the sweep across the shared `T = 0.5–7.0 s` grid
    using `build/demo_vgoswec`.
  - `--plot-only` reuses committed CSVs and does not call the solver.
- **Inputs consumed**
  - Solver configs: `config/vgoswec_{0,10,20,45,90}_cc.yaml`
  - Hydro inputs: `hydroData/vgoswec_{0,10,20,45,90}.h5`
  - `--plot-only` inputs: `analysis/cc/capture_efficiency_VGM{0,10,20,45,90}.csv`
- **Outputs produced**
  - `analysis/cc/capture_efficiency_VGM{0,10,20,45,90}.csv`
  - `analysis/cc/figures/capture_efficiency_VGM{0,10,20,45,90}.png`
  - `analysis/cc/figures/power_breakdown_VGM{0,10,20,45,90}.png`
  - `analysis/cc/figures/capture_efficiency_summary.png`

## 3. ff+PID (`passive_guarded`) capture-efficiency sweep

```bash
# Re-run the tuned exc_ff_pid sweep (invokes build/demo_vgoswec):
python3 scripts/capture_efficiency_sweep.py

# Reuse committed CSVs and regenerate figures only:
python3 scripts/capture_efficiency_sweep.py --plot-only
```

- **Solver behavior**
  - Default invocation runs the sweep across the shared `T = 0.5–7.0 s` grid
    using `build/demo_vgoswec`.
  - `--plot-only` reuses committed CSVs and does not call the solver.
- **Inputs consumed**
  - Solver configs: `config/vgoswec_{0,10,20,45,90}_exc_ff_pid.yaml`
  - Hydro inputs: `hydroData/vgoswec_{0,10,20,45,90}.h5`
  - `--plot-only` inputs:
    `analysis/passive_guarded/capture_efficiency_VGM{0,10,20,45,90}.csv`
- **Outputs produced**
  - `analysis/passive_guarded/capture_efficiency_VGM{0,10,20,45,90}.csv`
  - `analysis/passive_guarded/figures/capture_efficiency_VGM{0,10,20,45,90}.png`
  - `analysis/passive_guarded/figures/capture_efficiency_summary.png`

## 4. opt_passive sweep

```bash
# Re-run the passive + opt_passive sweep (invokes build/demo_vgoswec):
python3 scripts/passive_vs_optpassive_sweep.py

# Reuse committed CSVs and regenerate figures only:
python3 scripts/passive_vs_optpassive_sweep.py --plot-only
```

- **Solver behavior**
  - Default invocation runs both the `passive` and `opt_passive` arms across the
    shared `T = 0.5–7.0 s` grid using `build/demo_vgoswec`.
  - `--plot-only` reuses committed CSVs and does not call the solver.
- **Inputs consumed**
  - Solver configs:
    `config/vgoswec_{0,10,20,45,90}_passive.yaml`,
    `config/vgoswec_{0,10,20,45,90}_opt_passive.yaml`
  - Hydro inputs: `hydroData/vgoswec_{0,10,20,45,90}.h5`
  - `--plot-only` inputs:
    `analysis/passive/capture_efficiency_VGM{0,10,20,45,90}.csv`,
    `analysis/opt_passive/capture_efficiency_VGM{0,10,20,45,90}.csv`
- **Outputs produced**
  - `analysis/passive/capture_efficiency_VGM{0,10,20,45,90}.csv`
  - `analysis/opt_passive/capture_efficiency_VGM{0,10,20,45,90}.csv`
  - `analysis/passive/figures/capture_efficiency_VGM{0,10,20,45,90}.png`
  - `analysis/opt_passive/figures/capture_efficiency_VGM{0,10,20,45,90}.png`
  - `analysis/passive/figures/capture_efficiency_summary.png`
  - `analysis/opt_passive/figures/capture_efficiency_summary.png`
  - `analysis/passive_vs_optpassive/figures/`

## 5. CC vs ff+PID comparison

```bash
python3 scripts/cc_vs_ffpid_comparison.py --plot-only
```

- **Solver behavior**
  - This is an analysis-only overlay script; it consumes existing sweep CSVs and
    does not invoke `build/demo_vgoswec`.
- **Inputs consumed**
  - `analysis/cc/capture_efficiency_VGM{0,10,20,45,90}.csv`
  - `analysis/passive_guarded/capture_efficiency_VGM{0,10,20,45,90}.csv`
- **Outputs produced**
  - `analysis/comparison/figures/cc_vs_ffpid_VGM{0,10,20,45,90}.png`
  - `analysis/comparison/figures/cc_vs_ffpid_efficiency_VGM{0,10,20,45,90}.png`
  - `analysis/comparison/figures/cc_vs_ffpid_summary.png`
  - `analysis/comparison/figures/cc_vs_ffpid_efficiency_summary.png`

## 6. Three-regime relay + operating envelopes

```bash
python3 scripts/three_regime_comparison.py --plot-only
```

- **Solver behavior**
  - This is an analysis-only summary script; it consumes existing sweep CSVs and
    does not invoke `build/demo_vgoswec`.
- **Inputs consumed**
  - `analysis/cc/capture_efficiency_VGM{0,10,20,45,90}.csv`
  - `analysis/opt_passive/capture_efficiency_VGM{0,10,20,45,90}.csv`
  - `analysis/passive_guarded/capture_efficiency_VGM{0,10,20,45,90}.csv`
- **Outputs produced**
  - `analysis/three_regime/figures/three_regime_VGM{0,10,20,45,90}.png`
  - `analysis/three_regime/figures/three_regime_efficiency_VGM{0,10,20,45,90}.png`
  - `analysis/three_regime/figures/three_regime_summary.png`
  - `analysis/three_regime/figures/three_regime_efficiency_summary.png`
  - `analysis/three_regime/figures/operating_envelope.png`
  - `analysis/three_regime/figures/operating_envelope_efficiency.png`
  - `analysis/three_regime/operating_envelope.csv`
  - `analysis/three_regime/operating_envelope_efficiency.csv`

## Bottom line

Only the initial sweep / `--run` commands invoke `build/demo_vgoswec`. All
`--plot-only` paths regenerate figures from committed CSVs **without** the
solver. Together, these commands make the entire simulation side reproducible
from this repo alone.
