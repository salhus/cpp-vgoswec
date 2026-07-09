// active_pto.cpp
#include "active_pto.h"

#include <algorithm>
#include <cmath>

namespace vgoswec {

// ─── (A) PassiveDamper ────────────────────────────────────────────────────────

PassiveDamper::PassiveDamper(double B_pto, double clip_torque)
    : B_pto_(B_pto), clip_(clip_torque) {}

double PassiveDamper::ComputeForce(double /*disp*/, double vel, double /*t*/) {
    return std::clamp(-B_pto_ * vel, -clip_, clip_);
}

// ─── (B) OptimalPassive ───────────────────────────────────────────────────────

OptimalPassive::OptimalPassive(double B_opt, double clip_torque)
    : B_opt_(B_opt), clip_(clip_torque) {}

double OptimalPassive::ComputeForce(double /*disp*/, double vel, double /*t*/) {
    return std::clamp(-B_opt_ * vel, -clip_, clip_);
}

// ─── (C) ComplexConjugateControl ─────────────────────────────────────────────

ComplexConjugateControl::ComplexConjugateControl(double K_r, double B_r, double clip_torque)
    : K_r_(K_r), B_r_(B_r), clip_(clip_torque) {}

double ComplexConjugateControl::ComputeForce(double disp, double vel, double /*t*/) {
    return std::clamp(-K_r_ * disp - B_r_ * vel, -clip_, clip_);
}

// ─── (D) ExcitationVelocityController ────────────────────────────────────────

ExcitationVelocityController::ExcitationVelocityController(
    std::shared_ptr<ExcitationForceProvider> src,
    double alpha,
    double ff_gain,
    std::unique_ptr<PIDController> pid)
    : f_exc_source_(std::move(src)),
      alpha_(alpha),
      ff_gain_(ff_gain),
      pid_(std::move(pid)) {}

double ExcitationVelocityController::ComputeForce(double disp, double vel, double t) {
    (void)disp;
    const double f_exc = f_exc_source_->GetLatestExcitationTorque();
    pid_->SetSetpoint(alpha_ * f_exc);
    const double tau_ff = ff_gain_ * f_exc;
    const double tau_pid = pid_->Compute(vel, t);
    return -(tau_ff + tau_pid);
}

}  // namespace vgoswec
