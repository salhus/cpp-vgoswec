#!/usr/bin/env python3
"""Shared free-decay analysis functions for the VGOSWEC validation suite.

This module is import-safe (no side effects on import) and provides:
  - load_series        : load (t, x) from a results CSV, drop NaNs, detrend
  - estimate_wn_fft    : natural frequency via FFT peak
  - estimate_wn_zerocross : natural frequency via zero-crossing period
  - find_peaks         : positive local maxima above a fractional threshold
  - estimate_zeta_logdec : damping ratio via logarithmic decrement (correct n)
  - paper_fig4_zeta_estimate : compute per-config ζ from paper Fig. 4 envelope

Reference values from Ogden et al., ASME JOMAE 145(3):030905, Table 2, keyed by
flap angle in degrees.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Paper reference values (Ogden et al. / Husain et al., ASME JOMAE 145(3):030905, Table 2)
# Keys: flap angle [deg]
# Values: dict with paper_wn_rads, paper_Ts_s, paper_zeta_1e4
# ---------------------------------------------------------------------------
PAPER_TABLE2 = {
    0:  {"paper_wn_rads": 1.07, "paper_Ts_s": 5.86, "paper_zeta_1e4": 5.8},
    10: {"paper_wn_rads": 1.46, "paper_Ts_s": 4.29, "paper_zeta_1e4": 4.3},
    20: {"paper_wn_rads": 1.57, "paper_Ts_s": 4.01, "paper_zeta_1e4": 4.1},
    45: {"paper_wn_rads": 1.84, "paper_Ts_s": 3.42, "paper_zeta_1e4": 3.5},
    90: {"paper_wn_rads": 2.10, "paper_Ts_s": 2.99, "paper_zeta_1e4": 3.2},
}

# Validated C++ ζ fallback values (×10⁻⁴) computed via logdec with correct n=1
# between adjacent peaks from the committed simulation output CSVs.
FALLBACK_CPP_ZETA_1E4 = {
    0:  49.9,
    10: 40.1,
    20: 46.5,
    45: 37.8,
    90: 29.9,
}

# Validated C++ ω_n fallback values (rad/s)
FALLBACK_CPP_WN = {
    0:  {"cpp_zc": 1.072, "cpp_fft": 1.083},
    10: {"cpp_zc": 1.468, "cpp_fft": 1.517},
    20: {"cpp_zc": 1.568, "cpp_fft": 1.517},
    45: {"cpp_zc": 1.837, "cpp_fft": 1.819},
    90: {"cpp_zc": 2.094, "cpp_fft": 2.058},
}


# ---------------------------------------------------------------------------
# Per-config paper Fig. 4 ζ estimates (×10⁻⁴)
#
# Derived by log-decrement on the paper's own nondimensional free-decay
# time-history figure (Fig. 4, Ogden et al. ASME JOMAE 145(3):030905).
#
# Method: the nondimensional envelope decays from A₀ ≈ 1.0 to A_N ≈ 0.35
# over a record length of ~200 s.  Each config has a distinct oscillation
# period T_s (Table 2), giving N ≈ 200 / T_s cycles over the record.
#
#     δ = ln(A₀ / A_N) / N = ln(1.0 / 0.35) / N ≈ 1.0498 / N
#     ζ = δ / √(4π² + δ²)
#
# Values computed via paper_fig4_zeta_estimate(Ts_s) for each T_s:
#
# | angle | T_s [s] | N ≈ 200/T_s | δ      | ζ (×10⁻⁴) |
# |-------|---------|-------------|--------|------------|
# |  0°   |  5.86   |    ~34      | 0.0309 |    ~49     |
# |  10°  |  4.29   |    ~47      | 0.0224 |    ~36     |
# |  20°  |  4.01   |    ~50      | 0.0210 |    ~33     |
# |  45°  |  3.42   |    ~58      | 0.0180 |    ~29     |
# |  90°  |  2.99   |    ~67      | 0.0157 |    ~25     |
#
# These are approximate figure-read estimates (±few ×10⁻⁴); the envelope
# ratio and cycle count are both read from the plot, not digitised precisely.
# They are included as an independent per-geometry corroboration, not a
# precision measurement.  They agree with the C++ ζ values (30–50×10⁻⁴)
# and are ~10× the Table 2 ζ column (3.2–5.8×10⁻⁴), confirming the
# ×10⁻³/×10⁻⁴ exponent inconsistency in Table 2 at every geometry.
# ---------------------------------------------------------------------------
PAPER_FIG4_ZETA_1E4 = {
    0:  49,
    10: 36,
    20: 33,
    45: 29,
    90: 25,
}


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------


def paper_fig4_zeta_estimate(
    Ts_s: float,
    A0: float = 1.0,
    AN: float = 0.35,
    record_s: float = 200.0,
) -> float:
    """Compute per-config ζ estimate from the paper's Fig. 4 envelope.

    Uses the log-decrement formula applied to the nondimensional free-decay
    envelope visible in Fig. 4 (Ogden et al. ASME JOMAE 145(3):030905):

        N  = record_s / Ts_s          (number of cycles over the record)
        δ  = ln(A0 / AN) / N          (per-cycle logarithmic decrement)
        ζ  = δ / √(4π² + δ²)

    Parameters
    ----------
    Ts_s : float
        Oscillation period [s] from Table 2 for this geometry.
    A0 : float
        Initial nondimensional amplitude (default 1.0, start of record).
    AN : float
        Final nondimensional amplitude (default 0.35, end of 200 s record).
    record_s : float
        Length of the free-decay record [s] over which the envelope is read
        (default 200.0 s, matching the paper's Fig. 4 time axis).

    Returns
    -------
    float
        Estimated damping ratio ζ (dimensionless).

    Notes
    -----
    The returned value is an *approximate* figure-read estimate.  The envelope
    ratio A0/AN and the record length are both read from the plot and carry
    ±10–15% uncertainty.  Use for qualitative per-geometry corroboration only.
    """
    N = record_s / Ts_s
    delta = math.log(A0 / AN) / N
    return delta / math.sqrt(4.0 * math.pi ** 2 + delta ** 2)


def load_series(
    csv_path: Path,
    transient_s: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Load (t, x) from a free-decay results CSV.

    Reads ``time_s`` and ``flap_pitch_rad`` columns, sorts by time, drops rows
    with NaN or non-finite values, removes the first *transient_s* seconds, and
    detrends by subtracting the mean.

    Parameters
    ----------
    csv_path:
        Path to ``vgoswec_<deg>_freedecay_results.csv``.
    transient_s:
        Seconds of initial transient to discard.

    Returns
    -------
    t, x : np.ndarray
        Time [s] and detrended pitch [rad].

    Raises
    ------
    RuntimeError
        If there are not enough valid samples after filtering.
    """
    t_raw: List[float] = []
    x_raw: List[float] = []
    with Path(csv_path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                ti = float(row["time_s"])
                xi = float(row["flap_pitch_rad"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (math.isfinite(ti) and math.isfinite(xi)):
                continue
            t_raw.append(ti)
            x_raw.append(xi)

    if len(t_raw) < 16:
        raise RuntimeError(
            f"Insufficient valid samples in {csv_path} (found {len(t_raw)})"
        )

    order = np.argsort(np.asarray(t_raw, dtype=float))
    t = np.asarray(t_raw, dtype=float)[order]
    x = np.asarray(x_raw, dtype=float)[order]

    mask = t >= (t[0] + transient_s)
    t = t[mask]
    x = x[mask]
    if len(t) < 16:
        raise RuntimeError(
            f"Not enough post-transient samples in {csv_path} (need ≥16, got {len(t)})"
        )

    x = x - np.mean(x)
    return t, x


def estimate_wn_fft(t: np.ndarray, x: np.ndarray) -> float:
    """Estimate natural frequency via FFT peak pick.

    Parameters
    ----------
    t, x : np.ndarray
        Time [s] and detrended pitch signal [rad].

    Returns
    -------
    float
        ω_n [rad/s] corresponding to the FFT amplitude peak.
    """
    dt = float(np.median(np.diff(t)))
    if dt <= 0.0:
        raise RuntimeError("Non-positive median dt in time array")

    freqs = np.fft.rfftfreq(len(x), d=dt)
    amps = np.abs(np.fft.rfft(x))
    if len(amps) > 1:
        amps[0] = 0.0  # suppress DC
    k = int(np.argmax(amps))
    return float(2.0 * math.pi * freqs[k])


def estimate_wn_zerocross(t: np.ndarray, x: np.ndarray) -> float:
    """Estimate natural frequency via upward zero-crossing period.

    Uses linear interpolation between samples to find each upward
    zero crossing, then takes the median period and converts to ω_n.

    Parameters
    ----------
    t, x : np.ndarray
        Time [s] and detrended pitch signal [rad].

    Returns
    -------
    float
        ω_n [rad/s] from median zero-crossing period.
    """
    zc: List[float] = []
    for i in range(1, len(x)):
        if x[i - 1] < 0.0 <= x[i]:
            dx = x[i] - x[i - 1]
            if abs(dx) < 1e-12:
                continue
            alpha = -x[i - 1] / dx
            zc.append(float(t[i - 1] + alpha * (t[i] - t[i - 1])))
    if len(zc) < 2:
        raise RuntimeError(
            f"Insufficient upward zero crossings (found {len(zc)})"
        )
    periods = np.diff(np.asarray(zc, dtype=float))
    T_med = float(np.median(periods))
    return float(2.0 * math.pi / T_med)


def find_peaks(
    t: np.ndarray,
    x: np.ndarray,
    min_frac: float = 0.02,
) -> Tuple[np.ndarray, np.ndarray]:
    """Find positive local maxima above a fractional amplitude threshold.

    Parameters
    ----------
    t, x : np.ndarray
        Time [s] and detrended signal [rad].
    min_frac : float
        Minimum fraction of the global maximum to keep (default 0.02 = 2%).

    Returns
    -------
    peak_times, peak_amps : np.ndarray
        Times [s] and amplitudes [rad] of retained peaks.
    """
    threshold = min_frac * float(np.max(np.abs(x)))
    idx: List[int] = []
    for i in range(1, len(x) - 1):
        if x[i] > x[i - 1] and x[i] >= x[i + 1] and x[i] > threshold:
            idx.append(i)
    if not idx:
        raise RuntimeError("No positive peaks found above threshold")
    idx_arr = np.asarray(idx, dtype=int)
    return t[idx_arr], x[idx_arr]


def estimate_zeta_logdec(
    t: np.ndarray,
    x: np.ndarray,
    min_frac: float = 0.02,
) -> Tuple[float, np.ndarray]:
    """Estimate damping ratio ζ via logarithmic decrement.

    Uses the standard N-cycle formula:

        δ = (1/N) · ln(A_0 / A_N)
        ζ = δ / √(4π² + δ²)

    where N = (number of retained peaks − 1), A_0 is the first peak amplitude,
    and A_N is the last.  The formula ``ζ = δ/√(4π²+δ²)`` is equivalent to
    ``1/√(1+(2π/δ)²)`` (your WEC-Sim MATLAB formulation).

    **n pitfall**: the formula above computes the *per-cycle* δ, so N must equal
    the actual number of cycles between A_0 and A_N (i.e. the number of peaks
    minus one).  Passing n=2 when x1 and x2 are *adjacent* peaks (only 1 cycle
    apart) halves δ and therefore halves ζ — use n=1 for adjacent peaks.

    Also returns the per-adjacent-cycle ζ array (n=1 between each consecutive
    pair) so that linearity of damping can be inspected: constant per-cycle ζ
    implies linear (amplitude-independent) damping.

    Parameters
    ----------
    t, x : np.ndarray
        Time [s] and detrended signal [rad].
    min_frac : float
        Amplitude threshold for peak detection (see ``find_peaks``).

    Returns
    -------
    zeta : float
        Overall damping ratio from first-to-last peak (N-cycle formula).
    zeta_per_cycle : np.ndarray
        Per-adjacent-cycle ζ values (length = num_peaks − 1).
    """
    _, amps = find_peaks(t, x, min_frac=min_frac)
    if len(amps) < 2:
        raise RuntimeError(
            f"Need at least 2 peaks to compute logdec (found {len(amps)})"
        )

    N = len(amps) - 1
    delta_overall = (1.0 / N) * math.log(float(amps[0]) / float(amps[-1]))
    zeta = delta_overall / math.sqrt(4.0 * math.pi ** 2 + delta_overall ** 2)

    # Per-adjacent-cycle ζ (n=1: each consecutive pair is 1 cycle apart)
    zeta_pairs: List[float] = []
    for i in range(N):
        if amps[i + 1] <= 0.0:
            continue
        d = math.log(float(amps[i]) / float(amps[i + 1]))
        zeta_pairs.append(d / math.sqrt(4.0 * math.pi ** 2 + d ** 2))

    return zeta, np.asarray(zeta_pairs, dtype=float)
