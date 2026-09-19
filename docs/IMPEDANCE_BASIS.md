# Impedance-basis audit — 2026-09-19

This is the canonical record for the 2026-09-19 impedance-model audit.

## Scope

- **`P_capture` / the time-domain plant is correct.**
- The defects were confined to the **analytic gain-computation path** in `src/impedance.cpp` and to configs that selected the wrong H5 basis for gain computation.
- The affected quantity was the controller-side impedance model used by `opt_passive` and CC gain computation, **not** the Chrono/SEA-Stack plant physics.

## The four defects

| defect | symptom | fix |
|---|---|---|
| 1. `K_hs55` not de-normalized | `linear_restoring_stiffness` from BEMIO was used raw instead of `rho*g` scaled | `K_hs55 = raw * rho * g` |
| 2. `opt_passive` using CG H5 | gain computation mixed hinge inertia/spring with CG-referenced `A55/B55/K_hs55` | all `vgoswec_*_opt_passive.yaml` now set `hydro.impedance_h5_file: hydroData/hinged_vgoswec_*.h5`; fallback is explicit + logged |
| 3. gravity-buoyancy couple omitted | analytic model used `K_hs_eff = K_hs55 + C_ext` and missed the measured hinge restoring couple from submerged mass properties | added `hinge.gravity_buoyancy_stiffness`; model now uses `K_hs_eff = K_hs55 + C_ext + K_gb` |
| 4. stale hinge-inertia comments | comments said `I_hinge = 0.652` though runtime/code already used the correct parallel-axis result | comments corrected to `0.6788 kg·m²` |

## Defect 1 — `K_hs55` de-normalization

BEMIO stores `linear_restoring_stiffness` normalized by `rho*g`.

For `hydroData/vgoswec_90.h5`:

- raw `LRS[4][4] = -0.00012315`
- `rho = 1000`
- `g = 9.80665`
- corrected dimensional value: `-0.00012315 * 1000 * 9.80665 = -1.2076889 N·m/rad`

That matches the SEA-Stack hydrostatic-stiffness path used by the time-domain plant. The fix in `src/impedance.cpp` is therefore simply:

```cpp
coeffs.K_hs55 = tables.K_hs55 * rho_eff * tables.g;
```

For `hinged_vgoswec_*.h5`, the LRS dataset is empty, so `K_hs55 = 0` and this fix is a no-op there.

## Defect 2 — basis mismatch (`opt_passive` gains from CG H5)

The non-circular evidence is the spring-sweep estimate of `I + A55`, obtained from the identity

`omega_n^2 * (I + A55) = K_spring + K_gb`.

Regressing `omega_n^2` against the imposed external spring stiffness gives:

- slope `= 1 / (I + A55)`
- x-intercept `= -K_gb`

Measured `I + A55` versus H5 basis:

| flap | measured `I + A55` | hinged H5 | CG H5 |
|---|---:|---:|---:|
| VGM-0 | 6.535 | 6.663 (-1.9%) | ~1.16 |
| VGM-10 | 3.517 | 3.589 (-2.0%) | ~1.16 |
| VGM-20 | 3.078 | 3.155 (-2.4%) | ~1.16 |
| VGM-45 | 2.252 | 2.320 (-2.9%) | ~1.16 |
| VGM-90 | 1.716 | 1.767 (-2.9%) | 1.159 |

The measured value changes by about **3.8×** across flap geometry. The CG basis cannot reproduce that variation; the hinged basis tracks it to within about **3%**. That is the decisive basis-selection evidence.

## Defect 3 — missing gravity-buoyancy restoring couple

The plant still oscillates when `external_stiffness = 0`, so the analytic prediction `K_hs_eff <= 0 => unstable` was physically wrong.

From the spring-sweep x-intercepts:

| flap | `K_gb` [N·m/rad] |
|---|---:|
| VGM-0 | 0.827 |
| VGM-10 | 0.900 |
| VGM-20 | 0.883 |
| VGM-45 | 0.891 |
| VGM-90 | 0.834 |

Mean and spread:

- `K_gb = 0.867 N·m/rad`
- sample spread `±0.032 N·m/rad` (~3.7%)

All five free-decay configs share the same mass properties, so this is a property of the apparatus, not of flap angle. It implies a CB-CG offset of about `13.2 mm` via:

`r_b - r_g = K_gb / (m*g) = 0.867 / (6.676 * 9.81)`.

The model and controller formulas now use:

`K_hs_eff = K_hs55 + C_ext + K_gb`.

## Defect 4 — stale `I_hinge` comments

The runtime already used the correct value:

`I_hinge = 0.21 + 6.676 * 0.265^2 = 0.678822 kg·m²`

Only comments were stale. They now read `0.6788 kg·m²`.

## Spring-sweep reproduction

Prerequisite: build `build/demo_vgoswec` as documented in [`REPRODUCTION.md`](REPRODUCTION.md).

Example: VGM-90 free-decay spring sweep from a clean tree, writing scratch configs under `/tmp`.

```bash
mkdir -p /tmp/vgoswec_springs
for K in 0.0 3.0 6.57 10.0 15.0; do
  python3 - <<'PY' "$K"
from pathlib import Path
import sys, yaml
root = Path('/home/runner/work/cpp-vgoswec/cpp-vgoswec')
out = Path('/tmp/vgoswec_springs') / f'vgm90_K{sys.argv[1].replace(".", "p")}.yaml'
cfg = yaml.safe_load((root / 'config/vgoswec_90_freedecay.yaml').read_text())
cfg['hinge']['external_stiffness'] = float(sys.argv[1])
out.write_text(yaml.safe_dump(cfg, sort_keys=False))
print(out)
PY
  ./build/demo_vgoswec --config "/tmp/vgoswec_springs/vgm90_K${K//./p}.yaml" --no-viz
  mv output/results.csv "/tmp/vgoswec_springs/vgm90_K${K//./p}_results.csv"
done
```

Then extract `omega_n` from zero crossings (same method used during the audit):

```bash
python3 - <<'PY'
import csv, math, numpy as np
from pathlib import Path
for csv_path in sorted(Path('/tmp/vgoswec_springs').glob('*_results.csv')):
    t, th = [], []
    for row in csv.DictReader(csv_path.open()):
        t.append(float(row['time']))
        th.append(float(row.get('pitch_rad') or row.get('theta_rad')))
    t = np.array(t); th = np.array(th)
    m = t > 5.0
    s = np.where(np.diff(np.sign(th[m])))[0]
    T = 2 * np.mean(np.diff(t[m][s]))
    print(csv_path.name, 2 * math.pi / T)
PY
```

Fit `omega_n^2` against the imposed spring stiffness to recover slope `= 1/(I+A55)` and intercept `= -K_gb`.

## Corrected-model validation

Using hinged-frame `A55(omega)` together with `K_eff = C_ext + K_gb = 6.57 + 0.867 = 7.437 N·m/rad`:

| flap | predicted `omega_n` | validated free-decay | error |
|---|---:|---:|---:|
| VGM-0 | 1.0565 | 1.066 | -0.9% |
| VGM-10 | 1.4396 | 1.460 | -1.4% |
| VGM-20 | 1.5353 | 1.557 | -1.4% |
| VGM-45 | 1.7906 | 1.823 | -1.8% |
| VGM-90 | 2.0513 | 2.083 | -1.5% |

All five are within **3%**, versus the previous ~7% bias.

## Circularity caveat

The corrected `omega_n` comparison is **not fully independent** because `K_gb` was itself extracted from free-decay spring-sweep runs. One of those regression points is the nominal `C_ext = 6.57` case.

So the corrected `omega_n` agreement is useful, but it is **partly circular**.

The non-circular result that should lead any argument is the basis-discrimination table above:

- hinged-frame `I + A55` reproduces the measured **3.8×** geometric variation to within ~3%
- CG-frame `I + A55` cannot reproduce that variation at all

That basis comparison is the strongest independent evidence that the analytic gain model must use hinge-referenced impedance data.

## Practical impact by controller arm

| arm | impact |
|---|---|
| `passive` | unaffected — constant `B_pto` from YAML; no impedance H5 lookup |
| `cc` | unaffected in committed results because those configs already used hinged `impedance_h5_file`; code/docs now explicitly include `K_gb` |
| `opt_passive` | **affected** — committed CSVs were generated from the wrong H5 basis and must be re-run |
| `exc_ff_pid` | not revalidated in this audit |
