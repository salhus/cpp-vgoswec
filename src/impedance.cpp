// impedance.cpp
#include "impedance.h"

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace vgoswec {

namespace {

// Compute B_rad,55(ω₀) and A₅₅(ω₀) from the RIRF stored in HydroData.
//
// Radiation IRF K(t) relates to frequency-domain coefficients via:
//   B(ω) = ∫₀^∞ K(t) · cos(ω·t) dt           [damping]
//   ω·(A(ω) − A∞) = −∫₀^∞ K(t) · sin(ω·t) dt  [added mass deviation]
//
// We approximate the semi-infinite integral with the finite RIRF grid using
// the trapezoidal rule over the available time samples.
struct RadCoeffs { double A; double B; };

RadCoeffs ComputeRadCoeffsFromRIRF(const seastack::hydro::HydroData& data,
                                    int body_idx, int dof, double omega0) {
    const auto& t_vec    = data.GetRIRFTimeVector();
    const int   N        = static_cast<int>(t_vec.size());
    const double A_inf   = data.GetInfAddedMassMatrix(body_idx)(dof, dof);

    if (N < 2) {
        std::cerr << "[impedance] WARNING: RIRF has fewer than 2 samples; "
                     "returning A=A_inf, B=0\n";
        return {A_inf, 0.0};
    }

    // Check frequency range
    const double dt = t_vec(1) - t_vec(0);
    const double t_max = t_vec(N - 1);
    const double omega_nyquist = M_PI / dt;
    if (omega0 > omega_nyquist) {
        std::cerr << "[impedance] WARNING: ω₀=" << omega0
                  << " rad/s exceeds RIRF Nyquist ω=" << omega_nyquist
                  << " rad/s — frequency-domain result unreliable\n";
    }

    // Trapezoidal integration
    double sum_cos = 0.0;
    double sum_sin = 0.0;
    for (int s = 0; s < N; ++s) {
        const double t  = t_vec(s);
        const double K  = data.GetRIRFVal(body_idx, dof, dof, s);
        const double w  = (s == 0 || s == N - 1) ? 0.5 : 1.0;
        sum_cos += w * K * std::cos(omega0 * t);
        sum_sin += w * K * std::sin(omega0 * t);
    }
    sum_cos *= dt;
    sum_sin *= dt;

    // Warn if RIRF truncation may bias result (last value should be near zero)
    const double K_last = std::abs(data.GetRIRFVal(body_idx, dof, dof, N - 1));
    if (K_last > 0.01 * std::abs(data.GetRIRFVal(body_idx, dof, dof, 0)) + 1e-20) {
        std::cerr << "[impedance] WARNING: RIRF at t=" << t_max
                  << " s has not decayed to zero (K=" << K_last
                  << "); truncation may bias B(ω) and A(ω)\n";
    }

    const double B_rad = sum_cos;
    const double A     = A_inf - sum_sin / omega0;
    return {A, B_rad};
}

}  // anonymous namespace

double PitchImpedanceMagnitude(const seastack::hydro::HydroData& data,
                                int flap_body_idx,
                                double omega0,
                                double I_flap_kgm2) {
    constexpr int kPitchDOF = 4;  // DOF index 4 = pitch about Y (BEMIO convention)

    const auto [A55, B55] = ComputeRadCoeffsFromRIRF(data, flap_body_idx, kPitchDOF, omega0);
    const double K_hs55   = data.GetHydrostaticStiffnessVal(flap_body_idx, kPitchDOF, kPitchDOF);

    // Z_intrinsic = B_rad + i·(ω·(I + A(ω)) − K_hs/ω)
    const double Z_real = B55;
    const double Z_imag = omega0 * (I_flap_kgm2 + A55) - K_hs55 / omega0;
    return std::sqrt(Z_real * Z_real + Z_imag * Z_imag);
}

CCGains ComputeCCGains(const seastack::hydro::HydroData& data,
                        int flap_body_idx,
                        double omega0,
                        double I_flap_kgm2) {
    constexpr int kPitchDOF = 4;

    const auto [A55, B55] = ComputeRadCoeffsFromRIRF(data, flap_body_idx, kPitchDOF, omega0);
    const double K_hs55   = data.GetHydrostaticStiffnessVal(flap_body_idx, kPitchDOF, kPitchDOF);

    CCGains gains;
    gains.K_r = -omega0 * omega0 * (I_flap_kgm2 + A55) + K_hs55;
    gains.B_r = B55;
    return gains;
}

}  // namespace vgoswec
