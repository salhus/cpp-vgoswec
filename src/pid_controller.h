#pragma once
// =============================================================================
// pid_controller.h
// Full PID controller with filtered derivative and anti-windup.
//
// Extends seastack::control::IController.
//
// Transfer function in s-domain:
//   u(s) = kp·e(s) + ki·e(s)/s + kd·s·e(s) / (tau_d·s + 1)
//
// Implementation uses backward Euler (suitable for dt ≈ 0.005 s).
// =============================================================================
#ifndef VGOSWEC_PID_CONTROLLER_H
#define VGOSWEC_PID_CONTROLLER_H

#include <seastack/control/controller.h>

namespace vgoswec {

struct PIDParams {
    double kp{0.5};         ///< Proportional gain [N·m/rad]
    double ki{0.05};        ///< Integral gain     [N·m/(rad·s)]
    double kd{0.05};        ///< Derivative gain   [N·m·s/rad]
    double tau_d{0.02};     ///< Derivative filter time constant [s]
    double u_min{-5.0};     ///< Output clamp lower bound [N·m]
    double u_max{5.0};      ///< Output clamp upper bound [N·m]
    double dt_expected{0.005}; ///< Nominal timestep [s] (used for init only)
};

/// Full PID with:
///   - Filtered derivative:  D · s / (tau_d · s + 1)
///   - Anti-windup via back-calculation (integrator only advances when unsaturated)
///   - Output clamp [u_min, u_max]
///
/// Units: measurement/setpoint are application-defined, output is [N·m].
class PIDController : public seastack::control::IController {
 public:
    explicit PIDController(const PIDParams& params);

    /// Set the reference (setpoint) value.
    void SetSetpoint(double setpoint) { setpoint_ = setpoint; }
    double GetSetpoint() const { return setpoint_; }

    /// Compute control output.
    /// @param measurement  Current measured process variable
    /// @param time         Current simulation time [s] (used to compute dt)
    /// @return             PTO torque command [N·m]
    double Compute(double measurement, double time) override;

    /// Reset integrator and derivative state.
    void Reset() override;

 private:
    PIDParams params_;
    double setpoint_{0.0};

    // State
    double integral_{0.0};      ///< Accumulated integral term
    double deriv_state_{0.0};   ///< Filtered derivative output D[k-1]
    double prev_error_{0.0};    ///< Error at previous call (for discrete derivative)
    double prev_time_{-1.0};    ///< Simulation time at previous call
};

}  // namespace vgoswec

#endif  // VGOSWEC_PID_CONTROLLER_H
