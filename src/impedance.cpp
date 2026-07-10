// impedance.cpp
#include "impedance.h"

#include <H5Cpp.h>
#include <hdf5.h>

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

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

struct FrequencyTable {
    std::vector<double> omega;
    std::vector<double> value;
};

struct PitchBEMTables {
    FrequencyTable added_mass_55;
    FrequencyTable radiation_damping_55;
    FrequencyTable excitation_mag_51;
    double K_hs55 = 0.0;  ///< Pitch/pitch hydrostatic stiffness from LRS [4][4]; 0 if absent/empty
    double h5_rho = std::numeric_limits<double>::quiet_NaN();
    double g      = 9.81;
};

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
    return {A, std::max(0.0, B_rad)};
}

double ReadScalarDatasetOrDefault(H5::H5File& file,
                                  const std::string& dataset_path,
                                  double default_value) {
    try {
        H5::DataSet dataset     = file.openDataSet(dataset_path);
        H5::DataSpace filespace = dataset.getSpace();
        hsize_t dims[2]         = {1, 1};
        const int rank          = filespace.getSimpleExtentDims(dims);
        hsize_t n_elem          = 1;
        for (int d = 0; d < rank; ++d) {
            n_elem *= dims[d];
        }
        std::vector<double> buffer(static_cast<size_t>(n_elem), default_value);
        dataset.read(buffer.data(), H5::PredType::NATIVE_DOUBLE);
        return buffer.empty() ? default_value : buffer.front();
    } catch (const H5::Exception&) {
        H5Eclear2(H5E_DEFAULT);
        return default_value;
    }
}

// Read a BEM component dataset (Nx2: col0 = wave period T [s], col1 = normalised coefficient).
//
// If omega_axis is non-empty and its length matches the row count, it is used as the
// angular-frequency axis (rad/s), index-aligned with col1.  A sanity check verifies that
// col0[i] ≈ 2π/omega_axis[i] (i.e. col0 really is T).  If the check fails, the function
// falls back to deriving ω = 2π/col0 for that dataset with a warning.
//
// If omega_axis is empty (e.g. simulation_parameters/w was absent in the H5 file), the
// function derives ω = 2π/col0 and emits a one-time warning per call.
FrequencyTable ReadTwoColumnDataset(H5::H5File& file, const std::string& dataset_path,
                                    const std::vector<double>& omega_axis = {}) {
    H5::DataSet dataset     = file.openDataSet(dataset_path);
    H5::DataSpace filespace = dataset.getSpace();
    hsize_t dims[2]         = {0, 0};
    const int rank          = filespace.getSimpleExtentDims(dims);
    if (rank != 2 || dims[1] < 2) {
        throw std::runtime_error("[impedance] Dataset '" + dataset_path +
                                 "' must be an Nx2 numeric table");
    }

    const hsize_t rows = dims[0];
    const hsize_t cols = dims[1];
    std::vector<double> buffer(static_cast<size_t>(rows * cols), 0.0);
    dataset.read(buffer.data(), H5::PredType::NATIVE_DOUBLE);

    constexpr double kTwoPi = 2.0 * M_PI;

    std::vector<std::pair<double, double>> pairs;
    pairs.reserve(static_cast<size_t>(rows));

    const bool use_omega_axis =
        (!omega_axis.empty() && omega_axis.size() == static_cast<size_t>(rows));

    if (use_omega_axis) {
        // Verify that col0 ≈ 2π/ω (col0 should store wave period T = 2π/ω).
        bool aligned = true;
        for (hsize_t row = 0; row < rows && aligned; ++row) {
            const double w    = omega_axis[row];
            const double col0 = buffer[static_cast<size_t>(row * cols)];
            if (w > 0.0) {
                const double T_expected = kTwoPi / w;
                // Allow 0.1 % relative tolerance plus a small absolute floor
                if (std::abs(col0 - T_expected) > 1e-3 * T_expected + 1e-8) {
                    aligned = false;
                }
            }
        }

        if (!aligned) {
            std::cerr << "[impedance] WARNING: col0 of '" << dataset_path
                      << "' does not match 2π/ω from simulation_parameters/w — "
                         "falling back to ω = 2π/col0 for this table.\n";
            for (hsize_t row = 0; row < rows; ++row) {
                const double col0 = buffer[static_cast<size_t>(row * cols)];
                const double val  = buffer[static_cast<size_t>(row * cols + 1)];
                if (col0 > 0.0) {
                    pairs.emplace_back(kTwoPi / col0, val);
                }
            }
        } else {
            // Use the authoritative omega axis; col1 is index-aligned with omega_axis.
            for (hsize_t row = 0; row < rows; ++row) {
                pairs.emplace_back(omega_axis[row],
                                   buffer[static_cast<size_t>(row * cols + 1)]);
            }
        }
    } else {
        // Fallback: col0 stores wave period T; derive ω = 2π/T.
        if (omega_axis.empty()) {
            std::cerr << "[impedance] WARNING: no simulation_parameters/w axis available for '"
                      << dataset_path << "'; deriving ω = 2π/T from col0.\n";
        }
        for (hsize_t row = 0; row < rows; ++row) {
            const double col0 = buffer[static_cast<size_t>(row * cols)];
            const double val  = buffer[static_cast<size_t>(row * cols + 1)];
            if (col0 > 0.0) {
                pairs.emplace_back(kTwoPi / col0, val);
            }
        }
    }

    std::sort(pairs.begin(), pairs.end(),
              [](const auto& lhs, const auto& rhs) { return lhs.first < rhs.first; });

    FrequencyTable table;
    table.omega.reserve(pairs.size());
    table.value.reserve(pairs.size());
    for (const auto& [omega, value] : pairs) {
        table.omega.push_back(omega);
        table.value.push_back(value);
    }
    return table;
}

const PitchBEMTables& LoadPitchBEMTables(const std::string& h5_file, int flap_body_idx) {
    static std::map<std::string, PitchBEMTables> cache;

    const std::string body_name = "body" + std::to_string(flap_body_idx + 1);
    const std::string cache_key = h5_file + "#" + body_name;
    const auto found            = cache.find(cache_key);
    if (found != cache.end()) {
        return found->second;
    }

    H5::H5File file(h5_file, H5F_ACC_RDONLY);

    // ── Read the authoritative angular-frequency axis from simulation_parameters/w ──────
    // The component datasets store wave period T (= 2π/ω) in col0, NOT ω.
    // We read the ω grid from simulation_parameters/w and use it as the frequency axis so
    // that interpolation is performed in rad/s, not in seconds.
    std::vector<double> w_axis;
    try {
        H5::DataSet w_ds    = file.openDataSet("simulation_parameters/w");
        H5::DataSpace w_sp  = w_ds.getSpace();
        hsize_t w_dims[2]   = {0, 0};
        const int w_rank    = w_sp.getSimpleExtentDims(w_dims);
        const hsize_t n_rows = (w_rank >= 1) ? w_dims[0] : 0;
        const hsize_t n_cols = (w_rank >= 2) ? w_dims[1] : 1;
        const hsize_t n_elem = n_rows * n_cols;
        if (n_elem > 0) {
            std::vector<double> w_buf(static_cast<size_t>(n_elem));
            w_ds.read(w_buf.data(), H5::PredType::NATIVE_DOUBLE);
            // Flatten Nx1 (or 1-D) layout: pick column 0 from each row.
            w_axis.resize(static_cast<size_t>(n_rows));
            for (hsize_t i = 0; i < n_rows; ++i) {
                w_axis[i] = w_buf[static_cast<size_t>(i * n_cols)];
            }
        }
    } catch (const H5::Exception&) {
        H5Eclear2(H5E_DEFAULT);
        std::cerr << "[impedance] WARNING: '" << h5_file
                  << "' lacks simulation_parameters/w; "
                     "deriving ω = 2π/T from col0 of each dataset (fallback).\n";
    }

    PitchBEMTables tables;
    tables.added_mass_55 = ReadTwoColumnDataset(
        file, body_name + "/hydro_coeffs/added_mass/components/5_5", w_axis);
    tables.radiation_damping_55 = ReadTwoColumnDataset(
        file, body_name + "/hydro_coeffs/radiation_damping/components/5_5", w_axis);
    tables.excitation_mag_51 = ReadTwoColumnDataset(
        file, body_name + "/hydro_coeffs/excitation/components/mag/5_1", w_axis);
    tables.h5_rho = ReadScalarDatasetOrDefault(file, "simulation_parameters/rho",
                                               std::numeric_limits<double>::quiet_NaN());
    tables.g      = ReadScalarDatasetOrDefault(file, "simulation_parameters/g", 9.81);

    // Read hydrostatic stiffness K_hs55 from linear_restoring_stiffness [4][4].
    // For hinge-referenced impedance files, this dataset is empty or absent → K_hs55 = 0.
    constexpr hsize_t kPitchIdx = 4;  // 0-based pitch DOF index in BEMIO convention
    tables.K_hs55 = 0.0;
    try {
        H5::DataSet lrs_ds       = file.openDataSet(body_name + "/hydro_coeffs/linear_restoring_stiffness");
        H5::DataSpace lrs_space  = lrs_ds.getSpace();
        hsize_t lrs_dims[2]      = {0, 0};
        const int lrs_rank       = lrs_space.getSimpleExtentDims(lrs_dims);
        const hsize_t n_elem     = (lrs_rank >= 2) ? lrs_dims[0] * lrs_dims[1] : 0;
        if (n_elem > 0 && lrs_dims[0] > kPitchIdx && lrs_dims[1] > kPitchIdx) {
            std::vector<double> lrs_buf(static_cast<size_t>(n_elem), 0.0);
            lrs_ds.read(lrs_buf.data(), H5::PredType::NATIVE_DOUBLE);
            // Row-major layout: element [row][col] = buf[row * cols + col]
            tables.K_hs55 = lrs_buf[static_cast<size_t>(kPitchIdx * lrs_dims[1] + kPitchIdx)];
        } else if (n_elem > 0) {
            std::cerr << "[impedance] NOTE: " << body_name
                      << "/hydro_coeffs/linear_restoring_stiffness is smaller than 5x5 "
                      << "(shape " << lrs_dims[0] << "x" << lrs_dims[1]
                      << "); K_hs55 set to 0.0\n";
        }
        // If n_elem == 0 (empty dataset, shape (0,0)), K_hs55 stays 0.0 — correct for hinged files.
    } catch (const H5::Exception&) {
        H5Eclear2(H5E_DEFAULT);
        // Dataset absent: K_hs55 = 0.0.
    }

    // ── Startup diagnostic: print ω range and BEM coefficient peaks ──────────────────────
    // This verifies the frequency axis is in rad/s (not period) and peaks are physically sane.
    {
        const auto& ex_omega = tables.excitation_mag_51.omega;
        const auto& ex_value = tables.excitation_mag_51.value;
        const auto& rd_omega = tables.radiation_damping_55.omega;
        const auto& rd_value = tables.radiation_damping_55.value;

        std::cerr << "[impedance] Loaded BEM tables from '" << h5_file << "' (" << body_name << ")"
                  << ": ω ∈ [" << (ex_omega.empty() ? 0.0 : ex_omega.front())
                  << ", "       << (ex_omega.empty() ? 0.0 : ex_omega.back())
                  << "] rad/s, N=" << ex_omega.size() << "\n";

        // Excitation peak (raw normalised values; max raw ↔ max de-normed since rho·g > 0)
        if (!ex_value.empty()) {
            const auto it = std::max_element(ex_value.begin(), ex_value.end());
            const size_t idx = static_cast<size_t>(std::distance(ex_value.begin(), it));
            std::cerr << "[impedance]   Excitation peak: ω = " << ex_omega[idx]
                      << " rad/s  (ex_norm = " << *it << ")\n";
        }

        // B55 peak in de-normalised units: B55 = lambda · rho · ω
        if (!rd_value.empty() && !std::isnan(tables.h5_rho)) {
            double b55_max = 0.0;
            double b55_omega = 0.0;
            for (size_t i = 0; i < rd_value.size(); ++i) {
                const double b55 = std::max(0.0, rd_value[i]) * tables.h5_rho * rd_omega[i];
                if (b55 > b55_max) { b55_max = b55; b55_omega = rd_omega[i]; }
            }
            std::cerr << "[impedance]   B55 peak: ω = " << b55_omega
                      << " rad/s  (B55 = " << b55_max << " N·m·s/rad)\n";
        }
    }

    return cache.emplace(cache_key, std::move(tables)).first->second;
}

double InterpolateClamped(const FrequencyTable& table, double omega0, bool* clamped) {
    if (table.omega.empty()) {
        throw std::runtime_error("[impedance] Cannot interpolate empty frequency table");
    }
    if (clamped) {
        *clamped = false;
    }

    if (omega0 <= table.omega.front()) {
        if (clamped) {
            *clamped = true;
        }
        return table.value.front();
    }
    if (omega0 >= table.omega.back()) {
        if (clamped) {
            *clamped = true;
        }
        return table.value.back();
    }

    const auto upper_it = std::lower_bound(table.omega.begin(), table.omega.end(), omega0);
    if (upper_it == table.omega.begin()) {
        return table.value.front();
    }

    const auto upper_idx = static_cast<size_t>(std::distance(table.omega.begin(), upper_it));
    const auto lower_idx = upper_idx - 1;
    const double w_lo    = table.omega[lower_idx];
    const double w_hi    = table.omega[upper_idx];
    const double v_lo    = table.value[lower_idx];
    const double v_hi    = table.value[upper_idx];
    const double alpha   = (omega0 - w_lo) / (w_hi - w_lo);
    return v_lo + alpha * (v_hi - v_lo);
}

}  // anonymous namespace

PitchHydroCoefficients GetPitchHydroCoefficientsAtOmega(
    const seastack::hydro::HydroData& data,
    const std::string& h5_file,
    int flap_body_idx,
    double omega0,
    double rho_match_omega) {
    constexpr int kPitchDOF = 4;  // H5 component 5_5 == 0-based pitch DOF 4.
    if (!(rho_match_omega > 0.0) || !(omega0 > 0.0)) {
        throw std::runtime_error("[impedance] omega and rho_match_omega must be > 0");
    }

    const auto& tables = LoadPitchBEMTables(h5_file, flap_body_idx);

    // ── Legacy RIRF-derived rho (diagnostic only) ────────────────────────────
    bool added_mass_clamped_match = false;
    const double mu55_match = InterpolateClamped(
        tables.added_mass_55, rho_match_omega, &added_mass_clamped_match);
    if (!(mu55_match > 0.0)) {
        throw std::runtime_error("[impedance] H5 added-mass table returned non-positive mu55");
    }

    const auto legacy = ComputeRadCoeffsFromRIRF(data, flap_body_idx, kPitchDOF, rho_match_omega);
    const double rho_eff_match = legacy.A / mu55_match;  // legacy: for diagnostics only

    // ── Active rho: use stored H5 rho as single source of truth ─────────────
    // This pins de-normalization to the known physical density (1000 kg/m³ for
    // VGM BEM runs) and makes VGM-45 and VGM-0 comparable on the same basis.
    double rho_eff = tables.h5_rho;
    if (std::isnan(tables.h5_rho)) {
        std::cerr << "[impedance] WARNING: H5 file does not contain simulation_parameters/rho;"
                     " falling back to legacy A55-match rho = " << rho_eff_match
                  << " kg/m^3.  Provide rho in the H5 file for consistent de-normalization.\n";
        rho_eff = rho_eff_match;
    }

    bool added_mass_clamped = false;
    bool damping_clamped    = false;
    bool excitation_clamped = false;
    const double mu55 = InterpolateClamped(tables.added_mass_55, omega0, &added_mass_clamped);
    const double lambda55 = InterpolateClamped(
        tables.radiation_damping_55, omega0, &damping_clamped);
    const double ex55 = InterpolateClamped(
        tables.excitation_mag_51, omega0, &excitation_clamped);

    const bool omega_clamped =
        added_mass_clamped || damping_clamped || excitation_clamped || added_mass_clamped_match;
    if (omega_clamped) {
        std::cerr << "[impedance] WARNING: requested frequency was clamped to the H5 table range ["
                  << tables.added_mass_55.omega.front() << ", "
                  << tables.added_mass_55.omega.back() << "] rad/s\n";
    }

    PitchHydroCoefficients coeffs{};
    coeffs.A55          = mu55 * rho_eff;
    coeffs.B55          = std::max(0.0, lambda55 * rho_eff * omega0);
    coeffs.Fexc55       = ex55 * rho_eff * tables.g;
    coeffs.K_hs55       = tables.K_hs55;
    coeffs.rho_eff      = rho_eff;
    coeffs.rho_eff_match = rho_eff_match;
    coeffs.h5_rho       = tables.h5_rho;
    coeffs.g            = tables.g;
    coeffs.A55_existing = legacy.A;
    coeffs.omega_clamped = omega_clamped;

    // ── Diagnostic: warn if legacy-match rho differs significantly from H5 rho
    if (!std::isnan(tables.h5_rho) && std::abs(rho_eff_match - tables.h5_rho) > 1.0) {
        std::cerr << "[impedance] INFO: legacy A55-match rho=" << rho_eff_match
                  << " kg/m^3 differs from stored H5 rho=" << tables.h5_rho
                  << " kg/m^3; using stored H5 rho for de-normalization\n";
    }

    return coeffs;
}

std::pair<double,double> GetPitchRadCoeffsAtOmega(
    const seastack::hydro::HydroData& data,
    const std::string& h5_file,
    int flap_body_idx,
    double omega0,
    double rho_match_omega) {
    const auto coeffs =
        GetPitchHydroCoefficientsAtOmega(data, h5_file, flap_body_idx, omega0, rho_match_omega);
    return {coeffs.A55, coeffs.B55};
}

double PitchImpedanceMagnitude(const seastack::hydro::HydroData& data,
                                const std::string& h5_file,
                                int flap_body_idx,
                                double omega0,
                                double I_flap_kgm2,
                                double C_ext_cg) {
    const auto coeffs =
        GetPitchHydroCoefficientsAtOmega(data, h5_file, flap_body_idx, omega0, omega0);
    // K_hs55 is read from the impedance H5 (not the CG HydroData object) so the
    // reference frame matches the BEM tables.  For hinge-referenced files, K_hs55 = 0.
    const double K_hs_eff = coeffs.K_hs55 + C_ext_cg;

    // Z_intrinsic = B_rad + i·(ω·(I + A(ω)) − K_hs_eff/ω)
    const double Z_real = coeffs.B55;
    const double Z_imag = omega0 * (I_flap_kgm2 + coeffs.A55) - K_hs_eff / omega0;
    return std::sqrt(Z_real * Z_real + Z_imag * Z_imag);
}

CCGains ComputeCCGains(const seastack::hydro::HydroData& data,
                        const std::string& h5_file,
                        int flap_body_idx,
                        double omega0,
                        double I_flap_kgm2,
                        double C_ext_cg) {
    const auto coeffs =
        GetPitchHydroCoefficientsAtOmega(data, h5_file, flap_body_idx, omega0, omega0);
    // K_hs55 is read from the impedance H5 (not the CG HydroData object) so the
    // reference frame matches the BEM tables.  For hinge-referenced files, K_hs55 = 0.
    const double K_hs_eff = coeffs.K_hs55 + C_ext_cg;

    CCGains gains;
    // K_r is the intrinsic pitch reactance to be cancelled by CC.
    // With the external spring already in the physical dynamics, the effective
    // restoring stiffness is K_hs_eff = K_hs55 + C_ext_cg, and CC must cancel
    // the remaining reactive term: K_r = ω0²(I+A55) − K_hs_eff.
    // At resonance (ω0 = ωn), K_r = 0 and the controller is purely absorbing.
    gains.K_r = omega0 * omega0 * (I_flap_kgm2 + coeffs.A55) - K_hs_eff;
    gains.B_r = coeffs.B55;
    return gains;
}

}  // namespace vgoswec
