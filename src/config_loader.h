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
    double clip_torque{5.0};        ///< [N·m]
};

struct PIDConfig {
    double kp{0.5};
    double ki{0.05};
    double kd{0.05};
    double tau_d{0.02};             ///< [s] derivative filter time constant
    double u_min{-5.0};             ///< [N·m]
    double u_max{5.0};              ///< [N·m]
};

struct ExcFFPIDConfig {
    double alpha{1.0};              ///< feedforward gain on F_exc
    double theta_ref{0.0};          ///< [rad] reference angle
    PIDConfig pid;
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
    double inertia_yy{0.15};        ///< [kg·m²] (flap only)
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

    // Hydro
    std::string h5_file;
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
