# CC hinge-impedance validation

`python3 scripts/cc_impedance_hinge_check.py` validates that complex-conjugate (CC) impedance matching uses hinge-referenced BEM coefficients from `hydroData/hinged_vgoswec_*.h5` (body1/flap only; body2/base is fixed and ignored).

The script:
- reads hinge-frame `A55`, `B55`, and `|Fexc55|` from body1 tables,
- de-normalizes with per-file `simulation_parameters/{rho,g,w}`,
- uses constants `I_hinge = 0.658 kg·m²`, `C_ext = 6.57 N·m/rad`, `K_eff = K_hs + C_ext = 6.57` (`K_hs=0`),
- solves hinge resonance self-consistently from `ω_n = sqrt(K_eff / (I_hinge + A55(ω_n)))`,
- computes CC gains at each config `design_omega` (`K_r`, `B_r`) and checks `B_r > 0`,
- reports Budal bound power at design frequency, including `H=0.05 m` (`a=0.025 m`) scaling,
- writes `analysis/cc_hinge/cc_impedance_hinge_summary.csv`.

This is a frequency-domain sanity check for hinge-referenced CC gain inputs (`K_r ≈ 0` when `ω0` is near `ω_n`).
