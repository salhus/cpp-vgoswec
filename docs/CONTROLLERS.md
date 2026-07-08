# VGOSWEC-45 PTO Controllers

## Sign convention

| Symbol | Meaning | Units |
|--------|---------|-------|
| θ | Flap angle from upright equilibrium | rad |
| θ̇ (ω) | Flap angular velocity | rad/s |
| τ_pto | PTO torque about hinge Y-axis (returned by `ComputeForce`) | N·m |
| P_abs | Absorbed power: P_abs = −τ_pto · ω (positive = extracted from waves) | W |

**Restoring convention**: positive τ opposes positive θ.

---

## (A) PassiveDamper

### Formula
```
τ = −B_pto · ω
```

### Parameters
| Name | Symbol | Default | Units |
|------|--------|---------|-------|
| `B_pto` | B_pto | 0.5 | N·m·s/rad |
| `clip_torque` | — | 5.0 | N·m |

### Notes
- Simplest baseline.
- No energy input to the ocean. Always stable.
- **Tune**: increase B_pto until flap motion degrades; back off 20%.

---

## (B) OptimalPassive

### Formula
```
τ = −B_opt · ω
```

### Gain derivation
```
B_opt = |Z_intrinsic(ω₀)|
Z_intrinsic = B_rad,55(ω₀) + i · [ω₀·(I_flap + A₅₅(ω₀)) − K_hs,55/ω₀]
```

Frequency-domain coefficients A(ω₀), B(ω₀) are computed from the stored RIRF via numerical Fourier cosine/sine transform (`impedance.cpp`). See `PitchImpedanceMagnitude()`.

### Parameters
| Name | Symbol | Notes |
|------|--------|-------|
| `design_omega` | ω₀ | If 0 in config, derived from `wave.period` |
| `clip_torque` | — | — |

---

## (C) ComplexConjugateControl

### Formula
```
τ = −K_r · θ − B_r · ω
```

### Gain derivation (from impedance.cpp)
```
K_r =  ω₀² · (I_flap + A₅₅(ω₀)) − K_hs,55   (intrinsic pitch reactance to be cancelled)
B_r =  B_rad,55(ω₀)
```

At ω₀, CC control achieves maximum power absorption for a single-frequency wave (Budal/Falnes theorem). It requires reactive PTO (power input during part of the cycle).

### Parameters
`K_r_override` and `B_r_override` (both zero = auto-compute from H5).

### Warning
CC control requires bidirectional power flow. A physical PTO must support reactive operation (e.g., active motor/generator). Add conservative `clip_torque`.

---

## (D) ExcitationFeedforwardPID

### Formula
```
τ = α · F_exc,pitch(t)  +  PID(θ_ref − θ)
```

### Sub-components
- **Feedforward** (`α · F_exc`): uses real-time wave excitation torque from `ExcitationForceProvider`. Requires `HydroSystem::SetPerComponentCaptureEnabled(true)`.
- **PID** (`PID(θ_ref − θ)`): full PID with filtered derivative (time constant τ_d) and anti-windup back-calculation. Keeps flap near `θ_ref` (default: 0 = upright).

### PID parameters
| Name | Default | Notes |
|------|---------|-------|
| `kp` | 0.5 | N·m/rad |
| `ki` | 0.05 | N·m/(rad·s) |
| `kd` | 0.05 | N·m·s/rad |
| `tau_d` | 0.02 s | ≈ 4× timestep |
| `u_min/u_max` | ±5 N·m | Saturation clamp |

**All gains marked TODO: tune with tank-test data.**

### One-step delay
`ExcitationForceProvider` is updated after each `DoStepDynamics` call. The RSDA functor reads excitation from the previous step (≈ 0.005 s delay vs T=1.5 s wave period → negligible).

---

## HIL interface

All four controllers implement `seastack::pto::IPTOModel`:
```cpp
virtual double ComputeForce(double displacement, double velocity, double time) = 0;
```

To replace any controller with a hardware-in-the-loop (HIL) implementation, derive from `IPTOModel` and pass to `RsdaPtoFunctor`. See `docs/HIL_MIGRATION.md`.

---

## Tuning guide (wave-tank scale)

1. **Start with PassiveDamper**. Verify flap motion is physical (no divergence).
2. **OptimalPassive**: theoretical maximum for passive control. Compare with step 1.
3. **CC control**: compare peak torque vs clip. Reduce clip until stable.
4. **ExcFF+PID**: set α=0 first (pure PID), tune kp/ki/kd, then increase α from 0.

All gains are seed values based on order-of-magnitude estimates. **Tank-test data required** to identify inertia (bifilar pendulum) and validate gains.
