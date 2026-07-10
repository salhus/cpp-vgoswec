// active_pto.cpp
#include "active_pto.h"

#include <algorithm>
#include <cmath>

namespace vgoswec {

namespace {

double ApplyThetaLimit(double tau, double disp, double theta_clip_rad) {
    if (theta_clip_rad <= 0.0) {
        return tau;
    }
    // Safety rule at the small-angle boundary:
    //   - if disp >= +clip and torque would increase theta further (tau < 0),
    //   - if disp <= -clip and torque would decrease theta further (tau > 0),
    // clamp commanded torque to zero so the controller cannot actively drive
    // farther into the limit. (Positive tau opposes positive theta.)
    if ((disp >= theta_clip_rad && tau < 0.0) || (disp <= -theta_clip_rad && tau > 0.0)) {
        return 0.0;
    }
    return tau;
}

double ApplyTorqueClip(double tau, double clip, bool enabled) {
    if (!enabled) {
        return tau;
    }
    return std::clamp(tau, -clip, clip);
}

}  // namespace

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

ComplexConjugateControl::ComplexConjugateControl(double K_r,
                                                 double B_r,
                                                 double clip_torque,
                                                 double theta_clip_rad,
                                                 bool torque_clip_enabled)
    : K_r_(K_r),
      B_r_(B_r),
      clip_(clip_torque),
      theta_clip_rad_(theta_clip_rad),
      torque_clip_enabled_(torque_clip_enabled) {}

double ComplexConjugateControl::ComputeForce(double disp, double vel, double /*t*/) {
    double tau = -K_r_ * disp - B_r_ * vel;
    tau = ApplyThetaLimit(tau, disp, theta_clip_rad_);
    return ApplyTorqueClip(tau, clip_, torque_clip_enabled_);
}

// ─── (D) ExcitationVelocityController ────────────────────────────────────────

ExcitationVelocityController::ExcitationVelocityController(
    std::shared_ptr<ExcitationForceProvider> src,
    double B_ctrl,
    double alpha,
    std::unique_ptr<PIDController> pid,
    double clip_torque,
    bool passive_safe,
    double theta_clip_rad,
    bool torque_clip_enabled)
    : f_exc_source_(std::move(src)),
      B_ctrl_(B_ctrl),
      alpha_(alpha),
      clip_(clip_torque),
      passive_safe_(passive_safe),
      theta_clip_rad_(theta_clip_rad),
      torque_clip_enabled_(torque_clip_enabled),
      pid_(std::move(pid)) {}

double ExcitationVelocityController::ComputeForce(double disp, double vel, double t) {
    const double f_exc = f_exc_source_->GetLatestExcitationTorque();
    const double vel_ref = alpha_ * f_exc;
    pid_->SetSetpoint(vel_ref);
    const double tau_pid = pid_->Compute(vel, t);
    const double tau_damp = -B_ctrl_ * vel;
    double tau = tau_damp + tau_pid;
    // Passive-safety guard: if the candidate torque would inject energy into
    // the system (tau * vel > 0 means torque acts in the direction of motion),
    // replace it with the guaranteed-dissipative damping floor. The floor
    // cannot inject energy because it always opposes velocity.
    if (passive_safe_ && (tau * vel > 0.0)) {
        tau = tau_damp;
    }
    tau = ApplyThetaLimit(tau, disp, theta_clip_rad_);
    return ApplyTorqueClip(tau, clip_, torque_clip_enabled_);
}

}  // namespace vgoswec
