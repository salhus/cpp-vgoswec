// pid_controller.cpp
#include "pid_controller.h"

#include <algorithm>
#include <cmath>

namespace vgoswec {

PIDController::PIDController(const PIDParams& params)
    : params_(params) {}

double PIDController::Compute(double measurement, double time) {
    const bool first_call = (prev_time_ < 0.0);
    const double dt = first_call ? params_.dt_expected : (time - prev_time_);
    prev_time_ = time;

    const double error = setpoint_ - measurement;

    // ── Proportional ──────────────────────────────────────────────────────
    const double P = params_.kp * error;

    // ── Derivative with first-order low-pass filter ───────────────────────
    // D(s) = kd · s / (tau_d · s + 1)
    // Backward-Euler discrete:
    //   D[k] = alpha * D[k-1] + (1-alpha) * kd * (e[k] - e[k-1]) / dt
    //   alpha = tau_d / (tau_d + dt)
    const double alpha_d = params_.tau_d / (params_.tau_d + dt);
    const double deriv_error = first_call ? 0.0 : (error - prev_error_) / dt;
    const double D = alpha_d * deriv_state_
                   + (1.0 - alpha_d) * params_.kd * deriv_error;
    prev_error_ = error;

    // ── Raw unsaturated output ────────────────────────────────────────────
    const double u_unsat = P + params_.ki * integral_ + D;

    // ── Saturate ─────────────────────────────────────────────────────────
    const double u = std::clamp(u_unsat, params_.u_min, params_.u_max);

    // ── Anti-windup: back-calculation ─────────────────────────────────────
    // Integrator advances only when output is NOT saturated.
    const bool saturated = (u != u_unsat);
    if (!saturated) {
        integral_ += error * dt;
    }

    // Update derivative state for next call
    deriv_state_ = D;

    return u;
}

void PIDController::Reset() {
    integral_    = 0.0;
    deriv_state_ = 0.0;
    prev_error_  = 0.0;
    prev_time_   = -1.0;
}

}  // namespace vgoswec
