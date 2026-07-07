// demo_vgoswec.cpp
// =============================================================================
// Standalone VGOSWEC-45 simulation with pluggable active PTO control.
//
// Follows the pattern of SEA-Stack's demos/oswec/demo_oswec_irreg_waves.cpp.
//
// Body ordering (critical — must match H5 file):
//   bodies[0] = flap  → H5 body 1 (index 0 in SEA-Stack)
//   bodies[1] = base  → H5 body 2 (index 1 in SEA-Stack)
//
// Per-component excitation torque path:
//   HydroSystem::SetPerComponentCaptureEnabled(true)
//   → after DoStepDynamics: hydro_system.GetLastComponentForces()
//   → ExcitationForceProvider::Update(per_comp, t)
//   → ExcitationFeedforwardPID::ComputeForce reads it next step (1-step delay, ≈0.005 s)
// =============================================================================

#include "active_pto.h"
#include "config_loader.h"
#include "excitation_force_provider.h"
#include "impedance.h"
#include "rsda_pto_functor.h"
#include "pid_controller.h"

#include <gui/guihelper.h>
#include <seastack/adapters/chrono/helper.h>
#include <seastack/adapters/chrono/hydro_system.h>
#include <seastack/hydro/waves/wave_component.h>
#include <seastack/hydro/waves/component_sampler.h>
#include <seastack/hydro/waves/linear_directional_wave_field.h>
#include <seastack/hydro_io/h5_reader.h>
#include <seastack/infra/logging.h>

#include <chrono/physics/ChBodyEasy.h>
#include <chrono/physics/ChLinkLock.h>
#include <chrono/physics/ChLinkMate.h>
#include <chrono/physics/ChLinkRSDA.h>
#include <chrono/physics/ChSystemNSC.h>
#include <chrono/solver/ChSolverGMRES.h>

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

using namespace chrono;
using namespace seastack::hydro;

// ─── Helper: print usage ──────────────────────────────────────────────────────

static void PrintUsage(const char* argv0) {
    std::cout <<
        "Usage: " << argv0 << " --config <path.yaml> [OPTIONS]\n\n"
        "Options:\n"
        "  --config <path>          YAML config file (required)\n"
        "  --controller <name>      Override controller: passive | opt_passive | cc | exc_ff_pid\n"
        "  --data-dir <path>        Root data directory (default: .)\n"
        "  --no-viz                 Disable visualization (headless)\n"
        "  --duration <s>           Override simulation duration [s]\n"
        "  -h, --help               Show this message\n";
}

// ─── CLI parsing ─────────────────────────────────────────────────────────────

struct CLIArgs {
    std::string config_path;
    std::string controller_override;
    std::string data_dir{"."};
    bool visualization_on{true};
    double duration_override{-1.0};
};

static CLIArgs ParseCLI(int argc, char* argv[]) {
    CLIArgs args;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "-h" || a == "--help") { PrintUsage(argv[0]); std::exit(0); }
        else if (a == "--config"     && i + 1 < argc) args.config_path        = argv[++i];
        else if (a == "--controller" && i + 1 < argc) args.controller_override= argv[++i];
        else if (a == "--data-dir"   && i + 1 < argc) args.data_dir           = argv[++i];
        else if (a == "--no-viz")                     args.visualization_on   = false;
        else if (a == "--duration"   && i + 1 < argc) args.duration_override  = std::stod(argv[++i]);
        else { std::cerr << "Unknown argument: " << a << "\n"; PrintUsage(argv[0]); std::exit(1); }
    }
    if (args.config_path.empty()) {
        std::cerr << "ERROR: --config is required\n";
        PrintUsage(argv[0]);
        std::exit(1);
    }
    return args;
}

// ─── Build wave field from config ─────────────────────────────────────────────

static std::shared_ptr<LinearDirectionalWaveField> BuildWaveField(
    const vgoswec::SimConfig& cfg) {
    SeaStateDefinition sea_state;
    if (cfg.wave.type == "regular") {
        sea_state.type      = "regular";
        sea_state.amplitude = cfg.wave.height / 2.0;   // H/2 = amplitude
        sea_state.omega     = 2.0 * M_PI / cfg.wave.period;
    } else {
        // JONSWAP or other irregular spectrum
        sea_state.type    = "irregular";
        sea_state.n_omega = cfg.wave.n_components;
        sea_state.seed    = cfg.wave.seed;
        SeaStatePartition part;
        part.spectrum.type  = "jonswap";
        part.spectrum.Hs    = cfg.wave.height;
        part.spectrum.Tp    = cfg.wave.period;
        part.spectrum.gamma = cfg.wave.gamma;
        sea_state.partitions.push_back(part);
    }
    auto components = ComponentSampler::Build(sea_state);
    auto waves = std::make_shared<LinearDirectionalWaveField>(
        std::move(components), /*depth=*/0.0);
    waves->SetRampDuration(cfg.wave_ramp);
    return waves;
}

// ─── Build the requested controller ─────────────────────────────────────────

static std::shared_ptr<seastack::pto::IPTOModel> BuildController(
    const vgoswec::SimConfig& cfg,
    const std::string& type_override,
    const seastack::hydro::HydroData& hydro_data,
    std::shared_ptr<vgoswec::ExcitationForceProvider> exc_provider) {

    const std::string type = type_override.empty() ? cfg.controller.type : type_override;
    const double omega0 = (cfg.controller.opt_passive.design_omega > 0.0)
                          ? cfg.controller.opt_passive.design_omega
                          : 2.0 * M_PI / cfg.wave.period;

    std::cout << "[demo_vgoswec] Controller: " << type
              << "  ω₀ = " << omega0 << " rad/s\n";

    if (type == "passive") {
        const auto& p = cfg.controller.passive;
        return std::make_shared<vgoswec::PassiveDamper>(p.B_pto, p.clip_torque);

    } else if (type == "opt_passive") {
        const auto& p = cfg.controller.opt_passive;
        const double B_opt = vgoswec::PitchImpedanceMagnitude(
            hydro_data, /*flap_body_idx=*/0, omega0, cfg.flap.inertia_yy);
        std::cout << "[demo_vgoswec] B_opt = " << B_opt << " N·m·s/rad\n";
        return std::make_shared<vgoswec::OptimalPassive>(B_opt, p.clip_torque);

    } else if (type == "cc") {
        const auto& p = cfg.controller.cc;
        double K_r, B_r;
        if (p.K_r_override != 0.0 || p.B_r_override != 0.0) {
            K_r = p.K_r_override;
            B_r = p.B_r_override;
            std::cout << "[demo_vgoswec] CC gains (override): K_r=" << K_r
                      << " B_r=" << B_r << "\n";
        } else {
            auto gains = vgoswec::ComputeCCGains(
                hydro_data, /*flap_body_idx=*/0, omega0, cfg.flap.inertia_yy);
            K_r = gains.K_r;
            B_r = gains.B_r;
            std::cout << "[demo_vgoswec] CC gains (computed): K_r=" << K_r
                      << " N·m/rad  B_r=" << B_r << " N·m·s/rad\n";
        }
        return std::make_shared<vgoswec::ComplexConjugateControl>(K_r, B_r, p.clip_torque);

    } else if (type == "exc_ff_pid") {
        const auto& p = cfg.controller.exc_ff_pid;
        vgoswec::PIDParams pid_params;
        pid_params.kp          = p.pid.kp;
        pid_params.ki          = p.pid.ki;
        pid_params.kd          = p.pid.kd;
        pid_params.tau_d       = p.pid.tau_d;
        pid_params.u_min       = p.pid.u_min;
        pid_params.u_max       = p.pid.u_max;
        pid_params.dt_expected = cfg.timestep;
        auto pid = std::make_unique<vgoswec::PIDController>(pid_params);
        return std::make_shared<vgoswec::ExcitationFeedforwardPID>(
            exc_provider, p.alpha, std::move(pid), p.theta_ref);

    } else {
        throw std::runtime_error("Unknown controller type: '" + type + "'");
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// main
// ─────────────────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    std::cout << "=== VGOSWEC-45 SEA-Stack Simulation ===\n";

    // ── 1. Parse CLI ─────────────────────────────────────────────────────────
    const auto args = ParseCLI(argc, argv);
    const auto cfg  = vgoswec::LoadConfig(args.config_path);

    const double sim_duration = (args.duration_override > 0.0)
                                ? args.duration_override : cfg.duration;
    const std::string data_dir = args.data_dir;

    // Resolve paths relative to data_dir
    const auto resolve = [&](const std::string& rel) {
        if (std::filesystem::path(rel).is_absolute()) return rel;
        return (std::filesystem::path(data_dir) / rel).lexically_normal().generic_string();
    };
    const std::string h5_file    = resolve(cfg.h5_file);
    const std::string flap_mesh  = resolve(cfg.flap.mesh);
    const std::string base_mesh  = resolve(cfg.base.mesh);

    std::cout << "[demo_vgoswec] H5 file:   " << h5_file   << "\n";
    std::cout << "[demo_vgoswec] Flap mesh: " << flap_mesh << "\n";
    std::cout << "[demo_vgoswec] Base mesh: " << base_mesh << "\n";
    std::cout << "[demo_vgoswec] Duration:  " << sim_duration << " s  dt=" << cfg.timestep << " s\n";

    // ── 2. Load hydro data (needed for impedance / CC gains at startup) ──────
    auto hydro_data = seastack::hydro_io::H5FileInfo(h5_file, /*num_bodies=*/2).ReadH5Data();

    // ── 3. Build Chrono system ───────────────────────────────────────────────
    ChSystemNSC system;
    system.SetGravitationalAcceleration(ChVector3d(0.0, 0.0, -9.81));
    system.SetSolverType(ChSolver::Type::GMRES);

    // ── 4. Bodies ────────────────────────────────────────────────────────────

    // Flap (body 1 in H5 — index 0 in SEA-Stack bodies vector)
    auto flap_body = chrono_types::make_shared<ChBodyEasyMesh>(
        flap_mesh, /*density=*/1000.0, false, true, false);
    system.Add(flap_body);
    flap_body->SetName("body1");
    flap_body->SetPos(ChVector3d(cfg.flap.cog[0], cfg.flap.cog[1], cfg.flap.cog[2]));
    flap_body->SetMass(cfg.flap.mass);
    // Diagonal inertia: I_yy = cfg.flap.inertia_yy; use same value for I_xx, I_zz as placeholder
    flap_body->SetInertiaXX(
        ChVector3d(cfg.flap.inertia_yy, cfg.flap.inertia_yy, cfg.flap.inertia_yy));

    // Base (body 2 in H5 — index 1 in SEA-Stack bodies vector, fixed to ground)
    auto base_body = chrono_types::make_shared<ChBodyEasyMesh>(
        base_mesh, /*density=*/1000.0, false, true, false);
    system.Add(base_body);
    base_body->SetName("body2");
    base_body->SetPos(ChVector3d(cfg.base.cog[0], cfg.base.cog[1], cfg.base.cog[2]));
    base_body->SetMass(cfg.base.mass);
    base_body->SetInertiaXX(ChVector3d(1e6, 1e6, 1e6));

    // Fix base to ground via ChLinkMateGeneric (mimic OSWEC demo pattern)
    auto ground = chrono_types::make_shared<ChBody>();
    system.AddBody(ground);
    ground->SetPos(ChVector3d(cfg.base.cog[0], cfg.base.cog[1], cfg.base.cog[2]));
    ground->SetFixed(true);
    ground->EnableCollision(false);
    auto anchor = chrono_types::make_shared<ChLinkMateGeneric>();
    anchor->Initialize(base_body, ground, false,
                       base_body->GetVisualModelFrame(),
                       base_body->GetVisualModelFrame());
    anchor->SetConstrainedCoords(true, true, true, true, true, true);
    system.Add(anchor);

    // ── 5. Revolute hinge (rotation about world Y) ───────────────────────────
    // QuatFromAngleX(π/2) orients the joint frame so its Z axis ‖ world Y,
    // making ChLinkLockRevolute constrain rotation about world Y.
    const ChVector3d hinge_pos(0.0, 0.0, cfg.hinge_z);
    const ChQuaternion<> hinge_rot = QuatFromAngleX(CH_PI / 2.0);
    auto revolute = chrono_types::make_shared<ChLinkLockRevolute>();
    revolute->Initialize(base_body, flap_body, ChFramed(hinge_pos, hinge_rot));
    system.AddLink(revolute);

    // ── 6. Hydrodynamics ─────────────────────────────────────────────────────
    auto waves = BuildWaveField(cfg);

    std::vector<std::shared_ptr<ChBody>> bodies{flap_body, base_body};
    seastack::chrono::HydroSystem hydro_system(bodies, h5_file, waves);
    hydro_system.SetPerComponentCaptureEnabled(true);  // enable per-component capture

    // ── 7. ExcitationForceProvider ───────────────────────────────────────────
    // flap_body_index=0: flap is first in bodies vector
    // dof_index=4: pitch about Y (BEMIO convention)
    auto exc_provider = std::make_shared<vgoswec::ExcitationForceProvider>(
        /*flap_body_index=*/0, /*dof_index=*/4);

    // ── 8. Build controller ──────────────────────────────────────────────────
    auto controller = BuildController(cfg, args.controller_override, hydro_data, exc_provider);

    // ── 9. Wire PTO via ChLinkRSDA ───────────────────────────────────────────
    // ChLinkRSDA is Chrono 10's Rotational Spring-Damper-Actuator.
    // We use the same hinge frame as the revolute joint.
    auto rsda = chrono_types::make_shared<ChLinkRSDA>();
    rsda->Initialize(base_body, flap_body, false,
                     ChFramed(hinge_pos, hinge_rot),
                     ChFramed(hinge_pos, hinge_rot));
    rsda->RegisterTorqueFunctor(std::make_shared<vgoswec::RsdaPtoFunctor>(controller));
    system.AddLink(rsda);

    // ── 10. Visualization ────────────────────────────────────────────────────
    auto pui = seastack::viz::CreateUI(args.visualization_on);
    auto& ui = *pui;
    ui.Init(&system, "VGOSWEC-45 SEA-Stack Demo");
    ui.SetCamera(0, -3, 0, 0, 0, cfg.hinge_z);
    if (args.visualization_on) ui.SetWaveModel(waves);

    // ── 11. Data storage ─────────────────────────────────────────────────────
    struct Record {
        double t;
        double flap_pitch_rad;
        double flap_pitch_vel;
        double pto_torque_nm;
        double exc_torque_nm;
        double power_w;      ///< Instantaneous absorbed power: P = -τ_pto · ω
    };
    std::vector<Record> records;
    records.reserve(static_cast<size_t>(sim_duration / cfg.timestep) + 100);

    // ── 12. Time loop ─────────────────────────────────────────────────────────
    std::cout << "[demo_vgoswec] Simulation running...\n";
    while (system.GetChTime() <= sim_duration) {
        if (!ui.IsRunning(cfg.timestep)) break;
        if (ui.simulationStarted) {
            system.DoStepDynamics(cfg.timestep);

            const double t = system.GetChTime();

            // Update ExcitationForceProvider from last evaluation's per-component data.
            // Note: 1-step delay (≈0.005 s) is negligible vs wave period (1.5 s).
            exc_provider->Update(hydro_system.GetLastComponentForces(), t);

            // Read flap state from revolute joint angle (relative to hinge frame)
            const double pitch_rad = rsda->GetAngle();
            const double pitch_vel = rsda->GetVelocity();
            const double pto_tau   = rsda->GetTorque();
            const double exc_tau   = exc_provider->GetLatestExcitationTorque();

            records.push_back(Record{
                t, pitch_rad, pitch_vel, pto_tau, exc_tau,
                -pto_tau * pitch_vel  // P_abs = -τ · ω
            });
        }
    }

    // ── 13. Summary ──────────────────────────────────────────────────────────
    if (!records.empty()) {
        double total_energy = 0.0;
        for (size_t i = 1; i < records.size(); ++i) {
            const double dt = records[i].t - records[i-1].t;
            total_energy += records[i].power_w * dt;
        }
        const double dur = records.back().t - records.front().t;
        std::cout << "\n=== RESULTS ===\n"
                  << "Simulated:     " << dur << " s  (" << records.size() << " steps)\n"
                  << "Mean abs power:" << (dur > 0 ? total_energy / dur : 0.0) << " W\n"
                  << "Total energy:  " << total_energy << " J\n";
    }

    // ── 14. CSV output ────────────────────────────────────────────────────────
    const std::string out_dir = "output";
    std::filesystem::create_directories(out_dir);
    const std::string csv_path = out_dir + "/vgoswec_45_results.csv";

    std::ofstream csv(csv_path);
    if (csv.is_open()) {
        csv << std::fixed;
        csv << "time_s,flap_pitch_rad,flap_pitch_vel_rads,"
               "pto_torque_nm,exc_torque_nm,power_w\n";
        for (const auto& r : records) {
            csv << std::setprecision(6) << r.t         << ","
                << std::setprecision(8) << r.flap_pitch_rad  << ","
                                        << r.flap_pitch_vel  << ","
                                        << r.pto_torque_nm   << ","
                                        << r.exc_torque_nm   << ","
                                        << r.power_w         << "\n";
        }
        std::cout << "Results saved to " << csv_path << "\n";
    } else {
        std::cerr << "WARNING: could not write " << csv_path << "\n";
    }

    return 0;
}
