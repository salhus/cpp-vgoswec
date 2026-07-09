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
    double B_ctrl,
    double alpha,
    std::unique_ptr<PIDController> pid,
    double clip_torque)
    : f_exc_source_(std::move(src)),
      B_ctrl_(B_ctrl),
      alpha_(alpha),
      clip_(clip_torque),
      pid_(std::move(pid)) {}

double ExcitationVelocityController::ComputeForce(double /*disp*/, double vel, double t) {
    const double f_exc = f_exc_source_->GetLatestExcitationTorque();
    const double vel_ref = alpha_ * f_exc;
    pid_->SetSetpoint(vel_ref);
    const double tau_pid = pid_->Compute(vel, t);
    const double tau_damp = -B_ctrl_ * vel;
    return std::clamp(tau_damp + tau_pid, -clip_, clip_);
}

}  // namespace vgoswec
