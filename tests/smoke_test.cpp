// smoke_test.cpp
// =============================================================================
// Smoke tests for vgoswec_core / vgoswec_chrono libraries.
// Does NOT require Chrono or SEA-Stack runtime data files — tests pure math.
// Exception: ComputeCCGainsHingedH5 loads hydroData/*.h5 if present; skips
// gracefully when the files are absent.
// =============================================================================

#include <gtest/gtest.h>
#include <cmath>
#include <filesystem>
#include <fstream>

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

// ─── ComputeCCGains hinged-H5 integration test ────────────────────────────────
// Guards: skips when the HDF5 files are absent (e.g., minimal CI checkouts).
// When present, verifies that K_hs55 is read from the impedance H5 (= 0 for
// hinged-frame files) so that K_r ≈ 0 at the hinge resonance and B_r > 0.
//
// Physical parameters (VGM-0):
//   I_hinge  = I_cg + m*r_g^2 = 0.21 + 6.676*0.265^2 = 0.6788 kg*m^2
//   C_ext    = 6.57 N*m/rad  (pure torsional hinge spring)
//   omega0   = 0.8763 rad/s  (hinge-frame resonance: K_r = 0 at this frequency)
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
    constexpr double kOmega0 = 0.8763;   // hinge-frame resonance [rad/s]
    constexpr double kIHinge = 0.6788;   // I_cg + m*r_g^2 [kg*m^2]
    constexpr double kCext   = 6.57;     // pure torsional hinge spring [N*m/rad]

    const auto gains = vgoswec::ComputeCCGains(hydro_data, hinged_h5, kFlap, kOmega0, kIHinge, kCext);

    // At hinge resonance with K_hs55=0 (hinged file): K_r = omega0^2*(I+A55) - K_eff ≈ 0
    EXPECT_LE(std::abs(gains.K_r), 0.5)
        << "K_r should be near zero at hinge resonance; got " << gains.K_r;
    // Radiation damping must be positive (healthy BEM result)
    EXPECT_GT(gains.B_r, 0.0)
        << "B_r must be positive (radiation damping > 0); got " << gains.B_r;
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
