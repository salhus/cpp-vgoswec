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
#include <sstream>
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
  std::vector<double> hydro_periods;  ///< override period list for --hydro-report
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
            << "  --hydro-report       Print de-normalized hydro coefficients and P_opt at fixed periods, then exit\n"
            << "  --hydro-periods <csv>  Comma-separated period list for --hydro-report (e.g. 6.0,4.49,3.42)\n";
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
    } else if (a == "--hydro-periods" && i + 1 < argc) {
      std::string csv = argv[++i];
      std::istringstream ss(csv);
      std::string tok;
      while (std::getline(ss, tok, ',')) {
        if (!tok.empty()) args.hydro_periods.push_back(std::stod(tok));
      }
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
  // External spring C_ext (hinge-referenced) equals its CG-referred value for a
  // pure torsional spring, so pass directly to impedance functions.
  const double C_ext_cg = cfg.hinge_external_stiffness;
  // Hinge-referenced pitch inertia for analytic impedance/gain formulas.
  // The closed-form expressions have no kinematic constraint to synthesise the
  // parallel-axis term m·r_g²; they must use I_hinge = I_cg + m·r_g² = 0.652 kg·m²
  // (= 0.21 + 6.676·0.265² ≈ 0.21 + 0.469 = 0.652, WEC-Sim validated).
  // (Chrono dynamics use I_cg via SetInertiaXX; the revolute constraint adds m·r_g².)
  const double r_g_ctrl = std::abs(cfg.flap.cog[2] - cfg.hinge_z);
  const double I_hinge_ctrl = cfg.flap.inertia_yy + cfg.flap.mass * r_g_ctrl * r_g_ctrl;

  if (type == "passive")
    return std::make_shared<vgoswec::PassiveDamper>(cfg.controller.passive.B_pto,
                                                     cfg.controller.passive.clip_torque);

  if (type == "opt_passive") {
    const double B_opt = vgoswec::PitchImpedanceMagnitude(
        hydro_data, h5_file, 0, omega0, I_hinge_ctrl, C_ext_cg);
    return std::make_shared<vgoswec::OptimalPassive>(B_opt, cfg.controller.opt_passive.clip_torque);
  }

  if (type == "cc") {
    double K_r = cfg.controller.cc.K_r_override;
    double B_r = cfg.controller.cc.B_r_override;
    if (K_r == 0.0 && B_r == 0.0) {
      const auto gains = vgoswec::ComputeCCGains(
          hydro_data, h5_file, 0, omega0, I_hinge_ctrl, C_ext_cg);
      K_r = gains.K_r;
      B_r = gains.B_r;
    }
    return std::make_shared<vgoswec::ComplexConjugateControl>(K_r, B_r, cfg.controller.cc.clip_torque);
  }

  if (type == "exc_ff_pid") {
    vgoswec::PIDParams p{};
    p.kp = cfg.controller.exc_ff_pid.vel_pid.kp;
    p.ki = cfg.controller.exc_ff_pid.vel_pid.ki;
    p.kd = cfg.controller.exc_ff_pid.vel_pid.kd;
    p.tau_d = cfg.controller.exc_ff_pid.vel_pid.tau_d;
    p.u_min = cfg.controller.exc_ff_pid.vel_pid.u_min;
    p.u_max = cfg.controller.exc_ff_pid.vel_pid.u_max;
    p.dt_expected = cfg.timestep;

    auto pid = std::make_unique<vgoswec::PIDController>(p);
    return std::make_shared<vgoswec::ExcitationVelocityController>(
        exc_provider,
        cfg.controller.exc_ff_pid.alpha,
        cfg.controller.exc_ff_pid.ff_gain,
        std::move(pid));
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
    // Use CLI-specified periods if given; otherwise fall back to the VGM-45
    // default sweep band (6.00–1.57 s).  Pass device-specific periods via
    // --hydro-periods to cover VGM-0 resonance (T ≈ 5.86 s).
    const std::vector<double> periods_s = args.hydro_periods.empty()
        ? std::vector<double>{6.00, 4.49, 3.42, 3.00, 2.50, 2.00, 1.57}
        : args.hydro_periods;
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
  // Inertia about CG — SetInertiaXX receives the CG value (0.21 kg·m²), NOT the hinge
  // value (0.652 kg·m²).  The revolute constraint at the hinge automatically synthesises
  // the parallel-axis term m·r_g² when the CG swings on its arc, so passing the hinge
  // inertia here would double-count m·r_g² and drive the dynamic resonance too low.
  // Body frame = world frame when the flap is upright; the revolute is initialized with
  // QuatFromAngleX(PI/2) so its free-rotation Z-axis aligns with world Y (the hinge axis).
  // Pitch about the hinge Y-axis therefore corresponds to body Iyy.
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

  // External hinge spring: physical restoring spring at the hinge, present in
  // the experimental apparatus for ALL configurations (passive, opt_passive, cc,
  // exc_ff_pid, freedecay).  C_ext = 6.57 N·m/rad (Table 1) for VGM-45 and VGM-0.
  // Applied as a separate RSDA with SetSpringCoefficient so the spring torque
  // τ = -C_ext · θ is added to the flap body independently of the PTO torque.
  // NOTE: for CC, the computed K_r already accounts for this spring via K_hs_eff
  // in ComputeCCGains (K_r = ω0²(I+A55) − K_hs_eff), so there is NO double-counting.
  std::shared_ptr<ChLinkRSDA> spring_rsda;
  if (cfg.hinge_external_stiffness > 0.0) {
    spring_rsda = chrono_types::make_shared<ChLinkRSDA>();
    spring_rsda->Initialize(base_body, flap_body, false,
                            ChFramed(hinge_pos, hinge_rot), ChFramed(hinge_pos, hinge_rot));
    spring_rsda->SetSpringCoefficient(cfg.hinge_external_stiffness);
    system.AddLink(spring_rsda);
  }

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
    // Hinge-referenced inertia for the natural-frequency prediction.
    // The analytic ωn formula has no kinematic constraint to add m·r_g²; it must
    // use I_hinge = I_cg + m·r_g² = 0.652 kg·m² (= 0.21 + 6.676·0.265², WEC-Sim validated).
    // (Chrono's revolute constraint already adds m·r_g² dynamically from I_cg.)
    const double r_g_diag   = std::abs(cfg.flap.cog[2] - cfg.hinge_z);
    const double I_hinge    = I_cg + cfg.flap.mass * r_g_diag * r_g_diag;
    // C_ext: external hinge spring from config (all controllers, all times).
    const double C_ext = cfg.hinge_external_stiffness;
    // K_hs_eff: combined hydrostatic + external spring restoring stiffness (CG-referenced).
    // C_ext is a pure torsional spring so its CG-referred value equals the hinge value.
    const double K_hs_eff = K_hs55 + C_ext;
    // Guarded natural-frequency prediction (two estimates: A55_inf and A55(omega0)).
    // Uses I_hinge so the denominator is (I_hinge + A55) ≈ (0.652 + 0.904) = 1.556 kg·m²
    // → ωn ≈ sqrt(5.37/1.556) ≈ 1.86 rad/s for VGM-45 (WEC-Sim free-decay: 1.84 rad/s).
    // VGM-0 analytic single-DOF prediction is ~7% high vs WEC-Sim free-decay (1.07 rad/s);
    // this is expected and acceptable — the authoritative value is the WEC-Sim free-decay.
    const double num_pred     = K_hs_eff;
    const double den_pred_inf = I_hinge + A55_inf;
    const double den_pred_lf  = I_hinge + A55;    // A55 = A55(omega0) already computed above

    std::cout << "=== HYDRO DIAGNOSTIC (flap pitch, hinge-referenced) ===\n"
              << "  omega0       = " << omega0   << " rad/s\n"
              << "  K_hs55       = " << K_hs55  << " N*m/rad\n"
              << "  rho_used     = " << coeffs_h5.rho_eff << " kg/m^3 (H5 rho)\n"
              << "  rho_legacy   = " << coeffs_h5.rho_eff_match << " kg/m^3 (A55 match, diagnostic only)\n"
              << "  H5 g         = " << coeffs_h5.g << " m/s^2\n"
              << "  A55(omega0) [H5]     = " << A55      << " kg*m^2\n"
              << "  A55(omega0) [legacy] = " << coeffs_h5.A55_existing << " kg*m^2\n"
              << "  B55(omega0) [H5]     = " << B55      << " N*m*s/rad\n"
              << "  Fexc55(omega0) [H5]  = " << coeffs_h5.Fexc55 << " N*m per unit wave amplitude\n"
              << "  A55_inf      = " << A55_inf  << " kg*m^2\n"
              << "  I_cg         = " << I_cg     << " kg*m^2  (Chrono body inertia; revolute adds m*r_g^2)\n"
              << "  r_g          = " << r_g_diag  << " m  (CG above hinge)\n"
              << "  I_hinge      = " << I_hinge  << " kg*m^2  (= I_cg + m*r_g^2; used in impedance math)\n"
              << "  C_ext (hinge)= " << C_ext    << " N*m/rad  [torsional spring, CG-referred = same]\n"
              << "  K_hs_eff     = " << K_hs_eff << " N*m/rad  (K_hs55 + C_ext)\n";
    if (num_pred <= 0.0) {
      std::cout << "  omega_n_pred = N/A (K_hs_eff <= 0: hydrostatically unstable)\n"
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
                  << " rad/s  [best predictor, A55(w0)=" << A55 << " kg*m^2]\n"
                  << "  Ts_pred      (A55(w0)) = " << 2.0 * M_PI / wn_lf << " s\n";
      }
    }
    if (ctrl_type == "cc") {
      double diag_K_r = cfg.controller.cc.K_r_override;
      double diag_B_r = cfg.controller.cc.B_r_override;
      if (diag_K_r == 0.0 && diag_B_r == 0.0) {
        const auto gains = vgoswec::ComputeCCGains(hydro_data, h5_file, kBody, omega0, I_hinge, C_ext);
        diag_K_r = gains.K_r;
        diag_B_r = gains.B_r;
      }
      std::cout << "  K_r (CC)     = " << diag_K_r << " N*m/rad\n"
                << "  B_r (CC)     = " << diag_B_r << " N*m*s/rad\n";
      // Degeneracy diagnostic: when B55(omega0) is far below the radiation-damping floor
      // (B_R_FLOOR = 1e-4 N*m*s/rad), CC degenerates to a pure reactive spring (B_r ~ 0).
      // The controller does ~0 net work per cycle; residual sign is numerical noise.
      // Mirror threshold in scripts/controller_power_sweep.py (B_R_FLOOR = 1e-4).
      constexpr double kCC_B_R_FLOOR = 1.0e-4;  // N*m*s/rad
      if (diag_B_r < kCC_B_R_FLOOR) {
        std::cout << "  \u26a0 CC degenerate at this omega0: B55(omega0)=" << diag_B_r
                  << " < " << kCC_B_R_FLOOR << " N*m*s/rad"
                  << " => reactive-limited (pure reactive spring)."
                  << " Expect ~0 net absorbed power and large motion.\n";
      }
    }
    std::cout << "======================================================\n";
  }

  // ── HYDRO FREQUENCY SWEEP (printed once at startup, side-effect free) ────────
  {
    constexpr int kBodySw  = 0;
    const double K_hs55_sw = hydro_data.GetHydrostaticStiffnessVal(kBodySw, 4, 4);
    // Effective restoring stiffness includes the external hinge spring.
    const double K_hs_eff_sw = K_hs55_sw + cfg.hinge_external_stiffness;
    // Hinge-referenced inertia for K_r sweep (same reasoning as HYDRO DIAGNOSTIC).
    const double r_g_sw   = std::abs(cfg.flap.cog[2] - cfg.hinge_z);
    const double I_hinge_sw = cfg.flap.inertia_yy + cfg.flap.mass * r_g_sw * r_g_sw;
    const double rho_match_omega = (cfg.controller.opt_passive.design_omega > 0.0)
                                       ? cfg.controller.opt_passive.design_omega
                                       : 2.0 * M_PI / cfg.wave.period;

    // Sweep ω = 1.0–4.0 rad/s (operating band containing VGM 45 resonance at ~1.88 rad/s).
    // Δω = 0.1 rad/s (31 rows).  B55 is clamped ≥ 0 in GetPitchRadCoeffsAtOmega
    // (radiation damping is physically non-negative; paper Eq. (1), λ₅,₅ ≥ 0).
    // K_r uses K_hs_eff (includes external spring) and I_hinge so CC gains are correctly tuned.
    // An extra row is inserted at ω = 1.84 rad/s to mark the VGM 45 natural frequency.
    constexpr double kOmegaVGM45Resonance = 1.84;  // VGM 45 ωₙ ≈ 1.84 rad/s (paper Table 2)
    auto PrintSweepRow = [&](double w_sw, const char* note = nullptr) {
      const double T_sw = 2.0 * M_PI / w_sw;
      const auto [A55_sw, B55_sw] = vgoswec::GetPitchRadCoeffsAtOmega(
          hydro_data, h5_file, kBodySw, w_sw, rho_match_omega);
      const double K_r_sw = w_sw * w_sw * (I_hinge_sw + A55_sw) - K_hs_eff_sw;
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

    std::cout << "=== HYDRO FREQUENCY SWEEP (flap pitch, hinge-referenced) ===\n"
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
  // Derive output filename from config stem so each config writes its own file.
  // e.g. config/vgoswec_45_cc.yaml  →  output/vgoswec_45_cc_results.csv
  //      config/vgoswec_0_passive.yaml → output/vgoswec_0_passive_results.csv
  const std::string config_stem =
      std::filesystem::path(args.config_path).stem().string();
  const std::string out_csv_path = "output/" + config_stem + "_results.csv";
  std::ofstream csv(out_csv_path);
  csv << "time_s,flap_pitch_rad,flap_pitch_vel_rads,pto_torque_nm,exc_torque_nm,power_w\n";
  for (const auto& r : records) {
    csv << std::fixed << std::setprecision(6) << r.t << ","
        << std::setprecision(8) << r.th << ","
        << r.om << "," << r.tau_pto << "," << r.tau_exc << "," << r.p << "\n";
  }

  std::cout << "Results saved to " << out_csv_path << "\n";
  return 0;
}
