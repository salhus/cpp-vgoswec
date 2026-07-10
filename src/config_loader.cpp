// config_loader.cpp
#include "config_loader.h"

#include <stdexcept>
#include <yaml-cpp/yaml.h>

namespace vgoswec {

namespace {

// Helper: read optional scalar with default
template <typename T>
T ReadOpt(const YAML::Node& node, const std::string& key, T def) {
    if (node[key]) return node[key].as<T>();
    return def;
}

WaveConfig ParseWave(const YAML::Node& n) {
    WaveConfig w;
    w.type        = ReadOpt<std::string>(n, "type",         "regular");
    w.height      = ReadOpt<double>(n, "height",            0.05);
    w.period      = ReadOpt<double>(n, "period",            1.5);
    w.direction   = ReadOpt<double>(n, "direction",         0.0);
    w.gamma       = ReadOpt<double>(n, "gamma",             3.3);
    w.n_components= ReadOpt<int>(n, "n_components",         200);
    w.seed        = ReadOpt<int>(n, "seed",                 42);
    return w;
}

BodyConfig ParseBody(const YAML::Node& n) {
    BodyConfig b;
    b.mesh       = ReadOpt<std::string>(n, "mesh", "");
    b.mass       = ReadOpt<double>(n, "mass", 1.0);
    b.inertia_yy = ReadOpt<double>(n, "inertia_yy", 0.21);
    // inertia_xx and inertia_zz default to inertia_yy when not specified (isotropic fallback)
    b.inertia_xx = ReadOpt<double>(n, "inertia_xx", b.inertia_yy);
    b.inertia_zz = ReadOpt<double>(n, "inertia_zz", b.inertia_yy);
    b.initial_pitch = ReadOpt<double>(n, "initial_pitch", 0.0);
    if (n["cog"] && n["cog"].IsSequence()) {
        b.cog[0] = n["cog"][0].as<double>();
        b.cog[1] = n["cog"][1].as<double>();
        b.cog[2] = n["cog"][2].as<double>();
    }
    return b;
}

PIDConfig ParsePID(const YAML::Node& n) {
    PIDConfig p;
    p.kp    = ReadOpt<double>(n, "kp",    1.0);
    p.ki    = ReadOpt<double>(n, "ki",    0.0);
    p.kd    = ReadOpt<double>(n, "kd",    0.0);
    p.tau_d = ReadOpt<double>(n, "tau_d", 0.02);
    p.u_min = ReadOpt<double>(n, "u_min", -5.0);
    p.u_max = ReadOpt<double>(n, "u_max",  5.0);
    return p;
}

ControllerConfig ParseController(const YAML::Node& n) {
    ControllerConfig ctrl;
    ctrl.type = ReadOpt<std::string>(n, "type", "passive");

    if (n["passive"]) {
        const auto& p = n["passive"];
        ctrl.passive.B_pto       = ReadOpt<double>(p, "B_pto",       0.5);
        ctrl.passive.clip_torque = ReadOpt<double>(p, "clip_torque", 5.0);
    }
    if (n["opt_passive"]) {
        const auto& p = n["opt_passive"];
        ctrl.opt_passive.design_omega = ReadOpt<double>(p, "design_omega", 0.0);
        ctrl.opt_passive.clip_torque  = ReadOpt<double>(p, "clip_torque",  5.0);
    }
    if (n["cc"]) {
        const auto& p = n["cc"];
        ctrl.cc.K_r_override = ReadOpt<double>(p, "K_r_override", 0.0);
        ctrl.cc.B_r_override = ReadOpt<double>(p, "B_r_override", 0.0);
        ctrl.cc.clip_torque  = ReadOpt<double>(p, "clip_torque",  5.0);
    }
    if (n["exc_ff_pid"]) {
        const auto& p = n["exc_ff_pid"];
        ctrl.exc_ff_pid.B_ctrl       = ReadOpt<double>(p, "B_ctrl",       0.5);
        ctrl.exc_ff_pid.alpha        = ReadOpt<double>(p, "alpha",        -2.0);
        ctrl.exc_ff_pid.clip_torque  = ReadOpt<double>(p, "clip_torque",  5.0);
        ctrl.exc_ff_pid.passive_safe = ReadOpt<bool>(p,   "passive_safe", true);
        if (p["vel_pid"]) ctrl.exc_ff_pid.vel_pid = ParsePID(p["vel_pid"]);
    }
    return ctrl;
}

}  // anonymous namespace

SimConfig LoadConfig(const std::string& yaml_path) {
    YAML::Node root;
    try {
        root = YAML::LoadFile(yaml_path);
    } catch (const YAML::Exception& e) {
        throw std::runtime_error("YAML parse error in '" + yaml_path + "': " + e.what());
    }

    SimConfig cfg;

    if (root["simulation"]) {
        const auto& s = root["simulation"];
        cfg.duration   = ReadOpt<double>(s, "duration",  60.0);
        cfg.timestep   = ReadOpt<double>(s, "timestep",  0.005);
        cfg.wave_ramp  = ReadOpt<double>(s, "wave_ramp", 10.0);
    }

    if (root["body"]) {
        if (root["body"]["flap"]) cfg.flap = ParseBody(root["body"]["flap"]);
        if (root["body"]["base"]) cfg.base = ParseBody(root["body"]["base"]);
    }

    if (root["hinge"]) {
        cfg.hinge_z = ReadOpt<double>(root["hinge"], "position_z", -0.7658);
        cfg.hinge_external_stiffness = ReadOpt<double>(root["hinge"], "external_stiffness", 0.0);
    }

    if (root["hydro"]) {
        cfg.h5_file = ReadOpt<std::string>(root["hydro"], "h5_file", "");
        cfg.impedance_h5_file = ReadOpt<std::string>(root["hydro"], "impedance_h5_file", "");
        cfg.rho     = ReadOpt<double>(root["hydro"], "rho", 1025.0);
    }
    if (cfg.h5_file.empty())
        throw std::runtime_error("Config '" + yaml_path + "' missing hydro.h5_file");

    if (root["wave"])  cfg.wave       = ParseWave(root["wave"]);
    if (root["controller"]) cfg.controller = ParseController(root["controller"]);

    return cfg;
}

}  // namespace vgoswec
