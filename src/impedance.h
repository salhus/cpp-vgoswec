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
//
// IMPORTANT – reference frame consistency:
//   SEA-Stack attaches infinite-frequency added mass to the Chrono body at its
//   CG and computes hydrostatic restoring torques about the CG.  Therefore A₅₅,
//   B₅₅, and K_hs,55 from the H5 file are all CG-referenced pitch quantities.
//   The I_flap_kgm2 argument passed to all functions below MUST also be the
//   CG-referenced pitch inertia (not the hinge-referenced value) to keep the
//   frame consistent.  Use BodyConfig::inertia_yy (owner-provided CG Iyy = 0.21
//   kg·m²) — do NOT use the hinge-referenced Table 1 value of 0.962 kg·m².
// =============================================================================
#ifndef VGOSWEC_IMPEDANCE_H
#define VGOSWEC_IMPEDANCE_H

#include <seastack/hydro/hydro_data.h>
#include <utility>

namespace vgoswec {

/// Retrieve frequency-domain radiation added-mass and damping for pitch (DOF 4)
/// at omega0.  Uses the same RIRF Fourier-cosine/sine transform as
/// PitchImpedanceMagnitude and ComputeCCGains — suitable for diagnostics.
///
/// @return {A55(omega0) [kg·m²], B55(omega0) [N·m·s/rad]}
std::pair<double,double> GetPitchRadCoeffsAtOmega(
    const seastack::hydro::HydroData& data,
    int flap_body_idx,
    double omega0);

/// Intrinsic pitch impedance magnitude at ω₀:
///   |Z(ω₀)| = sqrt( B_rad,55(ω₀)²  +  (ω₀·(I_flap + A₅₅(ω₀)) − K_hs,55/ω₀)² )
///
/// @param data           Loaded HydroData (from H5FileInfo::ReadH5Data)
/// @param flap_body_idx  Body index of flap in HydroData (0)
/// @param omega0         Design angular frequency [rad/s]
/// @param I_flap_kgm2    CG-referenced dry pitch inertia of the flap [kg·m²]
/// @return               |Z(ω₀)| [N·m·s/rad]
double PitchImpedanceMagnitude(const seastack::hydro::HydroData& data,
                                int flap_body_idx,
                                double omega0,
                                double I_flap_kgm2);

/// Complex-conjugate reactive control gains at ω₀.
///   K_r =  ω₀² · (I_flap + A₅₅(ω₀)) − K_hs,55   (intrinsic pitch reactance to be cancelled)
///   B_r =  B_rad,55(ω₀)
///
/// I_flap_kgm2 MUST be the CG-referenced pitch inertia to be consistent with
/// SEA-Stack's CG-referenced A₅₅ and K_hs,55.
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
