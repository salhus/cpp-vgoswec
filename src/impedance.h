#pragma once
// =============================================================================
// impedance.h
// Free functions for frequency-domain impedance and complex-conjugate gains.
//
// All functions operate on a pre-loaded HydroData object.  Frequency-domain
// coefficients A(ω) and B(ω) are derived from the stored RIRF via numerical
// integration (Kramers-Kronig / Fourier cosine/sine transform):
//
//   B(ω) = ∫₀^∞ K(t) · cos(ω·t) dt   (radiation damping)
//   ω·(A(ω) − A∞) = −∫₀^∞ K(t) · sin(ω·t) dt
//
// where K(t) = RIRF[body][dof_row][dof_col][t_k].
//
// All quantities are in pitch (DOF 4, index 4) of the flap body.
// =============================================================================
#ifndef VGOSWEC_IMPEDANCE_H
#define VGOSWEC_IMPEDANCE_H

#include <seastack/hydro/hydro_data.h>

namespace vgoswec {

/// Intrinsic pitch impedance magnitude at ω₀:
///   |Z(ω₀)| = sqrt( B_rad,55(ω₀)²  +  (ω₀·(I_flap + A₅₅(ω₀)) − K_hs,55/ω₀)² )
///
/// @param data           Loaded HydroData (from H5FileInfo::ReadH5Data)
/// @param flap_body_idx  Body index of flap in HydroData (0)
/// @param omega0         Design angular frequency [rad/s]
/// @param I_flap_kgm2    Dry pitch inertia of the flap about the hinge [kg·m²]
/// @return               |Z(ω₀)| [N·m·s/rad]
double PitchImpedanceMagnitude(const seastack::hydro::HydroData& data,
                                int flap_body_idx,
                                double omega0,
                                double I_flap_kgm2);

/// Complex-conjugate reactive control gains at ω₀.
///   K_r = −ω₀² · (I_flap + A₅₅(ω₀)) + K_hs,55
///   B_r =  B_rad,55(ω₀)
struct CCGains {
    double K_r;   ///< Reactive stiffness [N·m/rad]
    double B_r;   ///< Reactive damping   [N·m·s/rad]
};
CCGains ComputeCCGains(const seastack::hydro::HydroData& data,
                        int flap_body_idx,
                        double omega0,
                        double I_flap_kgm2);

}  // namespace vgoswec

#endif  // VGOSWEC_IMPEDANCE_H
