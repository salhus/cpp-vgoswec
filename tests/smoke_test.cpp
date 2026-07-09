// smoke_test.cpp
// =============================================================================
// Smoke tests for vgoswec_core / vgoswec_chrono libraries.
// Does NOT require Chrono or SEA-Stack runtime data files — tests pure math.
// =============================================================================

#include <gtest/gtest.h>
#include <cmath>
#include <filesystem>
#include <fstream>

#include "config_loader.h"
#include "pid_controller.h"
#include "active_pto.h"

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

TEST(ExcitationVelocityController, DampingTerm) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(0.0, 0.0);  // F_exc = 0, so only damping term

    // B_ctrl = 0.5, ff_gain = 0.0: tau = -0.5 * vel + 0 * 0 = -B*vel
    vgoswec::ExcitationVelocityController controller(exc, /*B_ctrl=*/0.5, /*ff_gain=*/0.0, /*clip=*/100.0);

    // tau = -0.5 * 2.0 = -1.0 (same as PassiveDamper)
    EXPECT_NEAR(controller.ComputeForce(0.0, 2.0, 0.0), -1.0, 1e-9);
    EXPECT_NEAR(controller.ComputeForce(0.0, -2.0, 0.0), 1.0, 1e-9);
}

TEST(ExcitationVelocityController, FeedforwardTerm) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(2.0, 0.0);  // F_exc = 2.0 N·m

    // B_ctrl = 0.0, ff_gain = 0.5: tau = 0 + 0.5 * 2.0 = 1.0
    vgoswec::ExcitationVelocityController controller(exc, /*B_ctrl=*/0.0, /*ff_gain=*/0.5, /*clip=*/100.0);

    EXPECT_NEAR(controller.ComputeForce(0.0, 0.0, 0.0), 1.0, 1e-9);
}

TEST(ExcitationVelocityController, DampingPlusFeedforward) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(2.0, 0.0);  // F_exc = 2.0 N·m

    // B_ctrl = 0.5, ff_gain = 0.5: tau = -0.5*1.0 + 0.5*2.0 = -0.5 + 1.0 = 0.5
    vgoswec::ExcitationVelocityController controller(exc, /*B_ctrl=*/0.5, /*ff_gain=*/0.5, /*clip=*/100.0);

    EXPECT_NEAR(controller.ComputeForce(0.0, 1.0, 0.0), 0.5, 1e-9);
}

TEST(ExcitationVelocityController, IgnoresDisplacement) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(0.0, 0.0);  // F_exc = 0

    vgoswec::ExcitationVelocityController controller(exc, /*B_ctrl=*/0.5, /*ff_gain=*/0.0, /*clip=*/100.0);

    // Displacement should have no effect on the output
    EXPECT_NEAR(controller.ComputeForce(/*disp=*/99.0, /*vel=*/1.0, 0.0),
                controller.ComputeForce(/*disp=*/0.0, /*vel=*/1.0, 0.0), 1e-12);
}

TEST(ExcitationVelocityController, Clipping) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(0.0, 0.0);  // F_exc = 0

    // Large B_ctrl to saturate output
    vgoswec::ExcitationVelocityController controller(exc, /*B_ctrl=*/100.0, /*ff_gain=*/0.0, /*clip=*/5.0);

    EXPECT_EQ(controller.ComputeForce(0.0, 1.0, 0.0), -5.0);
    EXPECT_EQ(controller.ComputeForce(0.0, -1.0, 0.0), 5.0);
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
           "    ff_gain: 0.3\n"
           "    clip_torque: 4.0\n";
    cfg.close();

    const auto loaded = vgoswec::LoadConfig(cfg_path);
    EXPECT_EQ(loaded.controller.type, "exc_ff_pid");
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.B_ctrl, 0.75);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.ff_gain, 0.3);
    EXPECT_DOUBLE_EQ(loaded.controller.exc_ff_pid.clip_torque, 4.0);

    std::filesystem::remove(cfg_path);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
