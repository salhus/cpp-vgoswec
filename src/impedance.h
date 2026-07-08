#pragma once
// =============================================================================
// impedance.h
// Free functions for frequency-domain impedance and complex-conjugate gains.
//
// These helpers use the frequency-domain BEM tables stored in the hydro H5 for
// pitch added mass, radiation damping, and excitation magnitude.  Coefficients
// are de-normalized per the WEC-Sim/BEMIO convention using an effective
// density rho_eff derived from the legacy A55(ω_ref) value so the validated
// free-decay behaviour remains unchanged:
//
//   A55(ω)    = mu55_stored(ω)     * rho_eff
//   B55(ω)    = lambda55_stored(ω) * rho_eff * ω
//   |Fexc55|  = ex55_stored(ω)     * rho_eff * g
//
// The legacy A55(ω_ref) value is still computed from the stored RIRF only to
// derive rho_eff = A55_legacy(ω_ref) / mu55_stored(ω_ref).
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
#include <string>
#include <utility>

namespace vgoswec {

struct PitchHydroCoefficients {
    double A55;           ///< Pitch added mass [kg·m²]
    double B55;           ///< Pitch radiation damping [N·m·s/rad], clamped >= 0
    double Fexc55;        ///< Pitch excitation magnitude [N·m per unit wave amplitude]
    double rho_eff;       ///< Effective density derived from legacy A55(ω_ref)
    double h5_rho;        ///< Raw rho stored in the H5, if available
    double g;             ///< Gravity used for excitation de-normalization
    double A55_existing;  ///< Legacy A55(ω_ref) from the RIRF path
    bool omega_clamped;   ///< True if ω was outside the tabulated H5 range
};

/// Retrieve dimensional frequency-domain pitch coefficients at omega0 using the
/// H5 BEM tables and a rho_eff derived from rho_match_omega.
///
/// @param rho_match_omega  Reference ω used to derive rho_eff from the legacy
///                         A55(ω) match.  Use the controller design ω₀ so the
///                         validated free-decay/gain tuning remains unchanged.
PitchHydroCoefficients GetPitchHydroCoefficientsAtOmega(
    const seastack::hydro::HydroData& data,
    const std::string& h5_file,
    int flap_body_idx,
    double omega0,
    double rho_match_omega);

/// Retrieve dimensional frequency-domain pitch added-mass and damping using
/// the H5 BEM tables and rho_eff derived at rho_match_omega.
std::pair<double,double> GetPitchRadCoeffsAtOmega(
    const seastack::hydro::HydroData& data,
    const std::string& h5_file,
    int flap_body_idx,
    double omega0,
    double rho_match_omega);

/// Intrinsic pitch impedance magnitude at ω₀:
///   |Z(ω₀)| = sqrt( B_rad,55(ω₀)²  +  (ω₀·(I_flap + A₅₅(ω₀)) − K_hs,55/ω₀)² )
///
/// @param data           Loaded HydroData (from H5FileInfo::ReadH5Data)
/// @param flap_body_idx  Body index of flap in HydroData (0)
/// @param omega0         Design angular frequency [rad/s]
/// @param I_flap_kgm2    CG-referenced dry pitch inertia of the flap [kg·m²]
/// @return               |Z(ω₀)| [N·m·s/rad]
double PitchImpedanceMagnitude(const seastack::hydro::HydroData& data,
                                const std::string& h5_file,
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
                        const std::string& h5_file,
                        int flap_body_idx,
                        double omega0,
                        double I_flap_kgm2);

}  // namespace vgoswec

#endif  // VGOSWEC_IMPEDANCE_H
