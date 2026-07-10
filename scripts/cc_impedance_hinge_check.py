#!/usr/bin/env python3
"""Validate hinge-referenced CC impedance quantities from hinged H5 files."""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

import h5py
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "analysis" / "cc_hinge"
OUTPUT_CSV = OUTPUT_DIR / "cc_impedance_hinge_summary.csv"

ANGLES = [0, 10, 20, 45, 90]
DEFAULT_DESIGN_OMEGA = 1.07
I_HINGE = 0.658
C_EXT = 6.57
K_HS = 0.0
K_EFF = K_HS + C_EXT
WAVE_HEIGHT = 0.05
WAVE_AMPLITUDE = 0.5 * WAVE_HEIGHT
NEAR_RESONANCE_TOL = 0.25
K_R_NEAR_ZERO_TOL = 3.0


def _read_two_col_dataset(h5: h5py.File, path: str) -> tuple[np.ndarray, np.ndarray]:
    data = np.asarray(h5[path], dtype=float)
    if data.ndim != 2 or 2 not in data.shape:
        raise ValueError(f"Dataset {path} is not Nx2/2xN (shape={data.shape})")
    if data.shape[1] == 2:
        w = data[:, 0]
        vals = data[:, 1]
    else:
        w = data[0, :]
        vals = data[1, :]
    order = np.argsort(w)
    return np.asarray(w[order], dtype=float), np.asarray(vals[order], dtype=float)


def _interp(x: np.ndarray, y: np.ndarray, xq: float) -> float:
    return float(np.interp(xq, x, y))


def _solve_omega_n(w: np.ndarray, a55: np.ndarray) -> float:
    # Fixed-point solve: omega = sqrt(K_eff / (I_hinge + A55(omega)))
    omega = 1.0
    for _ in range(100):
        a = _interp(w, a55, omega)
        denom = I_HINGE + a
        if denom <= 0.0:
            raise ValueError("Non-positive inertia denominator while solving omega_n")
        next_omega = math.sqrt(K_EFF / denom)
        if abs(next_omega - omega) < 1e-10:
            break
        omega = next_omega
    return omega


def _read_design_omega(angle: int) -> float:
    cfg = REPO_ROOT / "config" / f"vgoswec_{angle}_cc.yaml"
    if not cfg.exists():
        return DEFAULT_DESIGN_OMEGA
    text = cfg.read_text(encoding="utf-8")
    match = re.search(r"^\s*design_omega\s*:\s*([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?)", text, re.MULTILINE)
    if not match:
        return DEFAULT_DESIGN_OMEGA
    return float(match.group(1))


def _load_row(angle: int) -> dict[str, float] | None:
    h5_path = REPO_ROOT / "hydroData" / f"hinged_vgoswec_{angle}.h5"
    if not h5_path.exists():
        print(f"[skip] hinged H5 missing for {angle} deg: {h5_path}")
        return None

    with h5py.File(h5_path, "r") as h5:
        w_a, mu55 = _read_two_col_dataset(h5, "body1/hydro_coeffs/added_mass/components/5_5")
        w_b, lam55 = _read_two_col_dataset(h5, "body1/hydro_coeffs/radiation_damping/components/5_5")
        w_f, mag = _read_two_col_dataset(h5, "body1/hydro_coeffs/excitation/components/mag/5_1")

        rho = float(np.asarray(h5["simulation_parameters/rho"]).squeeze())
        g = float(np.asarray(h5["simulation_parameters/g"]).squeeze())

    a55 = mu55 * rho
    b55 = lam55 * rho * w_b
    fexc55 = mag * rho * g

    design_omega = _read_design_omega(angle)
    omega_n = _solve_omega_n(w_a, a55)

    a55_w0 = _interp(w_a, a55, design_omega)
    b55_w0 = _interp(w_b, b55, design_omega)
    fexc55_w0 = _interp(w_f, fexc55, design_omega)

    if b55_w0 <= 0.0:
        raise ValueError(f"B55({design_omega:.3f}) <= 0 for angle {angle}: {b55_w0}")

    k_r = design_omega * design_omega * (I_HINGE + a55_w0) - K_EFF
    b_r = b55_w0

    p_opt_unit_amp = (fexc55_w0 * fexc55_w0) / (8.0 * b55_w0)
    p_opt_wave = p_opt_unit_amp * (WAVE_AMPLITUDE * WAVE_AMPLITUDE)

    return {
        "flap_angle": angle,
        "design_omega": design_omega,
        "omega_n": omega_n,
        "I_hinge": I_HINGE,
        "A55_w0": a55_w0,
        "B55_w0": b55_w0,
        "Fexc55_w0": fexc55_w0,
        "K_r": k_r,
        "B_r": b_r,
        "P_opt_W": p_opt_wave,
        "P_opt_unit_amp_W": p_opt_unit_amp,
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for angle in ANGLES:
        row = _load_row(angle)
        if row is not None:
            rows.append(row)

    if not rows:
        print("No hinged H5 files found; nothing to validate.")
        return 0

    print("\nHinge-frame CC impedance summary")
    print(" angle   w0(rad/s)   wn(rad/s)   K_r(Nm/rad)   B_r(Nms/rad)   Popt@H=0.05m(W)")
    for r in rows:
        print(
            f" {int(r['flap_angle']):>5d}"
            f"   {r['design_omega']:>9.3f}"
            f"   {r['omega_n']:>9.3f}"
            f"   {r['K_r']:>11.4f}"
            f"   {r['B_r']:>12.6f}"
            f"   {r['P_opt_W']:>14.6f}"
        )

    print("\nChecks:")
    for r in rows:
        near_resonance = abs(r["design_omega"] - r["omega_n"]) <= NEAR_RESONANCE_TOL
        near_zero = abs(r["K_r"]) <= K_R_NEAR_ZERO_TOL
        print(
            f"  VGM-{int(r['flap_angle'])}: |K_r|={abs(r['K_r']):.4f}"
            f" ({'OK' if near_zero else 'not-near-zero'}),"
            f" B_r={r['B_r']:.6f} (OK)"
        )
        print(
            f"           w0={r['design_omega']:.3f}, wn={r['omega_n']:.3f},"
            f" P_opt_unit_amp={r['P_opt_unit_amp_W']:.6f} W,"
            f" P_opt@H=0.05={r['P_opt_W']:.6f} W"
        )
        if near_resonance and not near_zero:
            raise AssertionError(
                f"VGM-{int(r['flap_angle'])}: expected |K_r| <= {K_R_NEAR_ZERO_TOL} "
                f"when w0~wn (w0={r['design_omega']:.3f}, wn={r['omega_n']:.3f}); "
                f"got {r['K_r']:.4f}"
            )

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "flap_angle",
            "design_omega",
            "omega_n",
            "I_hinge",
            "A55_w0",
            "B55_w0",
            "Fexc55_w0",
            "K_r",
            "B_r",
            "P_opt_W",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})

    print(f"\nWrote CSV: {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
