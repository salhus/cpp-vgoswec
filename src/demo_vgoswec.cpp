// demo_vgoswec.cpp (minimal, headless-safe)

#include "active_pto.h"
#include "config_loader.h"
#include "excitation_force_provider.h"
#include "impedance.h"
#include "pid_controller.h"

#include <seastack/adapters/chrono/helper.h>
#include <seastack/adapters/chrono/hydro_system.h>
#include <seastack/hydro/waves/component_sampler.h>
#include <seastack/hydro/waves/linear_directional_wave_field.h>
#include <seastack/hydro_io/h5_reader.h>

#ifdef VGOSWEC_HAVE_SEASTACK_GUIHELPER
#include <gui/guihelper.h>
#endif

#include <chrono/physics/ChBodyEasy.h>
#include <chrono/physics/ChLinkLock.h>
#include <chrono/physics/ChLinkMate.h>
#include <chrono/physics/ChSystemNSC.h>
#include <chrono/physics/ChLinkMotorRotationTorque.h>
#include <chrono/functions/ChFunctionConst.h>

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using namespace chrono;
using namespace seastack::hydro;

namespace {

struct CLIArgs {
  std::string config_path;
  std::string controller_override;
  std::string data_dir{"."};
  bool visualization_on{true};
  double duration_override{-1.0};
};

static void PrintUsage(const char* argv0) {
  std::cout << "Usage: " << argv0 << " --config <path.yaml> [OPTIONS]\n"
            << "  --controller <name>  passive|opt_passive|cc|exc_ff_pid\n"
            << "  --data-dir <path>\n"
            << "  --no-viz\n"
            << "  --duration <s>\n";
}

static CLIArgs ParseCLI(int argc, char* argv[]) {
  CLIArgs args;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "-h" || a == "--help") {
      PrintUsage(argv[0]);
      std::exit(0);
    } else if (a == "--config" && i + 1 < argc) {
      args.config_path = argv[++i];
    } else if (a == "--controller" && i + 1 < argc) {
      args.controller_override = argv[++i];
    } else if (a == "--data-dir" && i + 1 < argc) {
      args.data_dir = argv[++i];
    } else if (a == "--no-viz") {
      args.visualization_on = false;
    } else if (a == "--duration" && i + 1 < argc) {
      args.duration_override = std::stod(argv[++i]);
    } else {
      std::cerr << "Unknown arg: " << a << "\n";
      std::exit(1);
    }
  }

  if (args.config_path.empty()) {
    std::cerr << "ERROR: --config required\n";
    std::exit(1);
  }
  return args;
}

static std::shared_ptr<LinearDirectionalWaveField> BuildWaveField(const vgoswec::SimConfig& cfg) {
  SeaStateDefinition sea_state;
  if (cfg.wave.type == "regular") {
    sea_state.type = "regular";
    sea_state.amplitude = cfg.wave.height / 2.0;
    sea_state.omega = 2.0 * M_PI / cfg.wave.period;
  } else {
    sea_state.type = "irregular";
    sea_state.n_omega = cfg.wave.n_components;
    sea_state.seed = cfg.wave.seed;
    SeaStatePartition part;
    part.spectrum.type = "jonswap";
    part.spectrum.Hs = cfg.wave.height;
    part.spectrum.Tp = cfg.wave.period;
    part.spectrum.gamma = cfg.wave.gamma;
    sea_state.partitions.push_back(part);
  }

  auto components = ComponentSampler::Build(sea_state);
  auto waves = std::make_shared<LinearDirectionalWaveField>(std::move(components), 0.0);
  waves->SetRampDuration(cfg.wave_ramp);
  return waves;
}

static std::shared_ptr<seastack::pto::IPTOModel> BuildController(
    const vgoswec::SimConfig& cfg,
    const std::string& override_type,
    const seastack::hydro::HydroData& hydro_data,
    const std::shared_ptr<vgoswec::ExcitationForceProvider>& exc_provider) {
  const std::string type = override_type.empty() ? cfg.controller.type : override_type;
  const double omega0 = (cfg.controller.opt_passive.design_omega > 0.0)
                            ? cfg.controller.opt_passive.design_omega
                            : 2.0 * M_PI / cfg.wave.period;

  if (type == "passive")
    return std::make_shared<vgoswec::PassiveDamper>(cfg.controller.passive.B_pto,
                                                     cfg.controller.passive.clip_torque);

  if (type == "opt_passive") {
    const double B_opt = vgoswec::PitchImpedanceMagnitude(hydro_data, 0, omega0, cfg.flap.inertia_yy);
    return std::make_shared<vgoswec::OptimalPassive>(B_opt, cfg.controller.opt_passive.clip_torque);
  }

  if (type == "cc") {
    double K_r = cfg.controller.cc.K_r_override;
    double B_r = cfg.controller.cc.B_r_override;
    if (K_r == 0.0 && B_r == 0.0) {
      const auto gains = vgoswec::ComputeCCGains(hydro_data, 0, omega0, cfg.flap.inertia_yy);
      K_r = gains.K_r;
      B_r = gains.B_r;
    }
    return std::make_shared<vgoswec::ComplexConjugateControl>(K_r, B_r, cfg.controller.cc.clip_torque);
  }

  if (type == "exc_ff_pid") {
    vgoswec::PIDParams p{};
    p.kp = cfg.controller.exc_ff_pid.pid.kp;
    p.ki = cfg.controller.exc_ff_pid.pid.ki;
    p.kd = cfg.controller.exc_ff_pid.pid.kd;
    p.tau_d = cfg.controller.exc_ff_pid.pid.tau_d;
    p.u_min = cfg.controller.exc_ff_pid.pid.u_min;
    p.u_max = cfg.controller.exc_ff_pid.pid.u_max;
    p.dt_expected = cfg.timestep;

    auto pid = std::make_unique<vgoswec::PIDController>(p);
    return std::make_shared<vgoswec::ExcitationFeedforwardPID>(
        exc_provider, cfg.controller.exc_ff_pid.alpha, std::move(pid),
        cfg.controller.exc_ff_pid.theta_ref);
  }

  throw std::runtime_error("Unknown controller type: " + type);
}

struct Record {
  double t, th, om, tau_pto, tau_exc, p;
};

static void RunHeadlessLoop(
    ChSystemNSC& system,
    seastack::chrono::HydroSystem& hydro_system,
    const std::shared_ptr<ChBody>& flap_body,
    const std::shared_ptr<ChLinkMotorRotationTorque>& motor,
    const std::shared_ptr<seastack::pto::IPTOModel>& controller,
    const std::shared_ptr<vgoswec::ExcitationForceProvider>& exc_provider,
    double sim_duration,
    double dt,
    std::vector<Record>& records) {
  while (system.GetChTime() <= sim_duration) {
    const double t = system.GetChTime();

    const auto rpy = flap_body->GetRot().GetCardanAnglesXYZ();
    const double pitch_rad = rpy.y();
    const double pitch_vel = flap_body->GetAngVelParent().y();

    const double pto_tau = controller->ComputeForce(pitch_rad, pitch_vel, t);
    motor->SetTorqueFunction(chrono_types::make_shared<ChFunctionConst>(pto_tau));

    system.DoStepDynamics(dt);

    const auto& per_comp = hydro_system.GetLastComponentForces();
    if (!per_comp.empty()) {
      exc_provider->Update(per_comp, system.GetChTime());
    }
    const double exc_tau = exc_provider->GetLatestExcitationTorque();

    records.push_back(
        {system.GetChTime(), pitch_rad, pitch_vel, pto_tau, exc_tau, -pto_tau * pitch_vel});
  }
}

}  // namespace

int main(int argc, char* argv[]) {
  const auto args = ParseCLI(argc, argv);
  const auto cfg = vgoswec::LoadConfig(args.config_path);
  const double sim_duration = (args.duration_override > 0.0) ? args.duration_override : cfg.duration;

  const auto resolve = [&](const std::string& rel) {
    if (std::filesystem::path(rel).is_absolute())
      return rel;
    return (std::filesystem::path(args.data_dir) / rel).lexically_normal().generic_string();
  };

  const std::string h5_file = resolve(cfg.h5_file);
  const std::string flap_mesh = resolve(cfg.flap.mesh);
  const std::string base_mesh = resolve(cfg.base.mesh);

  auto hydro_data = seastack::hydro_io::H5FileInfo(h5_file, 2).ReadH5Data();

  ChSystemNSC system;
  system.SetGravitationalAcceleration(ChVector3d(0, 0, -9.81));
  system.SetSolverType(ChSolver::Type::GMRES);

  auto flap_body = chrono_types::make_shared<ChBodyEasyMesh>(flap_mesh, 1000.0, false, true, false);
  system.Add(flap_body);
  flap_body->SetName("body1");
  flap_body->SetPos(ChVector3d(cfg.flap.cog[0], cfg.flap.cog[1], cfg.flap.cog[2]));
  flap_body->SetMass(cfg.flap.mass);
  flap_body->SetInertiaXX(ChVector3d(cfg.flap.inertia_yy, cfg.flap.inertia_yy, cfg.flap.inertia_yy));

  auto base_body = chrono_types::make_shared<ChBodyEasyMesh>(base_mesh, 1000.0, false, true, false);
  system.Add(base_body);
  base_body->SetName("body2");
  base_body->SetPos(ChVector3d(cfg.base.cog[0], cfg.base.cog[1], cfg.base.cog[2]));
  base_body->SetMass(cfg.base.mass);
  base_body->SetInertiaXX(ChVector3d(1e6, 1e6, 1e6));

  auto ground = chrono_types::make_shared<ChBody>();
  system.AddBody(ground);
  ground->SetPos(ChVector3d(cfg.base.cog[0], cfg.base.cog[1], cfg.base.cog[2]));
  ground->SetFixed(true);
  ground->EnableCollision(false);

  auto anchor = chrono_types::make_shared<ChLinkMateGeneric>();
  anchor->Initialize(base_body, ground, false, base_body->GetVisualModelFrame(), base_body->GetVisualModelFrame());
  anchor->SetConstrainedCoords(true, true, true, true, true, true);
  system.Add(anchor);

  const ChVector3d hinge_pos(0.0, 0.0, cfg.hinge_z);
  const ChQuaternion<> hinge_rot = QuatFromAngleX(CH_PI / 2.0);

  auto motor = chrono_types::make_shared<ChLinkMotorRotationTorque>();
  motor->Initialize(base_body, flap_body, ChFrame<>(hinge_pos, hinge_rot));
  auto tau_fun = chrono_types::make_shared<ChFunctionConst>(0.0);
  motor->SetTorqueFunction(tau_fun);
  system.AddLink(motor);

  auto waves = BuildWaveField(cfg);
  std::vector<std::shared_ptr<ChBody>> bodies{flap_body, base_body};
  seastack::chrono::HydroSystem hydro_system(bodies, h5_file, waves);
  hydro_system.SetPerComponentCaptureEnabled(true);

  auto exc_provider = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
  auto controller = BuildController(cfg, args.controller_override, hydro_data, exc_provider);

  std::vector<Record> records;
  records.reserve(static_cast<size_t>(sim_duration / cfg.timestep) + 100);

  if (args.visualization_on) {
#ifdef VGOSWEC_HAVE_SEASTACK_GUIHELPER
    std::cout << "Visualization requested, but runtime GUI loop is not yet wired in this demo.\n"
              << "Falling back to headless simulation.\n";
#else
    std::cerr << "ERROR: Visualization requested but GUI support is not available in this build.\n"
              << "Rebuild with GUI support or use --no-viz.\n";
    return 2;
#endif
  }

  RunHeadlessLoop(system, hydro_system, flap_body, motor, controller, exc_provider,
                  sim_duration, cfg.timestep, records);

  std::filesystem::create_directories("output");
  std::ofstream csv("output/vgoswec_45_results.csv");
  csv << "time_s,flap_pitch_rad,flap_pitch_vel_rads,pto_torque_nm,exc_torque_nm,power_w\n";
  for (const auto& r : records) {
    csv << std::fixed << std::setprecision(6) << r.t << ","
        << std::setprecision(8) << r.th << ","
        << r.om << "," << r.tau_pto << "," << r.tau_exc << "," << r.p << "\n";
  }

  std::cout << "Results saved to output/vgoswec_45_results.csv\n";
  return 0;
}
