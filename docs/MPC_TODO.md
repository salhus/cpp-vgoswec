# MPC TODO Roadmap

Future extension: Model Predictive Control (MPC) for the VGOSWEC-45.

## Why MPC

The current ExcitationFeedforwardPID assumes the excitation force is known
perfectly at each instant (from HydroForces::Evaluate) but uses it reactively.
True optimal WEC control requires **preview** of future excitation — MPC
provides this while respecting torque, angle, and power constraints.

## Approach: receding-horizon MPC at wave scale

1. **Prediction model**: linearized pitch dynamics
   ```
   (I + A₅₅) · θ̈ + B_rad,55 · θ̇ + K_hs,55 · θ = F_exc(t) + τ_pto
   ```
   Discretize at dt=0.005 s, horizon N=30 steps (0.15 s ≈ T/10).

2. **Excitation preview**: use causal Kalman filter on wave elevation (pressure
   sensor or wave-gauge upstream) to predict F_exc over the horizon.

3. **Objective**: maximize extracted power while respecting:
   - |τ_pto| ≤ 5 N·m
   - |θ| ≤ θ_max (structural limit)
   - |θ̇| ≤ ω_max

4. **Solver**: small QP (N≤30) can be solved in < 1 ms with OSQP or a
   custom active-set solver. Embed via `osqp-cpp` or `qpOASES`.

## Interface compatibility

MPC would implement `seastack::pto::IPTOModel` (same as current controllers):
```cpp
class MpcPtoModel : public seastack::pto::IPTOModel {
 public:
  double ComputeForce(double disp, double vel, double t) override;
  // ... QP solve using preview of F_exc
};
```

Add `--controller mpc` to CLI and `vgoswec_45_mpc.yaml` config.

## Dependencies to add
- `osqp-cpp` (Apache 2.0): `find_package(osqp REQUIRED)`
- OR: `qpOASES` if already in SEA-Stack dependency chain

## Status
- [ ] Identify upstream wave-gauge sensor (tank test setup)
- [ ] Implement linear state-space discretization
- [ ] Implement causal excitation predictor (Kalman filter on wave elevation)
- [ ] Implement QP formulation and OSQP wrapper
- [ ] Validate against ExcitationFeedforwardPID in simulation
- [ ] Tank-test comparison

## References
- Falnes, J. (2002). *Ocean Waves and Oscillating Systems*. Cambridge UP.
- Ringwood, J. V. et al. (2014). Energy-maximizing control of wave-energy
  converters. *IEEE Trans. Control Systems Technology*, 22(4), 1345–1353.
- Faedo, N. et al. (2017). Optimal control, MPC and MPC-like algorithms for
  wave energy systems. *IFAC Journal of Systems and Control*, 1, 37–56.
