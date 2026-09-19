// smoke_test.cpp
// =============================================================================
// Smoke tests for vgoswec_core / vgoswec_chrono libraries.
// Does NOT require Chrono or SEA-Stack runtime data files — tests pure math.
// Exception: ComputeCCGainsHingedH5 loads hydroData/*.h5 if present; skips
// gracefully when the files are absent.
// =============================================================================

#include <gtest/gtest.h>
#include <H5Cpp.h>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <vector>

#include "config_loader.h"
#include "pid_controller.h"
#include "active_pto.h"
#include "impedance.h"

#include <seastack/hydro_io/h5_reader.h>

// ─── PID controller tests ─────────────────────────────────────────────────────

TEST(PIDController, ProportionalOnly) {
    vgoswec::PIDParams p;
    p.kp    = 2.0;
    p.ki    = 0.0;
    p.kd    = 0.0;
    p.tau_d = 0.01;
    p.u_min = -100.0;
    p.u_max =  100.0;
    vgoswec::PIDController pid(p);
    pid.SetSetpoint(0.0);
    // error = 0 - 1.0 = -1.0  →  u = kp * error = -2.0
    const double u = pid.Compute(1.0, 0.0);
    EXPECT_NEAR(u, -2.0, 1e-9);
}

TEST(PIDController, Saturation) {
    vgoswec::PIDParams p;
    p.kp    = 100.0;
    p.ki    = 0.0;
    p.kd    = 0.0;
    p.tau_d = 0.01;
    p.u_min = -5.0;
    p.u_max =  5.0;
    vgoswec::PIDController pid(p);
    pid.SetSetpoint(0.0);
    const double u = pid.Compute(1.0, 0.0);
    EXPECT_EQ(u, -5.0);
}

TEST(PIDController, ResetClearsState) {
    vgoswec::PIDParams p;
    p.kp = 1.0; p.ki = 1.0; p.kd = 0.0; p.tau_d = 0.01;
    p.u_min = -100.0; p.u_max = 100.0;
    vgoswec::PIDController pid(p);
    pid.SetSetpoint(0.0);
    pid.Compute(1.0, 0.0);
    pid.Compute(1.0, 0.01);
    pid.Reset();
    // After reset, integral = 0; should behave like first call
    const double u1 = pid.Compute(1.0, 0.0);
    pid.Reset();
    const double u2 = pid.Compute(1.0, 0.0);
    EXPECT_NEAR(u1, u2, 1e-9);
}

// ─── PassiveDamper tests ─────────────────────────────────────────────────────

TEST(PassiveDamper, BasicDamping) {
    vgoswec::PassiveDamper pd(0.5, /*clip=*/100.0);
    // τ = -B·ω = -0.5 * 2.0 = -1.0
    EXPECT_NEAR(pd.ComputeForce(0.0, 2.0, 0.0), -1.0, 1e-12);
    EXPECT_NEAR(pd.ComputeForce(0.0, -2.0, 0.0), 1.0, 1e-12);
}

TEST(PassiveDamper, Clipping) {
    vgoswec::PassiveDamper pd(100.0, /*clip=*/5.0);
    EXPECT_EQ(pd.ComputeForce(0.0, 1.0, 0.0), -5.0);
    EXPECT_EQ(pd.ComputeForce(0.0, -1.0, 0.0), 5.0);
}

// ─── ComplexConjugateControl tests ───────────────────────────────────────────

TEST(ComplexConjugateControl, SpringDamper) {
    // τ = -K_r*θ - B_r*ω  →  τ = -1.0*2.0 - 3.0*1.0 = -5.0
    vgoswec::ComplexConjugateControl cc(1.0, 3.0, /*clip=*/100.0);
    EXPECT_NEAR(cc.ComputeForce(2.0, 1.0, 0.0), -5.0, 1e-12);
}

// ─── OptimalPassive tests ─────────────────────────────────────────────────────

TEST(OptimalPassive, BasicDamping) {
    vgoswec::OptimalPassive op(2.0, /*clip=*/100.0);
    EXPECT_NEAR(op.ComputeForce(0.0, 3.0, 0.0), -6.0, 1e-12);
}

// ─── ExcitationVelocityController tests ──────────────────────────────────────

namespace {

std::unique_ptr<vgoswec::PIDController> MakeVelocityPid(double kp,
                                                        double ki = 0.0,
                                                        double kd = 0.0,
                                                        double u_min = -100.0,
                                                        double u_max = 100.0,
                                                        double dt_expected = 0.005) {
    vgoswec::PIDParams params;
    params.kp = kp;
    params.ki = ki;
    params.kd = kd;
    params.tau_d = 0.02;
    params.u_min = u_min;
    params.u_max = u_max;
    params.dt_expected = dt_expected;
    return std::make_unique<vgoswec::PIDController>(params);
}

double ReadPitchLrsRaw(const std::filesystem::path& h5_path) {
    H5::H5File file(h5_path.string(), H5F_ACC_RDONLY);
    H5::DataSet dataset = file.openDataSet("body1/hydro_coeffs/linear_restoring_stiffness");
    H5::DataSpace filespace = dataset.getSpace();
    hsize_t dims[2] = {0, 0};
    const int rank = filespace.getSimpleExtentDims(dims);
    EXPECT_EQ(rank, 2);
    EXPECT_GE(dims[0], 5u);
    EXPECT_GE(dims[1], 5u);
    std::vector<double> buffer(static_cast<size_t>(dims[0] * dims[1]), 0.0);
    dataset.read(buffer.data(), H5::PredType::NATIVE_DOUBLE);
    return buffer[static_cast<size_t>(4 * dims[1] + 4)];
}

std::map<std::string, double> ReadFreeDecayZeroCrossFrequencies(
    const std::filesystem::path& csv_path) {
    std::ifstream csv(csv_path);
    EXPECT_TRUE(csv.is_open()) << "Could not open " << csv_path;
    std::map<std::string, double> by_config;
    std::string line;
    if (!std::getline(csv, line)) {
        ADD_FAILURE() << "Could not read header from " << csv_path;
        return by_config;
    }
    while (std::getline(csv, line)) {
        if (line.empty()) {
            continue;
        }
        std::stringstream ss(line);
        std::string cell;
        std::vector<std::string> row;
        while (std::getline(ss, cell, ',')) {
            row.push_back(cell);
        }
        if (row.size() < 7u) {
            ADD_FAILURE() << "Unexpected freedecay_validation.csv row: " << line;
            continue;
        }
        by_config[row[0]] = std::stod(row[6]);
    }
    return by_config;
}

double FindNaturalFrequencyFromImpedance(const seastack::hydro::HydroData& hydro_data,
                                         const std::string& impedance_h5,
                                         double I_hinge,
                                         double K_eff) {
    auto residual = [&](double omega) {
        const auto coeffs = vgoswec::GetPitchHydroCoefficientsAtOmega(
            hydro_data, impedance_h5, /*flap_body_idx=*/0, omega, omega);
        return omega * omega * (I_hinge + coeffs.A55) - K_eff;
    };

    constexpr double kOmegaMin = 0.5;
    constexpr double kOmegaMax = 3.0;
    constexpr int kScanSteps = 250;
    double lo = kOmegaMin;
    double f_lo = residual(lo);
    bool bracketed = false;
    double hi = lo;
    double f_hi = f_lo;
    for (int step = 1; step <= kScanSteps; ++step) {
        hi = kOmegaMin + (kOmegaMax - kOmegaMin) * static_cast<double>(step) / kScanSteps;
        f_hi = residual(hi);
        if ((f_lo <= 0.0 && f_hi >= 0.0) || (f_lo >= 0.0 && f_hi <= 0.0)) {
            bracketed = true;
            break;
        }
        lo = hi;
        f_lo = f_hi;
    }

    EXPECT_TRUE(bracketed) << "Failed to bracket natural frequency root in [" << kOmegaMin
                           << ", " << kOmegaMax << "]";
    if (!bracketed) {
        return std::numeric_limits<double>::quiet_NaN();
    }

    for (int iter = 0; iter < 80; ++iter) {
        const double mid = 0.5 * (lo + hi);
        const double f_mid = residual(mid);
        if ((f_lo <= 0.0 && f_mid >= 0.0) || (f_lo >= 0.0 && f_mid <= 0.0)) {
            hi = mid;
            f_hi = f_mid;
        } else {
            lo = mid;
            f_lo = f_mid;
        }
    }
    return 0.5 * (lo + hi);
}

}  // namespace

TEST(ExcitationVelocityController, DampingTerm) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(0.0, 0.0);  // F_exc = 0, so only damping term

    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.5, /*alpha=*/0.0, MakeVelocityPid(/*kp=*/0.0), /*clip=*/100.0);

    // tau = -0.5 * 2.0 = -1.0 (same as PassiveDamper)
    EXPECT_NEAR(controller.ComputeForce(0.0, 2.0, 0.0), -1.0, 1e-9);
    EXPECT_NEAR(controller.ComputeForce(0.0, -2.0, 0.0), 1.0, 1e-9);
}

TEST(ExcitationVelocityController, VelocityTrackingPidTerm) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(2.0, 0.0);  // F_exc = 2.0 N·m

    // B_ctrl = 0, alpha = -2 => vel_ref = -4. With kp = 0.5 and vel = 0,
    // tau_pid = 0.5 * (-4 - 0) = -2.0
    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.0, /*alpha=*/-2.0, MakeVelocityPid(/*kp=*/0.5), /*clip=*/100.0);

    EXPECT_NEAR(controller.ComputeForce(0.0, 0.0, 0.0), -2.0, 1e-9);
}

TEST(ExcitationVelocityController, DampingPlusVelocityTrackingPid) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(2.0, 0.0);  // F_exc = 2.0 N·m

    // vel_ref = -4, error = -4 - 1 = -5, tau_pid = -5, tau_damp = -0.5 => total = -5.5
    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.5, /*alpha=*/-2.0, MakeVelocityPid(/*kp=*/1.0), /*clip=*/100.0);

    EXPECT_NEAR(controller.ComputeForce(0.0, 1.0, 0.0), -5.5, 1e-9);
}

TEST(ExcitationVelocityController, IgnoresDisplacement) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(0.0, 0.0);  // F_exc = 0

    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.5, /*alpha=*/0.0, MakeVelocityPid(/*kp=*/0.0), /*clip=*/100.0);

    // Displacement should have no effect on the output
    EXPECT_NEAR(controller.ComputeForce(/*disp=*/99.0, /*vel=*/1.0, 0.0),
                controller.ComputeForce(/*disp=*/0.0, /*vel=*/1.0, 0.0), 1e-12);
}

TEST(ExcitationVelocityController, Clipping) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(0.0, 0.0);  // F_exc = 0

    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.0, /*alpha=*/1.0, MakeVelocityPid(/*kp=*/10.0), /*clip=*/5.0);

    exc->UpdateDirect(10.0, 0.0);  // vel_ref = 10, pid error = 10 - 0 = 10, tau_pid = 100 -> clamp
    EXPECT_EQ(controller.ComputeForce(0.0, 0.0, 0.0), 5.0);
}

TEST(ExcitationVelocityController, PidTermUsesInternalClampBeforeFinalClamp) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(2.0, 0.0);  // vel_ref = -4 with alpha = -2

    // tau_pid would be -40 without the PID clamp; verify inner clamp to -1 before sum.
    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.5, /*alpha=*/-2.0, MakeVelocityPid(/*kp=*/10.0, 0.0, 0.0, -1.0, 1.0), /*clip=*/100.0);

    EXPECT_NEAR(controller.ComputeForce(0.0, 1.0, 0.0), -1.5, 1e-9);
}

// ─── ExcitationVelocityController passive-safety guard tests ──────────────────

TEST(ExcitationVelocityControllerPassiveSafe, GuardTriggersWhenCommandWouldInject) {
    // Scenario: raw tau = tau_damp + tau_pid would inject energy (tau * vel > 0).
    // Setup: B_ctrl=0.5, alpha=1, F_exc=10, kp=1, vel=2.
    //   tau_damp = -0.5 * 2  = -1.0
    //   vel_ref  =  1.0 * 10 = 10
    //   error    = 10 - 2    =  8  → tau_pid = 1.0 * 8 = 8
    //   tau_raw  = -1 + 8    = +7 > 0, and vel = 2 > 0  → tau_raw * vel = 14 > 0 (INJECTING)
    // Guard fires: replaces tau_raw with tau_damp = -1.0.
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(10.0, 0.0);  // F_exc = 10

    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.5, /*alpha=*/1.0, MakeVelocityPid(/*kp=*/1.0), /*clip=*/100.0,
        /*passive_safe=*/true);

    // vel=2: tau_raw = +7 → injecting; guard replaces with tau_damp = -1.0
    EXPECT_NEAR(controller.ComputeForce(0.0, 2.0, 0.0), -1.0, 1e-9);
}

TEST(ExcitationVelocityControllerPassiveSafe, GuardNoOpWhenCommandIsDissipative) {
    // When the raw command is already dissipative (tau * vel <= 0), the guard
    // must NOT modify the output.
    // vel=1.0, alpha=-2, F_exc=2 → vel_ref=-4, error=-5, kp=1 → tau_pid=-5
    // tau_damp = -0.5, total = -5.5. tau*vel = -5.5 * 1.0 < 0 → dissipative. No guard.
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(2.0, 0.0);

    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.5, /*alpha=*/-2.0, MakeVelocityPid(/*kp=*/1.0), /*clip=*/100.0,
        /*passive_safe=*/true);

    // tau = -5.5: dissipative (same direction as restoring), guard is a no-op
    EXPECT_NEAR(controller.ComputeForce(0.0, 1.0, 0.0), -5.5, 1e-9);
}

TEST(ExcitationVelocityControllerPassiveSafe, GuardDisabledRestoresUngardedBehavior) {
    // With passive_safe=false, the original (unguarded) behavior is restored:
    // injecting commands pass through unchanged.
    // Same scenario as GuardTriggersWhenCommandWouldInject: vel=2, tau_raw=+7.
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(10.0, 0.0);  // F_exc = 10

    vgoswec::ExcitationVelocityController controller(
        exc, /*B_ctrl=*/0.5, /*alpha=*/1.0, MakeVelocityPid(/*kp=*/1.0), /*clip=*/100.0,
        /*passive_safe=*/false);

    // tau_raw = +7: injecting, but guard is off → passes through as +7
    EXPECT_NEAR(controller.ComputeForce(0.0, 2.0, 0.0), 7.0, 1e-9);
}

TEST(ConfigLoader, ExcitationVelocityControllerSchema) {
    const auto cfg_path =
        (std::filesystem::temp_directory_path() / "vgoswec_exc_ff_pid_test.yaml").string();
    std::ofstream cfg(cfg_path);
    ASSERT_TRUE(cfg.is_open());
    cfg << "hydro:\n"
           "  h5_file: hydroData/test.h5\n"
           "controller:\n"
           "  type: exc_ff_pid\n"
           "  exc_ff_pid:\n"
           "    B_ctrl: 0.75\n"
           "    alpha: -1.5\n"
           "    clip_torque: 4.0\n"
           "    passive_safe: false\n"
           "    vel_pid:\n"
           "      kp: 2.0\n"
           "      ki: 0.1\n"
           "      kd: 0.2\n"
           "      tau_d: 0.03\n"
           "      u_min: -2.5\n"
           "      u_max: 2.5\n";
    cfg.close();

    const auto loaded = vgoswec::LoadConfig(cfg_path);
    EXPECT_EQ(loaded.controller.type, "exc_ff_pid");
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.B_ctrl, 0.75);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.alpha, -1.5);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.clip_torque, 4.0);
    EXPECT_EQ(loaded.controller.exc_ff_pid.passive_safe, false);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.vel_pid.kp, 2.0);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.vel_pid.ki, 0.1);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.vel_pid.kd, 0.2);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.vel_pid.tau_d, 0.03);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.vel_pid.u_min, -2.5);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.vel_pid.u_max, 2.5);

    std::filesystem::remove(cfg_path);
}

TEST(ConfigLoader, ExcitationVelocityControllerPassiveSafeDefaultsTrue) {
    // Verify passive_safe defaults to true when not specified in YAML.
    const auto cfg_path =
        (std::filesystem::temp_directory_path() / "vgoswec_exc_ff_pid_default_test.yaml").string();
    std::ofstream cfg(cfg_path);
    ASSERT_TRUE(cfg.is_open());
    cfg << "hydro:\n"
           "  h5_file: hydroData/test.h5\n"
           "controller:\n"
           "  type: exc_ff_pid\n"
           "  exc_ff_pid:\n"
           "    B_ctrl: 0.5\n"
           "    alpha: 11.0\n"
           "    clip_torque: 10.0\n"
           "    vel_pid:\n"
           "      kp: 4.0\n"
           "      ki: 5.0\n"
           "      kd: 1.0\n";
    cfg.close();

    const auto loaded = vgoswec::LoadConfig(cfg_path);
    EXPECT_EQ(loaded.controller.exc_ff_pid.passive_safe, true);

    std::filesystem::remove(cfg_path);
}

TEST(ConfigLoader, ImpedanceH5FileDefaultsEmpty) {
    const auto cfg_path =
        (std::filesystem::temp_directory_path() / "vgoswec_impedance_h5_default.yaml").string();
    std::ofstream cfg(cfg_path);
    ASSERT_TRUE(cfg.is_open());
    cfg << "hydro:\n"
           "  h5_file: hydroData/test.h5\n";
    cfg.close();

    const auto loaded = vgoswec::LoadConfig(cfg_path);
    EXPECT_TRUE(loaded.impedance_h5_file.empty());

    std::filesystem::remove(cfg_path);
}

TEST(ConfigLoader, ImpedanceH5FileParsesWhenProvided) {
    const auto cfg_path =
        (std::filesystem::temp_directory_path() / "vgoswec_impedance_h5_set.yaml").string();
    std::ofstream cfg(cfg_path);
    ASSERT_TRUE(cfg.is_open());
    cfg << "hydro:\n"
           "  h5_file: hydroData/test.h5\n"
           "  impedance_h5_file: hydroData/hinged_test.h5\n";
    cfg.close();

    const auto loaded = vgoswec::LoadConfig(cfg_path);
    EXPECT_EQ(loaded.impedance_h5_file, "hydroData/hinged_test.h5");

    std::filesystem::remove(cfg_path);
}

TEST(ConfigLoader, GravityBuoyancyStiffnessDefaultsZero) {
    const auto cfg_path =
        (std::filesystem::temp_directory_path() / "vgoswec_gravity_buoyancy_default.yaml").string();
    std::ofstream cfg(cfg_path);
    ASSERT_TRUE(cfg.is_open());
    cfg << "hydro:\n"
           "  h5_file: hydroData/test.h5\n";
    cfg.close();

    const auto loaded = vgoswec::LoadConfig(cfg_path);
    EXPECT_DOUBLE_EQ(loaded.hinge_gravity_buoyancy_stiffness, 0.0);

    std::filesystem::remove(cfg_path);
}

TEST(ConfigLoader, GravityBuoyancyStiffnessParsesWhenProvided) {
    const auto cfg_path =
        (std::filesystem::temp_directory_path() / "vgoswec_gravity_buoyancy_set.yaml").string();
    std::ofstream cfg(cfg_path);
    ASSERT_TRUE(cfg.is_open());
    cfg << "hinge:\n"
           "  gravity_buoyancy_stiffness: 0.867\n"
           "hydro:\n"
           "  h5_file: hydroData/test.h5\n";
    cfg.close();

    const auto loaded = vgoswec::LoadConfig(cfg_path);
    EXPECT_DOUBLE_EQ(loaded.hinge_gravity_buoyancy_stiffness, 0.867);

    std::filesystem::remove(cfg_path);
}

TEST(ConfigLoader, GainDerivedControllersRequireImpedanceH5File) {
    const std::vector<std::filesystem::path> configs = {
        "config/vgoswec_0_cc.yaml",
        "config/vgoswec_10_cc.yaml",
        "config/vgoswec_20_cc.yaml",
        "config/vgoswec_45_cc.yaml",
        "config/vgoswec_90_cc.yaml",
        "config/vgoswec_0_opt_passive.yaml",
        "config/vgoswec_10_opt_passive.yaml",
        "config/vgoswec_20_opt_passive.yaml",
        "config/vgoswec_45_opt_passive.yaml",
        "config/vgoswec_90_opt_passive.yaml",
    };

    for (const auto& cfg_path : configs) {
        ASSERT_TRUE(std::filesystem::exists(cfg_path)) << "Missing config " << cfg_path;
        const auto loaded = vgoswec::LoadConfig(cfg_path.string());
        EXPECT_FALSE(loaded.impedance_h5_file.empty())
            << "Configs that derive controller gains from H5 must set impedance_h5_file: "
            << cfg_path;
    }
}

// ─── ComputeCCGains hinged-H5 integration test ────────────────────────────────
// Guards: skips when the HDF5 files are absent (e.g., minimal CI checkouts).
// When present, verifies that K_hs55 is read from the impedance H5 (= 0 for
// hinged-frame files) so that K_r ≈ 0 at the hinge resonance and B_r > 0.
//
// Physical parameters (VGM-0):
//   I_hinge  = I_cg + m·r_g² = 0.21 + 6.676·0.265² = 0.6788 kg·m²
//   C_ext    = 6.57 N·m/rad  (pure torsional hinge spring)
//   omega_n  = 0.9929 rad/s  (hinge-frame resonance with correct ω axis:
//              K_r = 0 at this frequency from hinged_vgoswec_0.h5)
TEST(ComputeCCGains, HingedH5ZeroKhs) {
    const std::string cg_h5     = "hydroData/vgoswec_0.h5";
    const std::string hinged_h5 = "hydroData/hinged_vgoswec_0.h5";

    if (!std::filesystem::exists(cg_h5) || !std::filesystem::exists(hinged_h5)) {
        GTEST_SKIP() << "Skipping: H5 data files not found at " << cg_h5
                     << " / " << hinged_h5;
    }

    // Load CG HydroData (used for legacy RIRF diagnostic inside impedance.cpp)
    auto hydro_data = seastack::hydro_io::H5FileInfo(cg_h5, 2).ReadH5Data();

    constexpr int    kFlap   = 0;
    constexpr double kOmega0 = 0.9929;  // hinge-frame resonance [rad/s] (correct ω axis)
    constexpr double kIHinge = 0.6788;  // I_cg + m·r_g² [kg·m²]
    constexpr double kCext   = 6.57;    // pure torsional hinge spring [N·m/rad]

    const auto gains = vgoswec::ComputeCCGains(hydro_data, hinged_h5, kFlap, kOmega0, kIHinge, kCext);

    // At hinge resonance with K_hs55=0 (hinged file): K_r = omega0^2*(I+A55) - K_eff ≈ 0
    EXPECT_LE(std::abs(gains.K_r), 0.5)
        << "K_r should be near zero at hinge resonance; got " << gains.K_r;
    // Radiation damping must be positive (healthy BEM result)
    EXPECT_GT(gains.B_r, 0.0)
        << "B_r must be positive (radiation damping > 0); got " << gains.B_r;
}

TEST(Impedance, DenormalizesHydrostaticPitchStiffness) {
    const std::filesystem::path cg_h5 = "hydroData/vgoswec_90.h5";
    if (!std::filesystem::exists(cg_h5)) {
        GTEST_SKIP() << "Skipping: H5 data file not found at " << cg_h5;
    }

    auto hydro_data = seastack::hydro_io::H5FileInfo(cg_h5.string(), 2).ReadH5Data();
    const double raw_k_hs55 = ReadPitchLrsRaw(cg_h5);
    const auto coeffs = vgoswec::GetPitchHydroCoefficientsAtOmega(
        hydro_data, cg_h5.string(), /*flap_body_idx=*/0, /*omega0=*/2.094, /*rho_match_omega=*/2.094);

    constexpr double kExpectedRho = 1000.0;
    constexpr double kExpectedG = 9.80665;
    EXPECT_NEAR(coeffs.h5_rho, kExpectedRho, 1e-9);
    EXPECT_NEAR(coeffs.g, kExpectedG, 1e-9);
    EXPECT_NEAR(coeffs.K_hs55, raw_k_hs55 * kExpectedRho * kExpectedG, 1e-6);
}

TEST(ComputeCCGains, IncludesExternalAndGravityBuoyancyStiffness) {
    const std::string cg_h5 = "hydroData/vgoswec_90.h5";
    if (!std::filesystem::exists(cg_h5)) {
        GTEST_SKIP() << "Skipping: H5 data file not found at " << cg_h5;
    }

    auto hydro_data = seastack::hydro_io::H5FileInfo(cg_h5, 2).ReadH5Data();
    constexpr double kOmega0 = 2.094;
    constexpr double kIHinge = 0.6788221;
    constexpr double kCext = 6.57;
    constexpr double kKgb = 0.867;

    const auto coeffs = vgoswec::GetPitchHydroCoefficientsAtOmega(
        hydro_data, cg_h5, /*flap_body_idx=*/0, kOmega0, kOmega0);
    const auto gains = vgoswec::ComputeCCGains(
        hydro_data, cg_h5, /*flap_body_idx=*/0, kOmega0, kIHinge, kCext, kKgb);

    const double expected_k_r =
        kOmega0 * kOmega0 * (kIHinge + coeffs.A55) - (coeffs.K_hs55 + kCext + kKgb);
    EXPECT_NEAR(gains.K_r, expected_k_r, 1e-9);
    EXPECT_NEAR(gains.B_r, coeffs.B55, 1e-12);
}

TEST(Impedance, HingedNaturalFrequencyMatchesFreeDecayAcrossFlaps) {
    const std::filesystem::path freedecay_csv = "docs/freedecay_validation.csv";
    ASSERT_TRUE(std::filesystem::exists(freedecay_csv)) << "Missing " << freedecay_csv;
    const auto target_w_n = ReadFreeDecayZeroCrossFrequencies(freedecay_csv);

    struct Case {
        std::string config_name;
        std::string yaml_path;
    };
    const std::vector<Case> cases = {
        {"VGM-0", "config/vgoswec_0_opt_passive.yaml"},
        {"VGM-10", "config/vgoswec_10_opt_passive.yaml"},
        {"VGM-20", "config/vgoswec_20_opt_passive.yaml"},
        {"VGM-45", "config/vgoswec_45_opt_passive.yaml"},
        {"VGM-90", "config/vgoswec_90_opt_passive.yaml"},
    };

    for (const auto& test_case : cases) {
        ASSERT_TRUE(target_w_n.count(test_case.config_name))
            << "Missing free-decay target for " << test_case.config_name;
        ASSERT_TRUE(std::filesystem::exists(test_case.yaml_path))
            << "Missing config " << test_case.yaml_path;

        const auto cfg = vgoswec::LoadConfig(test_case.yaml_path);
        ASSERT_FALSE(cfg.impedance_h5_file.empty()) << test_case.yaml_path;
        ASSERT_TRUE(std::filesystem::exists(cfg.h5_file)) << "Missing " << cfg.h5_file;
        ASSERT_TRUE(std::filesystem::exists(cfg.impedance_h5_file))
            << "Missing " << cfg.impedance_h5_file;

        auto hydro_data = seastack::hydro_io::H5FileInfo(cfg.h5_file, 2).ReadH5Data();
        const double r_g = std::abs(cfg.flap.cog[2] - cfg.hinge_z);
        const double i_hinge = cfg.flap.inertia_yy + cfg.flap.mass * r_g * r_g;
        const double k_eff =
            cfg.hinge_external_stiffness + cfg.hinge_gravity_buoyancy_stiffness;
        const double predicted = FindNaturalFrequencyFromImpedance(
            hydro_data, cfg.impedance_h5_file, i_hinge, k_eff);
        const double expected = target_w_n.at(test_case.config_name);
        EXPECT_NEAR(predicted, expected, expected * 0.03)
            << test_case.config_name << ": predicted ω_n=" << predicted
            << " rad/s, expected " << expected << " rad/s";
    }
}

// ─── BEM omega-axis regression test ──────────────────────────────────────────
// Verifies that the ω axis loaded from vgoswec_0.h5 is ascending in rad/s
// spanning roughly [0.05, 15.0] and that argmax(Fexc) is at ω ≈ 7.2 rad/s.
// This prevents regression of the T-vs-ω axis confusion where col0 (period T)
// was mistakenly used as angular frequency ω, shifting the excitation peak to
// the wrong end of the spectrum.
TEST(BEMTables, OmegaAxisAscendingAndExcitationPeak) {
    const std::string cg_h5 = "hydroData/vgoswec_0.h5";
    if (!std::filesystem::exists(cg_h5)) {
        GTEST_SKIP() << "Skipping: H5 data file not found at " << cg_h5;
    }

    auto hydro_data = seastack::hydro_io::H5FileInfo(cg_h5, 2).ReadH5Data();

    // Query at ω = 7.2 rad/s (known excitation peak in vgoswec_0.h5).
    constexpr double kOmegaPeak = 7.2;
    const auto coeffs = vgoswec::GetPitchHydroCoefficientsAtOmega(
        hydro_data, cg_h5, /*flap_body_idx=*/0, kOmegaPeak, kOmegaPeak);

    // ω = 7.2 rad/s must be within the table range [~0.05, ~15.0] — not clamped.
    EXPECT_FALSE(coeffs.omega_clamped)
        << "ω = 7.2 rad/s should be within the BEM table range; omega_clamped = true";

    // Fexc55 at the excitation peak should be physically large (≈ 174 N·m/m).
    // With the T-vs-ω bug the value here would be ~0.001–2 N·m/m (wrong).
    EXPECT_GT(coeffs.Fexc55, 50.0)
        << "Fexc55 at ω=7.2 rad/s should be near-peak (> 50 N·m/m); got " << coeffs.Fexc55;

    // B55 at ω = 7.2 rad/s should be well above zero (≈ 2.2 N·m·s/rad).
    EXPECT_GT(coeffs.B55, 0.5)
        << "B55 at ω=7.2 rad/s should be significant (> 0.5 N·m·s/rad); got " << coeffs.B55;

    // Query at ω = 0.87 rad/s (≈ T = 7.2 s), which is what the buggy axis used to
    // return for the excitation peak.  The correct value here is much smaller.
    constexpr double kOmegaBugValue = 2.0 * M_PI / 7.2;  // ≈ 0.8727 rad/s
    const auto coeffs_low = vgoswec::GetPitchHydroCoefficientsAtOmega(
        hydro_data, cg_h5, 0, kOmegaBugValue, kOmegaBugValue);
    // Fexc at the old "peak" (ω ≈ 0.87 rad/s) should be much smaller than at ω=7.2.
    EXPECT_LT(coeffs_low.Fexc55, coeffs.Fexc55 * 0.5)
        << "Fexc55 at ω≈0.87 rad/s should be less than half of the true peak at ω=7.2";
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
