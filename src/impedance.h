#pragma once
// =============================================================================
// impedance.h
// Free functions for frequency-domain impedance and complex-conjugate gains.
//
// These helpers use the frequency-domain BEM tables stored in the hydro H5 for
// pitch added mass, radiation damping, and excitation magnitude.  Coefficients
// are de-normalized using the density stored in the H5 file
// (simulation_parameters/rho, = 1000 for VGM-45 and VGM-0 BEM runs):
//
//   A55(ω)    = mu55_stored(ω)     * rho_h5
//   B55(ω)    = lambda55_stored(ω) * rho_h5 * ω
//   |Fexc55|  = ex55_stored(ω)     * rho_h5 * g
//
// The legacy RIRF-derived A55(ω_ref) is still computed for diagnostics, but
// is NO LONGER used as the basis for rho — the stored H5 rho is the single
// source of truth so that VGM-45 and VGM-0 are on a consistent density basis.
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
//
// EXTERNAL SPRING (C_ext):
//   The VGOSWEC experimental apparatus includes an external torsional spring of
//   C_ext = 6.57 N·m/rad at the hinge.  Because it is a pure torsional spring
//   (couple), its CG-referred value equals the hinge value exactly — no
//   parallel-axis transformation is required.  The effective CG-referenced
//   hydrostatic + spring stiffness is therefore:
//     K_hs,eff = K_hs55_cg + C_ext
//   which for VGM-45/VGM-0 gives K_hs,eff ≈ +5.37 N·m/rad (stable).
//   PitchImpedanceMagnitude and ComputeCCGains both accept a C_ext_cg argument
//   so they use K_hs,eff correctly.  The physical spring is applied separately
//   in the Chrono simulation via a dedicated RSDA link.
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
    double rho_eff;       ///< rho used for de-normalization (= stored H5 rho)
    double rho_eff_match; ///< Legacy RIRF-derived rho (diagnostic only, not used)
    double h5_rho;        ///< Raw rho stored in the H5
    double g;             ///< Gravity used for excitation de-normalization
    double A55_existing;  ///< Legacy A55(ω_ref) from the RIRF path (diagnostic)
    bool omega_clamped;   ///< True if ω was outside the tabulated H5 range
};

/// Retrieve dimensional frequency-domain pitch coefficients at omega0 using the
/// H5 BEM tables.  De-normalization uses the rho stored in the H5 file
/// (simulation_parameters/rho) as the single source of truth so that
/// VGM-45 and VGM-0 results are on a consistent density basis.
///
/// @param rho_match_omega  Reference ω used ONLY for the diagnostic legacy-A55
///                         comparison printout.  Does not affect de-normalization.
PitchHydroCoefficients GetPitchHydroCoefficientsAtOmega(
    const seastack::hydro::HydroData& data,
    const std::string& h5_file,
    int flap_body_idx,
    double omega0,
    double rho_match_omega);

/// Retrieve dimensional frequency-domain pitch added-mass and damping.
std::pair<double,double> GetPitchRadCoeffsAtOmega(
    const seastack::hydro::HydroData& data,
    const std::string& h5_file,
    int flap_body_idx,
    double omega0,
    double rho_match_omega);

/// Intrinsic pitch impedance magnitude at ω₀, accounting for the external
/// hinge spring C_ext_cg [N·m/rad] (CG-referred value, equals hinge value for
/// a pure torsional spring):
///
///   K_hs_eff = K_hs55 + C_ext_cg
///   |Z(ω₀)| = sqrt( B_rad,55(ω₀)²  +  (ω₀·(I_flap + A₅₅(ω₀)) − K_hs_eff/ω₀)² )
///
/// @param data           Loaded HydroData (from H5FileInfo::ReadH5Data)
/// @param flap_body_idx  Body index of flap in HydroData (0)
/// @param omega0         Design angular frequency [rad/s]
/// @param I_flap_kgm2    CG-referenced dry pitch inertia of the flap [kg·m²]
/// @param C_ext_cg       CG-referred external spring stiffness [N·m/rad] (default 0)
/// @return               |Z(ω₀)| [N·m·s/rad]
double PitchImpedanceMagnitude(const seastack::hydro::HydroData& data,
                                const std::string& h5_file,
                                int flap_body_idx,
                                double omega0,
                                double I_flap_kgm2,
                                double C_ext_cg = 0.0);

/// Complex-conjugate reactive control gains at ω₀, accounting for the external
/// hinge spring C_ext_cg [N·m/rad]:
///
///   K_hs_eff = K_hs55 + C_ext_cg
///   K_r =  ω₀² · (I_flap + A₅₅(ω₀)) − K_hs_eff   (intrinsic reactance to cancel)
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
                        double I_flap_kgm2,
                        double C_ext_cg = 0.0);

}  // namespace vgoswec

#endif  // VGOSWEC_IMPEDANCE_H
