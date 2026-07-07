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

// ─── (D) ExcitationFeedforwardPID ────────────────────────────────────────────

ExcitationFeedforwardPID::ExcitationFeedforwardPID(
    std::shared_ptr<ExcitationForceProvider> src,
    double alpha,
    std::unique_ptr<PIDController> pid,
    double theta_ref)
    : f_exc_source_(std::move(src)),
      alpha_(alpha),
      pid_(std::move(pid)),
      theta_ref_(theta_ref) {
    pid_->SetSetpoint(theta_ref_);
}

double ExcitationFeedforwardPID::ComputeForce(double disp, double vel, double t) {
    (void)vel;
    const double tau_ff  = alpha_ * f_exc_source_->GetLatestExcitationTorque();
    const double tau_pid = pid_->Compute(disp, t);
    return tau_ff + tau_pid;
}

}  // namespace vgoswec
