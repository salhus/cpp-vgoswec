#pragma once
// =============================================================================
// config_loader.h
// Loads YAML simulation configuration into a plain struct.
// =============================================================================
#ifndef VGOSWEC_CONFIG_LOADER_H
#define VGOSWEC_CONFIG_LOADER_H

#include <array>
#include <string>

namespace vgoswec {

// ─── Wave params ─────────────────────────────────────────────────────────────

struct WaveConfig {
    std::string type{"regular"};    ///< "regular" | "jonswap" | "none" (free-decay / no incident wave)
    double height{0.05};            ///< [m]  H (regular) or Hs (JONSWAP)
    double period{1.5};             ///< [s]  T (regular) or Tp (JONSWAP)
    double direction{0.0};          ///< [rad]
    double gamma{3.3};              ///< JONSWAP peak-enhancement factor
    int    n_components{200};       ///< JONSWAP spectral components
    int    seed{42};                ///< JONSWAP random seed
};

// ─── PTO / controller params ──────────────────────────────────────────────────

struct PassiveConfig {
    double B_pto{0.5};              ///< [N·m·s/rad]
    double clip_torque{5.0};        ///< [N·m]
};

struct OptPassiveConfig {
    double design_omega{0.0};       ///< [rad/s] 0 = derive from wave.period
    double clip_torque{5.0};        ///< [N·m]
};

struct CCConfig {
    double K_r_override{0.0};       ///< [N·m/rad]   0 = compute from HydroData
    double B_r_override{0.0};       ///< [N·m·s/rad] 0 = compute from HydroData
    double clip_torque{5.0};        ///< [N·m] optional legacy torque clip magnitude
    bool   torque_clip_enabled{false}; ///< default false: rely on theta clip safety
    double theta_clip_rad{1.0};     ///< [rad] small-angle pitch guard
};

struct PIDConfig {
    double kp{1.0};
    double ki{0.0};
    double kd{0.0};
    double tau_d{0.02};             ///< [s] derivative filter time constant
    double u_min{-5.0};             ///< [N·m]
    double u_max{5.0};              ///< [N·m]
};

struct ExcFFPIDConfig {
    double B_ctrl{0.5};       ///< [N·m·s/rad] stability damping floor: tau += -B_ctrl*theta_dot (always dissipative)
    double alpha{-2.0};       ///< [(rad/s)/(N·m)] SIGNED velocity-reference gain: vel_ref = alpha*F_exc (negative for hinge sign)
    double clip_torque{5.0};  ///< [N·m] optional legacy output saturation magnitude
    bool   torque_clip_enabled{false}; ///< default false: rely on theta clip safety
    double theta_clip_rad{1.0};  ///< [rad] small-angle pitch guard
    bool   passive_safe{true};///< If true, replace any energy-injecting command (tau*vel > 0) with the dissipative floor -B_ctrl*vel
    PIDConfig vel_pid;        ///< velocity-error PID (gains/clamp). Note vel_pid.u_min/u_max clamp the PID term only.
};

struct ControllerConfig {
    std::string type{"passive"};    ///< "passive" | "opt_passive" | "cc" | "exc_ff_pid"
    PassiveConfig  passive;
    OptPassiveConfig opt_passive;
    CCConfig       cc;
    ExcFFPIDConfig exc_ff_pid;
};

// ─── Body params ─────────────────────────────────────────────────────────────

struct BodyConfig {
    std::string mesh;
    double mass{1.0};
    std::array<double, 3> cog{0.0, 0.0, 0.0};
    /// CG-referenced inertia components [kg·m²] (flap only).
    /// Chrono builds the body about its CG; the revolute constraint automatically
    /// synthesises the parallel-axis term m·r_g² when the CG swings on its arc, so
    /// SetInertiaXX must receive the CG value (not the hinge value).
    /// Pitch about hinge Y-axis = body Iyy (body frame = world frame when upright).
    /// Default 0.21 kg·m² is the WEC-Sim-validated CG pitch inertia.
    /// The hinge pitch inertia used by the analytic impedance formulas is
    ///   I_hinge = I_cg + m·r_g² = 0.21 + 6.676·0.265² = 0.652 kg·m².
    double inertia_xx{0.32};        ///< [kg·m²] CG roll inertia  (about body X)
    double inertia_yy{0.21};        ///< [kg·m²] CG pitch inertia (about body Y = hinge axis)
    double inertia_zz{0.12};        ///< [kg·m²] CG yaw inertia   (about body Z)
    double initial_pitch{0.0};      ///< [rad] initial pitch about hinge Y-axis
};

// ─── Top-level SimConfig ──────────────────────────────────────────────────────

struct SimConfig {
    // Simulation
    double duration{60.0};          ///< [s]
    double timestep{0.005};         ///< [s]
    double wave_ramp{10.0};         ///< [s] linear wave-ramp duration

    // Bodies
    BodyConfig flap;
    BodyConfig base;

    // Hinge
    double hinge_z{-0.7658};        ///< [m]
    /// External torsional spring stiffness at the hinge [N·m/rad].
    /// This is a PHYSICAL spring present in the experimental apparatus for ALL
    /// configurations.  C_ext = 6.57 N·m/rad for both VGM-45 and VGM-0
    /// (Ogden et al., ASME JOMAE 145(3):030905, Table 1).
    /// Because it is a pure torsional (couple) spring, its CG-referred value
    /// equals the hinge value exactly — no parallel-axis shift needed.
    /// Default 0.0 (disabled) so existing behaviour is opt-in; set to 6.57 in
    /// all VGM config files.
    double hinge_external_stiffness{0.0};

    // Hydro
    std::string h5_file;
    /// Optional H5 file used ONLY for frequency-domain impedance / CC-gain
    /// computation (hinge-referenced coefficients). If empty, falls back to
    /// h5_file. The time-domain HydroSystem always uses h5_file.
    std::string impedance_h5_file;   ///< default "" => use h5_file
    double rho{1025.0};             ///< [kg/m³]

    // Wave
    WaveConfig wave;

    // Controller
    ControllerConfig controller;
};

// ─── Loader ──────────────────────────────────────────────────────────────────

/// Load SimConfig from a YAML file.
/// Throws std::runtime_error on missing required fields or bad values.
SimConfig LoadConfig(const std::string& yaml_path);

}  // namespace vgoswec

#endif  // VGOSWEC_CONFIG_LOADER_H
