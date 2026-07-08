// demo_vgoswec.cpp (minimal, headless-safe)

#include "active_pto.h"
#include "config_loader.h"
#include "excitation_force_provider.h"
#include "impedance.h"
#include "pid_controller.h"
#include "rsda_pto_functor.h"

#include <seastack/adapters/chrono/helper.h>
#include <seastack/adapters/chrono/hydro_system.h>
#include <seastack/hydro/waves/component_sampler.h>
#include <seastack/hydro/waves/linear_directional_wave_field.h>
#include <seastack/hydro/waves/wave_base.h>
#include <seastack/hydro_io/h5_reader.h>

#ifdef VGOSWEC_HAVE_SEASTACK_GUIHELPER
#include <gui/guihelper.h>
#endif

#include <chrono/assets/ChVisualShapeBox.h>
#include <chrono/physics/ChBodyEasy.h>
#include <chrono/physics/ChLinkLock.h>
#include <chrono/physics/ChLinkMate.h>
#include <chrono/physics/ChLinkRSDA.h>
#include <chrono/physics/ChSystemNSC.h>

#ifdef VGOSWEC_HAVE_CHRONO_VSG
#include <chrono_vsg/ChVisualSystemVSG.h>
using namespace chrono::vsg3d;
#endif

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <limits>
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
  bool simple_viz{false};
  bool hydro_report{false};
  double duration_override{-1.0};
  double wave_period_override{-1.0};
  double wave_height_override{-1.0};
};

static void PrintUsage(const char* argv0) {
  std::cout << "Usage: " << argv0 << " --config <path.yaml> [OPTIONS]\n"
            << "  --controller <name>  passive|opt_passive|cc|exc_ff_pid\n"
            << "  --data-dir <path>\n"
            << "  --no-viz             Headless (no window); takes precedence over --simple-viz\n"
            << "  --simple-viz         Render flap as a box via plain Chrono VSG (no SEA-Stack water surface)\n"
            << "  --duration <s>\n"
            << "  --wave-period <s>\n"
            << "  --wave-height <m>\n"
            << "  --hydro-report       Print de-normalized hydro coefficients and P_opt at fixed periods, then exit\n";
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
    } else if (a == "--simple-viz") {
      args.simple_viz = true;
    } else if (a == "--duration" && i + 1 < argc) {
      args.duration_override = std::stod(argv[++i]);
    } else if (a == "--wave-period" && i + 1 < argc) {
      args.wave_period_override = std::stod(argv[++i]);
    } else if (a == "--wave-height" && i + 1 < argc) {
      args.wave_height_override = std::stod(argv[++i]);
    } else if (a == "--hydro-report") {
      args.hydro_report = true;
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

static std::shared_ptr<WaveBase> BuildWaveField(const vgoswec::SimConfig& cfg) {
  if (cfg.wave.type == "none") {
    return std::make_shared<NoWave>();
  }

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
    const std::string& h5_file,
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
    const double B_opt = vgoswec::PitchImpedanceMagnitude(
        hydro_data, h5_file, 0, omega0, cfg.flap.inertia_yy);
    return std::make_shared<vgoswec::OptimalPassive>(B_opt, cfg.controller.opt_passive.clip_torque);
  }

  if (type == "cc") {
    double K_r = cfg.controller.cc.K_r_override;
    double B_r = cfg.controller.cc.B_r_override;
    if (K_r == 0.0 && B_r == 0.0) {
      const auto gains = vgoswec::ComputeCCGains(
          hydro_data, h5_file, 0, omega0, cfg.flap.inertia_yy);
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

}  // namespace

int main(int argc, char* argv[]) {
  const auto args = ParseCLI(argc, argv);
  auto cfg = vgoswec::LoadConfig(args.config_path);
  if (args.wave_period_override > 0.0) {
    cfg.wave.period = args.wave_period_override;
  }
  if (args.wave_height_override > 0.0) {
    cfg.wave.height = args.wave_height_override;
  }
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

  if (cfg.wave.type == "regular") {
    const double wave_h = cfg.wave.height;
    const double wave_a = 0.5 * wave_h;
    if (!(wave_h > 0.0)) {
      throw std::runtime_error("Regular-wave height must be > 0");
    }
    std::cout << "=== WAVE INPUT (regular) ===\n"
              << "  period T   = " << cfg.wave.period << " s\n"
              << "  omega      = " << (2.0 * M_PI / cfg.wave.period) << " rad/s\n"
              << "  height H   = " << wave_h << " m (config field 'wave.height')\n"
              << "  amplitude A= " << wave_a << " m (A = H/2 used by SEA-Stack regular wave)\n"
              << "============================\n";
  }

  if (args.hydro_report) {
    constexpr int kBody = 0;
    constexpr double kB55Floor = 1e-9;
    const std::vector<double> periods_s{6.00, 4.49, 3.42, 3.00, 2.50, 2.00, 1.57};
    const double rho_match_omega = (cfg.controller.opt_passive.design_omega > 0.0)
                                       ? cfg.controller.opt_passive.design_omega
                                       : 2.0 * M_PI / cfg.wave.period;
    const double wave_a = (cfg.wave.type == "regular") ? (0.5 * cfg.wave.height) : 0.0;

    std::cout << "HYDRO_REPORT_HEADER,T_s,omega_rads,A55_kgm2,B55_Nmsrad,"
              << "Fexc55_Nm_per_m,wave_A_m,F_exc_Nm,P_opt_W,B55_floor_applied\n";
    for (const double T_s : periods_s) {
      const double omega = 2.0 * M_PI / T_s;
      const auto coeffs = vgoswec::GetPitchHydroCoefficientsAtOmega(
          hydro_data, h5_file, kBody, omega, rho_match_omega);
      const double F_exc = coeffs.Fexc55 * wave_a;
      const bool floor_applied = coeffs.B55 < kB55Floor;
      const double B55_for_power = floor_applied ? kB55Floor : coeffs.B55;
      const double P_opt = (F_exc * F_exc) / (8.0 * B55_for_power);
      std::cout << std::fixed << std::setprecision(6)
                << "HYDRO_REPORT_ROW," << T_s
                << "," << omega
                << "," << coeffs.A55
                << "," << coeffs.B55
                << "," << coeffs.Fexc55
                << "," << wave_a
                << "," << F_exc
                << "," << P_opt
                << "," << (floor_applied ? 1 : 0)
                << "\n";
    }
    return 0;
  }

  ChSystemNSC system;
  system.SetGravitationalAcceleration(ChVector3d(0, 0, -9.81));
  system.SetSolverType(ChSolver::Type::GMRES);

  auto flap_body = chrono_types::make_shared<ChBodyEasyMesh>(flap_mesh, 1000.0, false, true, false);
  system.Add(flap_body);
  flap_body->SetName("body1");
  flap_body->SetPos(ChVector3d(cfg.flap.cog[0], cfg.flap.cog[1], cfg.flap.cog[2]));
  flap_body->SetMass(cfg.flap.mass);
  // Inertia about CG (SEA-Stack's native reference frame).
  // Body frame = world frame when the flap is upright; the revolute is initialized with
  // QuatFromAngleX(PI/2) so its free-rotation Z-axis aligns with world Y (the hinge axis).
  // Pitch about the hinge Y-axis therefore corresponds to body Iyy.
  // I_flap (= inertia_yy = 0.21 kg·m²) used by the impedance/CC gain path must be the
  // same CG-referenced value to be consistent with SEA-Stack's CG-referenced A₅₅ / K_hs,55.
  flap_body->SetInertiaXX(ChVector3d(cfg.flap.inertia_xx, cfg.flap.inertia_yy, cfg.flap.inertia_zz));
  // NOTE: initial_pitch is applied AFTER all joints are initialized (see below) so that
  // the revolute/RSDA zero-reference is set at theta=0 and the IC is correctly reported.

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

  // Revolute constraint: 5-DOF hinge, free rotation about world Y-axis
  auto revolute = chrono_types::make_shared<ChLinkLockRevolute>();
  revolute->Initialize(base_body, flap_body, ChFrame<>(hinge_pos, hinge_rot));
  system.AddLink(revolute);

  auto waves = BuildWaveField(cfg);
  std::vector<std::shared_ptr<ChBody>> bodies{flap_body, base_body};
  seastack::chrono::HydroSystem hydro_system(bodies, h5_file, waves);
  hydro_system.SetPerComponentCaptureEnabled(true);

  auto exc_provider = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
  auto controller = BuildController(cfg, args.controller_override, h5_file, hydro_data, exc_provider);

  // RSDA: applies PTO torque at every force-assembly sub-step via RsdaPtoFunctor.
  // This replaces the per-outer-step ChLinkMotorRotationTorque + ChFunctionConst pattern.
  auto rsda = chrono_types::make_shared<ChLinkRSDA>();
  rsda->Initialize(base_body, flap_body, false,
                   ChFramed(hinge_pos, hinge_rot), ChFramed(hinge_pos, hinge_rot));
  rsda->RegisterTorqueFunctor(std::make_shared<vgoswec::RsdaPtoFunctor>(controller));
  system.AddLink(rsda);

  // Apply initial pitch AFTER all joints are initialized.
  // The revolute and RSDA capture theta=0 as their reference when the flap is at its
  // nominal (upright) position.  Rotating the flap here means rsda->GetAngle() will
  // correctly return initial_pitch (≈theta0) at the first simulation step instead of 0.
  if (std::abs(cfg.flap.initial_pitch) > std::numeric_limits<double>::epsilon()) {
    const double cos_pitch = std::cos(cfg.flap.initial_pitch);
    const double sin_pitch = std::sin(cfg.flap.initial_pitch);
    const double cog_x = cfg.flap.cog[0];
    const double cog_y = cfg.flap.cog[1];
    const double cog_z_relative = cfg.flap.cog[2] - cfg.hinge_z;
    flap_body->SetPos(ChVector3d(cos_pitch * cog_x + sin_pitch * cog_z_relative,
                                 cog_y,
                                 cfg.hinge_z - sin_pitch * cog_x + cos_pitch * cog_z_relative));
    flap_body->SetRot(QuatFromAngleY(cfg.flap.initial_pitch));
  }

  // ── HYDRO DIAGNOSTIC (printed once at startup, side-effect free) ─────────────
  {
    const std::string ctrl_type = args.controller_override.empty()
                                    ? cfg.controller.type
                                    : args.controller_override;
    const double omega0 = (cfg.controller.opt_passive.design_omega > 0.0)
                              ? cfg.controller.opt_passive.design_omega
                              : 2.0 * M_PI / cfg.wave.period;
    constexpr int kBody = 0;
    const double K_hs55   = hydro_data.GetHydrostaticStiffnessVal(kBody, 4, 4);
    const double A55_inf  = hydro_data.GetInfAddedMassMatrix(kBody)(4, 4);
    const auto coeffs_h5  = vgoswec::GetPitchHydroCoefficientsAtOmega(
        hydro_data, h5_file, kBody, omega0, omega0);
    const auto [A55, B55] = std::pair<double, double>{coeffs_h5.A55, coeffs_h5.B55};
    const double I_cg   = cfg.flap.inertia_yy;
    // C_ext: external spring stiffness for free-decay (cc with override and no damping).
    const double C_ext = (ctrl_type == "cc"
                           && cfg.controller.cc.K_r_override != 0.0
                           && cfg.controller.cc.B_r_override == 0.0)
                          ? cfg.controller.cc.K_r_override
                          : 0.0;
    // Guarded natural-frequency prediction (two estimates: A55_inf and A55(omega0))
    const double num_pred     = K_hs55 + C_ext;
    const double den_pred_inf = I_cg + A55_inf;
    const double den_pred_lf  = I_cg + A55;    // A55 = A55(omega0) already computed above

    std::cout << "=== HYDRO DIAGNOSTIC (flap pitch, about CG) ===\n"
              << "  omega0       = " << omega0   << " rad/s\n"
              << "  K_hs55       = " << K_hs55  << " N*m/rad\n"
              << "  rho_eff      = " << coeffs_h5.rho_eff << " kg/m^3 (A55 match)\n"
              << "  H5 rho       = " << coeffs_h5.h5_rho << " kg/m^3\n"
              << "  H5 g         = " << coeffs_h5.g << " m/s^2\n"
              << "  A55(omega0) [H5]     = " << A55      << " kg*m^2\n"
              << "  A55(omega0) [legacy] = " << coeffs_h5.A55_existing << " kg*m^2\n"
              << "  B55(omega0) [H5]     = " << B55      << " N*m*s/rad\n"
              << "  Fexc55(omega0) [H5]  = " << coeffs_h5.Fexc55 << " N*m per unit wave amplitude\n"
              << "  A55_inf      = " << A55_inf  << " kg*m^2\n"
              << "  I_cg         = " << I_cg     << " kg*m^2\n"
              << "  C_ext        = " << C_ext    << " N*m/rad\n";
    if (num_pred <= 0.0) {
      std::cout << "  omega_n_pred = N/A (K_hs+C_ext <= 0: hydrostatically unstable without spring)\n"
                << "  Ts_pred      = N/A\n";
    } else {
      if (den_pred_inf > 0.0) {
        const double wn_inf = std::sqrt(num_pred / den_pred_inf);
        std::cout << "  omega_n_pred (A55_inf) = " << wn_inf
                  << " rad/s  [high-freq asymptote, A55_inf=" << A55_inf << " kg*m^2]\n"
                  << "  Ts_pred      (A55_inf) = " << 2.0 * M_PI / wn_inf << " s\n";
      }
      if (den_pred_lf > 0.0) {
        const double wn_lf = std::sqrt(num_pred / den_pred_lf);
        std::cout << "  omega_n_pred (A55(w0)) = " << wn_lf
                  << " rad/s  [better predictor, A55(w0)=" << A55 << " kg*m^2]\n"
                  << "  Ts_pred      (A55(w0)) = " << 2.0 * M_PI / wn_lf << " s\n"
                  << "  Note: measured free-decay ~1.83 rad/s => eff. added mass ~1.4 kg*m^2 (low-freq > A55_inf)\n";
      }
    }
    if (ctrl_type == "cc") {
      double diag_K_r = cfg.controller.cc.K_r_override;
      double diag_B_r = cfg.controller.cc.B_r_override;
      if (diag_K_r == 0.0 && diag_B_r == 0.0) {
        const auto gains = vgoswec::ComputeCCGains(hydro_data, h5_file, kBody, omega0, I_cg);
        diag_K_r = gains.K_r;
        diag_B_r = gains.B_r;
      }
      std::cout << "  K_r (CC)     = " << diag_K_r << " N*m/rad\n"
                << "  B_r (CC)     = " << diag_B_r << " N*m*s/rad\n";
    }
    std::cout << "================================================\n";
  }

  // ── HYDRO FREQUENCY SWEEP (printed once at startup, side-effect free) ────────
  {
    constexpr int kBodySw  = 0;
    const double K_hs55_sw = hydro_data.GetHydrostaticStiffnessVal(kBodySw, 4, 4);
    const double I_cg_sw   = cfg.flap.inertia_yy;
    const double rho_match_omega = (cfg.controller.opt_passive.design_omega > 0.0)
                                       ? cfg.controller.opt_passive.design_omega
                                       : 2.0 * M_PI / cfg.wave.period;

    // Sweep ω = 1.0–4.0 rad/s (operating band containing VGM 45 resonance at 1.84 rad/s).
    // Δω = 0.1 rad/s (31 rows).  B55 is clamped ≥ 0 in GetPitchRadCoeffsAtOmega
    // (radiation damping is physically non-negative; paper Eq. (1), λ₅,₅ ≥ 0).
    // rho_eff is derived at the controller design ω₀; an extra row is inserted at
    // ω = 1.84 rad/s to mark the VGM 45 natural frequency.
    constexpr double kOmegaVGM45Resonance = 1.84;  // VGM 45 ωₙ ≈ 1.84 rad/s (paper Table 2)
    auto PrintSweepRow = [&](double w_sw, const char* note = nullptr) {
      const double T_sw = 2.0 * M_PI / w_sw;
      const auto [A55_sw, B55_sw] = vgoswec::GetPitchRadCoeffsAtOmega(
          hydro_data, h5_file, kBodySw, w_sw, rho_match_omega);
      const double K_r_sw = w_sw * w_sw * (I_cg_sw + A55_sw) - K_hs55_sw;
      const double B_r_sw = B55_sw;
      std::cout << std::setw(8)  << T_sw
                << std::setw(10) << w_sw
                << std::setw(14) << A55_sw
                << std::setw(15) << B55_sw
                << std::setw(14) << K_r_sw
                << std::setw(15) << B_r_sw;
      if (note) std::cout << "  " << note;
      std::cout << "\n";
    };

    std::cout << "=== HYDRO FREQUENCY SWEEP (flap pitch, about CG) ===\n"
              << std::fixed << std::setprecision(4)
              << std::setw(8)  << "T [s]"
              << std::setw(10) << "w [r/s]"
              << std::setw(14) << "A55[kg*m^2]"
              << std::setw(15) << "B55[N*m*s/r]"
              << std::setw(14) << "K_r[N*m/r]"
              << std::setw(15) << "B_r[N*m*s/r]"
              << "\n";
    // Use integer steps to avoid floating-point accumulation in the loop bound.
    bool resonance_printed = false;
    for (int step = 0; step <= 30; ++step) {
      const double w_sw = 1.0 + step * 0.1;
      // Insert the VGM 45 resonance row (1.84 rad/s) before the first grid point
      // above it, so it always appears in the table regardless of grid alignment.
      if (!resonance_printed && w_sw > kOmegaVGM45Resonance) {
        PrintSweepRow(kOmegaVGM45Resonance, "<-- VGM45 resonance");
        resonance_printed = true;
      }
      PrintSweepRow(w_sw);
    }
    if (!resonance_printed) {
      PrintSweepRow(kOmegaVGM45Resonance, "<-- VGM45 resonance");
    }
    std::cout << std::defaultfloat
              << "====================================================\n";
  }

  // Determine which visualization path to use.
  // use_simple_viz is true when:
  //   - the user explicitly requested --simple-viz, OR
  //   - visualization is on but the SEA-Stack guihelper is not available (automatic fallback).
#ifdef VGOSWEC_HAVE_SEASTACK_GUIHELPER
  constexpr bool have_guihelper = true;
#else
  constexpr bool have_guihelper = false;
#endif
  const bool use_simple_viz =
      args.simple_viz ||
      (args.visualization_on && !have_guihelper);

  // Attach box visual shapes for the plain-VSG renderer.  These are visual-only:
  // no mass, inertia, or collision geometry is added.  Only added when the
  // simple-viz path will be used to avoid changing the guihelper path's appearance.
  if (use_simple_viz) {
    // ChBodyEasyMesh is constructed with visualize=true (see body construction above),
    // so it auto-creates a triangle-mesh visual asset from the .obj/.STL file.  Those
    // mesh visuals have unallocated GPU vertex/index buffers in Chrono's VSG binding,
    // which causes vsg::VertexIndexDraw::record() to segfault with VK_NULL_HANDLE
    // buffers on the first rendered frame.  Clear the auto-created visual model first
    // so that the box shapes below are the ONLY visuals submitted to the VSG pipeline.
    if (flap_body->GetVisualModel())
      flap_body->GetVisualModel()->Clear();
    if (base_body->GetVisualModel())
      base_body->GetVisualModel()->Clear();

    // Flap: thin plate (~0.02 m × 0.30 m × 0.30 m). Thin along local X so the
    // plate face is visible as the flap swings about the hinge (world Y).
    auto flap_box = chrono_types::make_shared<ChVisualShapeBox>(0.02, 0.30, 0.30);
    flap_box->SetColor(ChColor(0.2f, 0.5f, 0.8f));
    flap_body->AddVisualShape(flap_box);

    // Base/hinge marker: small cube at the base body CoG to help orient the view.
    auto base_box = chrono_types::make_shared<ChVisualShapeBox>(0.05, 0.05, 0.05);
    base_box->SetColor(ChColor(0.6f, 0.6f, 0.6f));
    base_body->AddVisualShape(base_box);
  }

  std::vector<Record> records;
  records.reserve(static_cast<size_t>(sim_duration / cfg.timestep) + 100);

  const double dt = cfg.timestep;

  if (!args.visualization_on) {
    // ── Headless loop ────────────────────────────────────────────────────────
    while (system.GetChTime() <= sim_duration) {
      system.DoStepDynamics(dt);

      const auto& per_comp = hydro_system.GetLastComponentForces();
      if (!per_comp.empty()) {
        exc_provider->Update(per_comp, system.GetChTime());
      }

      // Read all logged quantities AFTER the step so every CSV column is consistent
      // at this record's timestamp (system.GetChTime()). Reading angle/velocity
      // before the step previously introduced a one-timestep skew vs. torque/time.
      const double pitch_rad = rsda->GetAngle();
      const double pitch_vel = rsda->GetVelocity();
      const double exc_tau   = exc_provider->GetLatestExcitationTorque();
      // GetTorque() is expected to return the applied PTO actuator torque about the
      // hinge Y-axis, matching the sign of RsdaPtoFunctor/IPTOModel::ComputeForce
      // and the docs/CONTROLLERS.md convention (positive torque opposes positive theta;
      // P_abs = -tau*omega).  Quick validation: in a `passive` run, pto_torque_nm
      // should have the OPPOSITE sign to flap_pitch_vel_rads, yielding net-positive
      // power_w.  If it does not, negate pto_tau here (logging-only) to restore the
      // documented convention.
      const double pto_tau   = rsda->GetTorque();

      records.push_back(
          {system.GetChTime(), pitch_rad, pitch_vel, pto_tau, exc_tau, -pto_tau * pitch_vel});
    }
  } else if (use_simple_viz) {
    // ── Simple plain-VSG box renderer (no SEA-Stack water surface) ───────────
    // Uses ChVisualSystemVSG directly, mirroring Chrono's demo_VSG_shapes and the
    // HIL chrono_flap_node init_visualization()/run() pattern. Avoids the
    // VertexIndexDraw::record() segfault that occurs when the animated water
    // surface mesh is added after Initialize() (unfixed upstream SEA-Stack bug).
#ifdef VGOSWEC_HAVE_CHRONO_VSG
    auto vis = chrono_types::make_shared<ChVisualSystemVSG>();
    vis->AttachSystem(&system);
    vis->SetWindowTitle("VGOSWEC-45 (simple VSG)");
    vis->SetWindowSize(1000, 700);
    vis->AddCamera(ChVector3d(0.0, -3.0, 0.5), ChVector3d(0.0, 0.0, cfg.hinge_z + 0.3));
    vis->SetCameraVertical(CameraVerticalDir::Z);  // world is Z-up (gravity = -Z)
    vis->SetLightIntensity(0.9f);                  // configure directional light intensity
    vis->SetLightDirection(0.5 * CH_PI_2, CH_PI_4);
    vis->Initialize();

    while (vis->Run() && system.GetChTime() <= sim_duration) {
      vis->BeginScene();
      vis->Render();
      vis->EndScene();

      system.DoStepDynamics(dt);

      const auto& per_comp = hydro_system.GetLastComponentForces();
      if (!per_comp.empty()) {
        exc_provider->Update(per_comp, system.GetChTime());
      }

      // Read all logged quantities AFTER the step so every CSV column is consistent
      // at this record's timestamp (system.GetChTime()). Reading angle/velocity
      // before the step previously introduced a one-timestep skew vs. torque/time.
      const double pitch_rad = rsda->GetAngle();
      const double pitch_vel = rsda->GetVelocity();
      const double exc_tau   = exc_provider->GetLatestExcitationTorque();
      // GetTorque() is expected to return the applied PTO actuator torque about the
      // hinge Y-axis, matching the sign of RsdaPtoFunctor/IPTOModel::ComputeForce
      // and the docs/CONTROLLERS.md convention (positive torque opposes positive theta;
      // P_abs = -tau*omega).  Quick validation: in a `passive` run, pto_torque_nm
      // should have the OPPOSITE sign to flap_pitch_vel_rads, yielding net-positive
      // power_w.  If it does not, negate pto_tau here (logging-only) to restore the
      // documented convention.
      const double pto_tau   = rsda->GetTorque();

      records.push_back(
          {system.GetChTime(), pitch_rad, pitch_vel, pto_tau, exc_tau, -pto_tau * pitch_vel});
    }
#else
    std::cerr << "ERROR: --simple-viz requested but this build does not include Chrono VSG.\n"
              << "Rebuild with Chrono VSG support or use --no-viz.\n";
    return 2;
#endif
  } else {
    // ── SEA-Stack guihelper path (unchanged) ─────────────────────────────────
#ifdef VGOSWEC_HAVE_SEASTACK_GUIHELPER
    // GUI path: CreateUI(true) -> real VSG renderer; CreateUI(false) -> headless no-op.
    // A single loop driven by ui.IsRunning() works for both visual and headless runs.
    auto pui = seastack::viz::CreateUI(args.visualization_on);
    seastack::viz::UI& ui = *pui;
    ui.Init(&system, "VGOSWEC-45");
    ui.SetCamera(0, -3.0, 0.5, 0, 0, -0.5);
    ui.SetWaveModel(waves);

    while (system.GetChTime() <= sim_duration) {
      if (!ui.IsRunning(dt)) break;
      if (ui.simulationStarted) {
        system.DoStepDynamics(dt);

        const auto& per_comp = hydro_system.GetLastComponentForces();
        if (!per_comp.empty()) {
          exc_provider->Update(per_comp, system.GetChTime());
        }

        // Read all logged quantities AFTER the step so every CSV column is consistent
        // at this record's timestamp (system.GetChTime()). Reading angle/velocity
        // before the step previously introduced a one-timestep skew vs. torque/time.
        const double pitch_rad = rsda->GetAngle();
        const double pitch_vel = rsda->GetVelocity();
        const double exc_tau   = exc_provider->GetLatestExcitationTorque();
        // GetTorque() is expected to return the applied PTO actuator torque about the
        // hinge Y-axis, matching the sign of RsdaPtoFunctor/IPTOModel::ComputeForce
        // and the docs/CONTROLLERS.md convention (positive torque opposes positive theta;
        // P_abs = -tau*omega).  Quick validation: in a `passive` run, pto_torque_nm
        // should have the OPPOSITE sign to flap_pitch_vel_rads, yielding net-positive
        // power_w.  If it does not, negate pto_tau here (logging-only) to restore the
        // documented convention.
        const double pto_tau   = rsda->GetTorque();

        records.push_back(
            {system.GetChTime(), pitch_rad, pitch_vel, pto_tau, exc_tau, -pto_tau * pitch_vel});
      }
    }
#else
    // Should not reach here: use_simple_viz would be true when guihelper is absent.
    std::cerr << "ERROR: Visualization requested but GUI support is not available in this build.\n"
              << "Rebuild with GUI support or use --no-viz.\n";
    return 2;
#endif
  }

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
