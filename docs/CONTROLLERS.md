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

## (D) ExcitationVelocityController (`exc_ff_pid`)

### Formula
```
vel_ref = alpha · F_exc,pitch(t)
τ_pto = clamp( −B_ctrl · θ̇ + PID_vel(vel_ref − θ̇), -clip_torque, clip_torque )
```

### Sub-components
- **Damping floor** (`−B_ctrl · θ̇`): guaranteed dissipative feedback. With `B_ctrl ≥ 0` this term always opposes velocity and CANNOT inject energy into the system, bounding the response and preventing runaway — the same proven-stable structure as `PassiveDamper`.
- **Velocity inner loop** (`PID_vel(vel_ref − θ̇)`): the Korde/Ringwood-style tracking loop that drives the flap toward a phase-aligned reference velocity `vel_ref = alpha · F_exc`.

`alpha` is **SIGNED** and defaults **negative** because the effective hinge-referred excitation currently has the opposite sign from the raw pitch excitation moment exposed by `ExcitationForceProvider`. A later follow-up can fix the excitation referral directly; for now the sign is carried by `alpha`.

The previous open-loop excitation feedforward term was removed because sweep testing showed it only approximated additional damping (and eventually over-damped toward lockup), rather than delivering genuine reactive control.

### Parameters
| Name | Default | Units | Notes |
|------|---------|-------|-------|
| `B_ctrl` | 0.5 | N·m·s/rad | Stability damping floor (always dissipative). |
| `alpha` | -2.0 | (rad/s)/(N·m) | SIGNED velocity-reference gain, `vel_ref = alpha·F_exc`. |
| `clip_torque` | 5.0 | N·m | Final output saturation clamp. |
| `vel_pid.kp` | 1.0 | N·m per (rad/s) | Velocity-error proportional gain. |
| `vel_pid.ki` | 0.0 | N·m/(rad/s·s) | Velocity-error integral gain. |
| `vel_pid.kd` | 0.0 | N·m·s/(rad/s) | Velocity-error derivative gain. |
| `vel_pid.tau_d` | 0.02 | s | Derivative filter time constant. |
| `vel_pid.u_min` / `vel_pid.u_max` | -5.0 / 5.0 | N·m | Clamp on the PID term only. |

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
4. **ExcFF+PID**: Choose `B_ctrl` for a stable absorbing baseline (start 0.5); then tune the velocity loop: set `alpha` (negative) and `kp` to track `vel_ref = alpha·F_exc`. Watch that improvements come from tracking, NOT from collapsing velocity toward lockup.

All gains are seed values based on order-of-magnitude estimates. **Tank-test data required** to identify inertia (bifilar pendulum) and validate gains.
