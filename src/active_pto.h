// =============================================================================
// ┌──────────────────────────────────────────────────────────────────────────┐
// │ active_pto.h — Four pluggable PTO / active-control models for VGOSWEC-45│
// │                                                                          │
// │ SIGN CONVENTION (document once; applies to ALL controllers below):       │
// │   displacement  = flap angle θ from upright equilibrium [rad]            │
// │   velocity      = θ̇ [rad/s]                                             │
// │   returned value = PTO torque about hinge Y-axis [N·m]                   │
// │   Positive torque OPPOSES positive θ (restoring convention)              │
// │   Absorbed power: P_abs = −τ_pto · ω   (positive = extracted from waves)│
// │   Active control law: τ_pto = −B_ctrl·θ̇ + ff_gain·F_exc  (clamped)     │
// └──────────────────────────────────────────────────────────────────────────┘
// =============================================================================
#pragma once
#ifndef VGOSWEC_ACTIVE_PTO_H
#define VGOSWEC_ACTIVE_PTO_H

#include <memory>
#include <seastack/pto/pto_model.h>
#include "excitation_force_provider.h"

namespace vgoswec {

// =============================================================================
// (A) PassiveDamper — baseline linear viscous damper
//     τ = −B_pto · ω
// =============================================================================
class PassiveDamper : public seastack::pto::IPTOModel {
 public:
    explicit PassiveDamper(double B_pto, double clip_torque = 5.0);
    double ComputeForce(double disp, double vel, double t) override;

 private:
    double B_pto_;
    double clip_;
};

// =============================================================================
// (B) OptimalPassive — optimal passive damping at design frequency ω₀
//     B_opt = |Z_intrinsic(ω₀)| (pre-computed by caller via impedance.h)
//     τ = −B_opt · ω
// =============================================================================
class OptimalPassive : public seastack::pto::IPTOModel {
 public:
    explicit OptimalPassive(double B_opt, double clip_torque = 5.0);
    double ComputeForce(double disp, double vel, double t) override;

 private:
    double B_opt_;
    double clip_;
};

// =============================================================================
// (C) ComplexConjugateControl — reactive CC control at ω₀
//     Gains pre-computed by caller via impedance.h::ComputeCCGains():
//       K_r =  ω₀²·(I_flap + A₅₅(ω₀)) − K_hs,55   (intrinsic pitch reactance to be cancelled)
//       B_r =  B_rad,55(ω₀)
//     τ = −K_r · θ − B_r · ω
// =============================================================================
class ComplexConjugateControl : public seastack::pto::IPTOModel {
 public:
    ComplexConjugateControl(double K_r, double B_r, double clip_torque = 5.0);
    double ComputeForce(double disp, double vel, double t) override;

 private:
    double K_r_;
    double B_r_;
    double clip_;
};

// =============================================================================
// (D) ExcitationVelocityController — damping + excitation feedforward
//     τ_pto = −B_ctrl · θ̇ + ff_gain · F_exc,pitch(t)   (clamped to ±clip)
//
//   The −B_ctrl·θ̇ term is guaranteed dissipative (cannot inject energy),
//   giving unconditional stability like PassiveDamper. The ff_gain·F_exc term
//   adds Korde-style phase anticipation using the real-time pitch excitation
//   torque from ExcitationForceProvider. With ff_gain = 0 the controller
//   reduces exactly to a passive damper.
//
//   Under this file's sign convention, positive returned torque opposes
//   positive θ (restoring convention).
// =============================================================================
class ExcitationVelocityController : public seastack::pto::IPTOModel {
 public:
    ExcitationVelocityController(std::shared_ptr<ExcitationForceProvider> src,
                                 double B_ctrl,
                                 double ff_gain,
                                 double clip_torque = 5.0);

    double ComputeForce(double disp, double vel, double t) override;

 private:
    std::shared_ptr<ExcitationForceProvider> f_exc_source_;
    double B_ctrl_;
    double ff_gain_;
    double clip_;
};

}  // namespace vgoswec

#endif  // VGOSWEC_ACTIVE_PTO_H
