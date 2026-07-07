// smoke_test.cpp
// =============================================================================
// Smoke tests for vgoswec_core / vgoswec_chrono libraries.
// Does NOT require Chrono or SEA-Stack runtime data files — tests pure math.
// =============================================================================

#include <gtest/gtest.h>
#include <cmath>

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

// ─── ExcitationFeedforwardPID tests ──────────────────────────────────────────

TEST(ExcitationFeedforwardPID, FeedforwardOnly) {
    auto exc = std::make_shared<vgoswec::ExcitationForceProvider>(0, 4);
    exc->UpdateDirect(2.0, 0.0);  // F_exc = 2.0 N·m

    vgoswec::PIDParams p;
    p.kp = 0.0; p.ki = 0.0; p.kd = 0.0;
    p.tau_d = 0.01; p.u_min = -100.0; p.u_max = 100.0;
    auto pid = std::make_unique<vgoswec::PIDController>(p);
    vgoswec::ExcitationFeedforwardPID ff_pid(exc, /*alpha=*/0.5, std::move(pid));

    // τ = alpha * F_exc + PID(0) = 0.5 * 2.0 + 0 = 1.0
    EXPECT_NEAR(ff_pid.ComputeForce(0.0, 0.0, 0.0), 1.0, 1e-9);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
