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
// │   Active control law: τ_pto = −B_ctrl·θ̇ + PID(alpha·F_exc − θ̇)         │
// │                       (clamped; returned torque already uses restoring)   │
// └──────────────────────────────────────────────────────────────────────────┘
// =============================================================================
#pragma once
#ifndef VGOSWEC_ACTIVE_PTO_H
#define VGOSWEC_ACTIVE_PTO_H

#include <memory>
#include <seastack/pto/pto_model.h>
#include "excitation_force_provider.h"
#include "pid_controller.h"

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
// (D) ExcitationVelocityController — stabilized velocity-tracking absorber
//     τ_pto = −B_ctrl · θ̇ + PID(alpha · F_exc,pitch(t) − θ̇)   (clamped)
//
//   This is the Korde/Ringwood stabilized velocity-tracking structure:
//   a guaranteed-dissipative damping floor −B_ctrl·θ̇ bounds the response,
//   while an inner velocity PID drives flap velocity toward
//   vel_ref = alpha · F_exc,pitch(t). alpha is SIGNED; the default negative
//   value accounts for the current hinge-referred excitation sign mismatch.
//
//   The older open-loop excitation feedforward term was removed because,
//   empirically, it only approximated additional damping rather than genuine
//   reactive control. Under this file's sign convention, the returned torque
//   already follows the restoring convention; there is no outer negation.
//
//   passive_safe: when true, any candidate torque that would inject energy
//   (tau * vel > 0) is replaced by the guaranteed-dissipative damping floor
//   −B_ctrl · vel before applying the final clip. This guard allows alpha/PID
//   gains to be tuned aggressively without risk of net energy injection.
// =============================================================================
class ExcitationVelocityController : public seastack::pto::IPTOModel {
 public:
    ExcitationVelocityController(std::shared_ptr<ExcitationForceProvider> src,
                                 double B_ctrl,
                                 double alpha,
                                 std::unique_ptr<PIDController> pid,
                                 double clip_torque = 5.0,
                                 bool passive_safe = true);

    double ComputeForce(double disp, double vel, double t) override;

 private:
    std::shared_ptr<ExcitationForceProvider> f_exc_source_;
    double B_ctrl_;
    double alpha_;
    double clip_;
    bool   passive_safe_;
    std::unique_ptr<PIDController> pid_;
};

}  // namespace vgoswec

#endif  // VGOSWEC_ACTIVE_PTO_H
