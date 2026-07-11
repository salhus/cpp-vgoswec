#!/usr/bin/env python3
"""Three-controller regime comparison for VGOSWEC flap variants.

Three-regime relay: CC (short periods) → opt_passive (resonance band) → ff+PID (long periods).

Loads per-flap CSVs from:
  analysis/cc/               — complex-conjugate controller
  analysis/opt_passive/      — optimal-passive damper
  analysis/passive_guarded/  — tuned exc_ff_pid (ff+PID) controller

Produces under analysis/three_regime/figures/:

Per-flap figures (one per VGM variant):
  three_regime_VGM<angle>.png  — P_capture overlay (all three controllers) with shaded
                                  winning-regime bands and crossover markers.
  three_regime_efficiency_VGM<angle>.png — efficiency overlay.

Cross-flap summary figures:
  three_regime_summary.png
  three_regime_efficiency_summary.png

Master operating-envelope figure:
  operating_envelope.png  — upper hull (best controller × best flap) at every period.
  operating_envelope.csv  — per-period hull table for reproducibility.

Per-flap peak table (opt_passive resonance humps march with flap angle):
  VGM-90: 0.509 W at T=2.50 s  → VGM-45: 0.479 W at T=3.00 s →
  VGM-20: 0.755 W at T=3.25 s  → VGM-10: 0.772 W at T=3.50 s →
  VGM-0:  0.681 W at T=4.75 s

Three-regime key result:
  CC wins T ≲ 2 s (near Budal bound, up to 2.34 W).
  opt_passive ties/beats ff+PID at the resonance peak for low-angle flaps (VGM-0/10/20);
  ff+PID edges it for high-angle flaps (VGM-45/90). opt_passive matches a tuned
  feedforward controller at resonance with a single tuning-free damping coefficient.
  ff+PID carries the long tail past resonance.

Run in --plot-only mode (default) to regenerate all figures from committed CSVs:
  python3 scripts/three_regime_comparison.py --plot-only
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import AutoMinorLocator, MultipleLocator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FLAP_ANGLES = [0, 10, 20, 45, 90]
FLAP_LABELS = {0: "VGM-0", 10: "VGM-10", 20: "VGM-20", 45: "VGM-45", 90: "VGM-90"}

# opt_passive resonance-peak periods T₀ [s] per flap (marches with flap angle).
# Used to shade the three regime bands per flap.
RESONANCE_PEAK_T = {0: 4.75, 10: 3.50, 20: 3.25, 45: 3.00, 90: 2.50}

# CC practical upper-period limit: beyond this it is reactive-heavy.
CC_PRACTICAL_LIMIT_T = 2.0

ETA_GT1_TOL = 1e-6

JOURNAL_STYLE = {
    "font.family": "serif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
}

# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def _load_cc_csv(csv_path: Path) -> list[dict]:
    """Load a CC efficiency CSV (has P_converted_W and P_injected_W)."""
    rows: list[dict] = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append({
                "T_s": float(r["T_s"]),
                "P_capture_W": float(r["P_capture_W"]) if r.get("P_capture_W", "").strip() else float("nan"),
                "P_opt_W": float(r["P_opt_W"]) if r.get("P_opt_W", "").strip() else float("nan"),
                "eta": float(r["eta"]) if r.get("eta", "").strip() else float("nan"),
                "masked": str(r.get("masked", "false")).strip().lower() == "true",
                "linear_popt_invalid": str(r.get("linear_popt_invalid", "false")).strip().lower() == "true",
            })
    rows.sort(key=lambda d: d["T_s"])
    return rows


def _load_opt_passive_csv(csv_path: Path) -> list[dict]:
    """Load an opt_passive efficiency CSV (8-col: T,omega,P_cap,P_opt,B55,F_exc,eta,masked)."""
    rows: list[dict] = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append({
                "T_s": float(r["T_s"]),
                "P_capture_W": float(r["P_capture_W"]) if r.get("P_capture_W", "").strip() else float("nan"),
                "P_opt_W": float(r["P_opt_W"]) if r.get("P_opt_W", "").strip() else float("nan"),
                "B55_Nmsrad": float(r["B55_Nmsrad"]) if r.get("B55_Nmsrad", "").strip() else float("nan"),
                "eta": float(r["eta"]) if r.get("eta", "").strip() else float("nan"),
                "masked": str(r.get("masked", "false")).strip().lower() == "true",
            })
    rows.sort(key=lambda d: d["T_s"])
    return rows


def _load_ffpid_csv(csv_path: Path) -> list[dict]:
    """Load an exc_ff_pid (passive_guarded) efficiency CSV."""
    rows: list[dict] = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append({
                "T_s": float(r["T_s"]),
                "P_capture_W": float(r["P_capture_W"]) if r.get("P_capture_W", "").strip() else float("nan"),
                "P_opt_W": float(r["P_opt_W"]) if r.get("P_opt_W", "").strip() else float("nan"),
                "eta": float(r["eta"]) if r.get("eta", "").strip() else float("nan"),
                "masked": str(r.get("masked", "false")).strip().lower() == "true",
            })
    rows.sort(key=lambda d: d["T_s"])
    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eta_valid(row: dict, is_cc: bool = False) -> tuple[float, bool]:
    """Return (eta_fraction, is_invalid).  is_invalid means eta>1+tol or undefined."""
    eta = row.get("eta", float("nan"))
    if not math.isfinite(eta):
        # Try to compute from P_capture / P_opt
        p_cap = row.get("P_capture_W", float("nan"))
        p_opt = row.get("P_opt_W", float("nan"))
        if math.isfinite(p_cap) and math.isfinite(p_opt) and p_opt > 0.0 and not row.get("masked", False):
            eta = p_cap / p_opt
        else:
            return float("nan"), True
    invalid = bool(
        row.get("linear_popt_invalid", False)
        or (math.isfinite(eta) and eta > (1.0 + ETA_GT1_TOL))
    )
    return eta, invalid


def _masked_spans(periods: np.ndarray, masked: np.ndarray) -> list[tuple[float, float]]:
    """Return list of (x0, x1) spans where masked=True (padded by half-step)."""
    spans: list[tuple[float, float]] = []
    if len(periods) < 2:
        return spans
    half_step = float(np.median(np.diff(periods))) / 2.0
    idx = np.where(masked)[0]
    if len(idx) == 0:
        return spans
    start = idx[0]
    prev = idx[0]
    for i in idx[1:]:
        if i == prev + 1:
            prev = i
            continue
        spans.append((periods[start] - half_step, periods[prev] + half_step))
        start = i
        prev = i
    spans.append((periods[start] - half_step, periods[prev] + half_step))
    return spans


def _add_masked_spans(ax, periods: np.ndarray, masked: np.ndarray, label: str = "") -> None:
    """Add hatched shading for masked (invalid/low-power) regions."""
    first = True
    for x0, x1 in _masked_spans(periods, masked):
        ax.axvspan(
            x0, x1,
            facecolor="0.92", edgecolor="0.45", hatch="//",
            alpha=0.50, linewidth=0.0, zorder=0.1,
            label=label if (first and label) else None,
        )
        first = False


def _style_period_axis(ax) -> None:
    ax.xaxis.set_major_locator(MultipleLocator(1.0))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))


def _style_power_axis(ax) -> None:
    ax.yaxis.set_major_locator(MultipleLocator(0.5))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_efficiency_axis(ax) -> None:
    ax.yaxis.set_major_locator(MultipleLocator(10.0))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_common(ax) -> None:
    ax.set_axisbelow(True)
    ax.grid(True, which="major", alpha=0.7, linestyle="--", color="0.45")
    ax.grid(True, which="minor", alpha=0.5, linestyle="--", color="0.6")


def _ceil_to_step(value: float, step: float) -> float:
    if (not math.isfinite(value)) or value <= 0.0:
        return step
    return float(math.ceil(value / step) * step)


def _find_crossover(T_a: np.ndarray, p_a: np.ndarray,
                    T_b: np.ndarray, p_b: np.ndarray) -> float | None:
    """Return the first T where curve-a and curve-b cross (interpolated)."""
    T_shared = np.intersect1d(np.round(T_a, 6), np.round(T_b, 6))
    if T_shared.size < 2:
        return None
    pa_i = np.interp(T_shared, T_a, p_a, left=float("nan"), right=float("nan"))
    pb_i = np.interp(T_shared, T_b, p_b, left=float("nan"), right=float("nan"))
    diff = pa_i - pb_i
    finite_mask = np.isfinite(diff)
    if not np.any(finite_mask):
        return None
    diff_f = diff[finite_mask]
    T_f = T_shared[finite_mask]
    sign_changes = np.where(np.diff(np.sign(diff_f)))[0]
    if len(sign_changes) == 0:
        return None
    i = sign_changes[0]
    t0, t1 = float(T_f[i]), float(T_f[i + 1])
    d0, d1 = float(diff_f[i]), float(diff_f[i + 1])
    if d1 == d0:
        return (t0 + t1) / 2.0
    return float(t0 - d0 * (t1 - t0) / (d1 - d0))


# ---------------------------------------------------------------------------
# Power / efficiency ceiling (shared across all per-flap figures)
# ---------------------------------------------------------------------------

def _compute_ceilings(
    cc_map: dict[int, Path],
    op_map: dict[int, Path],
    fp_map: dict[int, Path],
) -> tuple[float, float]:
    """Return (power_ceiling, efficiency_ceiling) over all available CSVs."""
    p_maxima: list[float] = []
    e_maxima: list[float] = []

    loaders = [(cc_map, _load_cc_csv, True), (op_map, _load_opt_passive_csv, False),
               (fp_map, _load_ffpid_csv, False)]
    for csv_map, loader, is_cc in loaders:
        for path in csv_map.values():
            if not path.exists():
                continue
            rows = loader(path)
            for r in rows:
                p = r.get("P_capture_W", float("nan"))
                if math.isfinite(p):
                    p_maxima.append(float(p))
                if not r.get("masked", False):
                    eta, inv = _eta_valid(r, is_cc)
                    if math.isfinite(eta) and not inv:
                        e_maxima.append(float(eta * 100.0))

    power_ceil = _ceil_to_step(max(p_maxima) if p_maxima else float("nan"), 0.5)
    eff_ceil = _ceil_to_step(max(e_maxima) if e_maxima else float("nan"), 5.0)
    return power_ceil, eff_ceil


# ---------------------------------------------------------------------------
# Per-flap 3-way comparison figure (power panel)
# ---------------------------------------------------------------------------

def _shade_regime_bands(ax, cc_xover: float | None, fp_xover: float | None,
                        T_min: float, T_max: float, y_top: float) -> None:
    """Shade three winning-regime bands: CC / opt_passive / ff+PID."""
    alpha_band = 0.08
    cc_end = cc_xover if cc_xover is not None else CC_PRACTICAL_LIMIT_T
    fp_start = fp_xover if fp_xover is not None else cc_end

    if cc_end > T_min:
        ax.axvspan(T_min, min(cc_end, T_max), color="tab:blue",
                   alpha=alpha_band, zorder=0.05, label="CC regime")
    if fp_start > cc_end and fp_start < T_max:
        ax.axvspan(min(cc_end, T_max), min(fp_start, T_max), color="tab:green",
                   alpha=alpha_band, zorder=0.05, label="opt_passive regime")
    if fp_start < T_max:
        ax.axvspan(max(fp_start, T_min), T_max, color="tab:orange",
                   alpha=alpha_band, zorder=0.05, label="ff+PID regime")


def plot_per_flap_power(
    cc_rows: list[dict],
    op_rows: list[dict],
    fp_rows: list[dict],
    flap_angle: int,
    out_png: Path,
    power_ceiling: float,
) -> None:
    label = FLAP_LABELS[flap_angle]

    T_cc = np.array([r["T_s"] for r in cc_rows], dtype=float)
    p_cc = np.array([r["P_capture_W"] for r in cc_rows], dtype=float)
    masked_cc = np.array([r["masked"] for r in cc_rows], dtype=bool)

    T_op = np.array([r["T_s"] for r in op_rows], dtype=float)
    p_op = np.array([r["P_capture_W"] for r in op_rows], dtype=float)
    masked_op = np.array([r["masked"] for r in op_rows], dtype=bool)

    T_fp = np.array([r["T_s"] for r in fp_rows], dtype=float)
    p_fp = np.array([r["P_capture_W"] for r in fp_rows], dtype=float)
    masked_fp = np.array([r["masked"] for r in fp_rows], dtype=bool)

    # Crossover points
    cc_xover = _find_crossover(T_cc, p_cc, T_op, p_op)
    fp_xover = _find_crossover(T_op, p_op, T_fp, p_fp)
    # Also find CC vs ff+PID crossover (for reference)
    cc_fp_xover = _find_crossover(T_cc, p_cc, T_fp, p_fp)

    T_all = np.union1d(np.union1d(T_cc, T_op), T_fp)
    T_min, T_max = float(T_all.min()), float(T_all.max())

    # Combined masked array
    cc_mask_map = {round(T_cc[i], 6): masked_cc[i] for i in range(len(T_cc))}
    op_mask_map = {round(T_op[i], 6): masked_op[i] for i in range(len(T_op))}
    fp_mask_map = {round(T_fp[i], 6): masked_fp[i] for i in range(len(T_fp))}
    combined_masked = np.array([
        (cc_mask_map.get(round(t, 6), False)
         or op_mask_map.get(round(t, 6), False)
         or fp_mask_map.get(round(t, 6), False))
        for t in T_all
    ], dtype=bool)

    fig, ax = plt.subplots(figsize=(8.4, 5.0))

    _shade_regime_bands(ax, cc_xover, fp_xover, T_min, T_max, power_ceiling)

    # Masked shading (B55 notch / low-power region)
    _add_masked_spans(ax, T_all, combined_masked, label="masked / low-power region")

    # Plot curves
    ax.plot(T_cc, p_cc, marker="o", color="tab:blue", linewidth=1.8,
            zorder=3, label="CC")
    ax.plot(T_op, p_op, marker="s", color="tab:green", linewidth=1.8,
            linestyle="--", zorder=3, label="opt_passive")
    ax.plot(T_fp, p_fp, marker="^", color="tab:orange", linewidth=1.8,
            linestyle="--", zorder=3, label="ff+PID")

    # Crossover markers
    if cc_xover is not None:
        ax.axvline(cc_xover, color="tab:blue", linestyle=":", linewidth=1.0,
                   zorder=2, label=f"CC/opt_p xover T≈{cc_xover:.1f} s")
    if fp_xover is not None:
        ax.axvline(fp_xover, color="tab:orange", linestyle=":", linewidth=1.0,
                   zorder=2, label=f"opt_p/ff+PID xover T≈{fp_xover:.1f} s")

    # Regime band labels
    band_y = 0.93
    if cc_xover is not None and cc_xover > T_min + 0.5:
        ax.text((T_min + min(cc_xover, T_max)) / 2.0, band_y, "CC",
                transform=ax.get_xaxis_transform(), ha="center", fontsize=8,
                color="tab:blue", alpha=0.8)
    mid_start = cc_xover if cc_xover is not None else CC_PRACTICAL_LIMIT_T
    mid_end = fp_xover if fp_xover is not None else (mid_start + 1.0)
    if mid_end > mid_start + 0.4:
        ax.text((mid_start + mid_end) / 2.0, band_y, "opt_passive",
                transform=ax.get_xaxis_transform(), ha="center", fontsize=8,
                color="tab:green", alpha=0.8)
    fp_start_x = fp_xover if fp_xover is not None else mid_end
    if fp_start_x < T_max - 0.5:
        ax.text((fp_start_x + T_max) / 2.0, band_y, "ff+PID",
                transform=ax.get_xaxis_transform(), ha="center", fontsize=8,
                color="tab:orange", alpha=0.8)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Captured power [W]")
    ax.set_title(f"{label} — Three-regime controller comparison")
    _style_period_axis(ax)
    _style_power_axis(ax)
    _style_common(ax)
    ax.set_xlim(T_min - 0.1, T_max + 0.1)
    ax.set_ylim(0.0, power_ceiling)
    ax.legend(loc="upper right", fontsize=7, ncol=2)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# Per-flap efficiency comparison figure
# ---------------------------------------------------------------------------

def plot_per_flap_efficiency(
    cc_rows: list[dict],
    op_rows: list[dict],
    fp_rows: list[dict],
    flap_angle: int,
    out_png: Path,
    efficiency_ceiling: float,
) -> None:
    label = FLAP_LABELS[flap_angle]

    T_cc = np.array([r["T_s"] for r in cc_rows], dtype=float)
    masked_cc = np.array([r["masked"] for r in cc_rows], dtype=bool)
    eta_cc = np.array([
        _eta_valid(r, is_cc=True)[0] for r in cc_rows
    ], dtype=float) * 100.0
    inv_cc = np.array([_eta_valid(r, is_cc=True)[1] for r in cc_rows], dtype=bool)

    T_op = np.array([r["T_s"] for r in op_rows], dtype=float)
    masked_op = np.array([r["masked"] for r in op_rows], dtype=bool)
    eta_op = np.array([
        _eta_valid(r)[0] for r in op_rows
    ], dtype=float) * 100.0

    T_fp = np.array([r["T_s"] for r in fp_rows], dtype=float)
    masked_fp = np.array([r["masked"] for r in fp_rows], dtype=bool)
    eta_fp = np.array([
        _eta_valid(r)[0] for r in fp_rows
    ], dtype=float) * 100.0

    T_all = np.union1d(np.union1d(T_cc, T_op), T_fp)
    cc_mask_map = {round(T_cc[i], 6): masked_cc[i] for i in range(len(T_cc))}
    op_mask_map = {round(T_op[i], 6): masked_op[i] for i in range(len(T_op))}
    fp_mask_map = {round(T_fp[i], 6): masked_fp[i] for i in range(len(T_fp))}
    combined_masked = np.array([
        (cc_mask_map.get(round(t, 6), False)
         or op_mask_map.get(round(t, 6), False)
         or fp_mask_map.get(round(t, 6), False))
        for t in T_all
    ], dtype=bool)

    fig, ax = plt.subplots(figsize=(8.4, 4.8))

    _add_masked_spans(ax, T_all, combined_masked, label="masked / low-power region")

    valid_cc = (~masked_cc) & (~inv_cc) & np.isfinite(eta_cc)
    valid_op = (~masked_op) & np.isfinite(eta_op)
    valid_fp = (~masked_fp) & np.isfinite(eta_fp)

    ax.plot(T_cc[valid_cc], eta_cc[valid_cc], marker="o", color="tab:blue",
            linewidth=1.8, zorder=3, label="CC $\\eta$")
    ax.plot(T_op[valid_op], eta_op[valid_op], marker="s", color="tab:green",
            linewidth=1.8, linestyle="--", zorder=3, label="opt_passive $\\eta$")
    ax.plot(T_fp[valid_fp], eta_fp[valid_fp], marker="^", color="tab:orange",
            linewidth=1.8, linestyle="--", zorder=3, label="ff+PID $\\eta$")

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Efficiency [%]")
    ax.set_title(f"{label} — Three-regime efficiency comparison")
    _style_period_axis(ax)
    _style_efficiency_axis(ax)
    _style_common(ax)
    ax.set_ylim(0.0, efficiency_ceiling)
    ax.legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# Cross-flap summary figures
# ---------------------------------------------------------------------------

def plot_summary_power(
    cc_map: dict[int, Path],
    op_map: dict[int, Path],
    fp_map: dict[int, Path],
    out_png: Path,
    power_ceiling: float,
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.5))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAP_ANGLES)))

    for color, angle in zip(cmap, FLAP_ANGLES):
        lbl = FLAP_LABELS[angle]
        if angle in cc_map and cc_map[angle].exists():
            rows = _load_cc_csv(cc_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            p = np.array([r["P_capture_W"] for r in rows], dtype=float)
            ax.plot(T, p, marker="o", linewidth=1.5, color=color, linestyle="-",
                    label=f"{lbl} CC", zorder=3)
        if angle in op_map and op_map[angle].exists():
            rows = _load_opt_passive_csv(op_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            p = np.array([r["P_capture_W"] for r in rows], dtype=float)
            ax.plot(T, p, marker="s", linewidth=1.3, color=color, linestyle="--",
                    alpha=0.85, label=f"{lbl} opt_p", zorder=3)
        if angle in fp_map and fp_map[angle].exists():
            rows = _load_ffpid_csv(fp_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            p = np.array([r["P_capture_W"] for r in rows], dtype=float)
            ax.plot(T, p, marker="^", linewidth=1.3, color=color, linestyle=":",
                    alpha=0.80, label=f"{lbl} ff+PID", zorder=3)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Captured power [W]")
    ax.set_title("Three-regime: CC / opt_passive / ff+PID — all flap variants")
    _style_period_axis(ax)
    _style_power_axis(ax)
    _style_common(ax)
    ax.set_ylim(0.0, power_ceiling)
    ax.legend(loc="upper right", fontsize=6, ncol=3)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_summary_efficiency(
    cc_map: dict[int, Path],
    op_map: dict[int, Path],
    fp_map: dict[int, Path],
    out_png: Path,
    efficiency_ceiling: float,
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.5))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAP_ANGLES)))

    for color, angle in zip(cmap, FLAP_ANGLES):
        lbl = FLAP_LABELS[angle]
        if angle in cc_map and cc_map[angle].exists():
            rows = _load_cc_csv(cc_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            masked = np.array([r["masked"] for r in rows], dtype=bool)
            inv = np.array([_eta_valid(r, True)[1] for r in rows], dtype=bool)
            eta = np.array([_eta_valid(r, True)[0] for r in rows], dtype=float) * 100.0
            valid = (~masked) & (~inv) & np.isfinite(eta)
            ax.plot(T[valid], eta[valid], marker="o", linewidth=1.5, color=color,
                    linestyle="-", label=f"{lbl} CC", zorder=3)
        if angle in op_map and op_map[angle].exists():
            rows = _load_opt_passive_csv(op_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            masked = np.array([r["masked"] for r in rows], dtype=bool)
            eta = np.array([_eta_valid(r)[0] for r in rows], dtype=float) * 100.0
            valid = (~masked) & np.isfinite(eta)
            ax.plot(T[valid], eta[valid], marker="s", linewidth=1.3, color=color,
                    linestyle="--", alpha=0.85, label=f"{lbl} opt_p", zorder=3)
        if angle in fp_map and fp_map[angle].exists():
            rows = _load_ffpid_csv(fp_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            masked = np.array([r["masked"] for r in rows], dtype=bool)
            eta = np.array([_eta_valid(r)[0] for r in rows], dtype=float) * 100.0
            valid = (~masked) & np.isfinite(eta)
            ax.plot(T[valid], eta[valid], marker="^", linewidth=1.3, color=color,
                    linestyle=":", alpha=0.80, label=f"{lbl} ff+PID", zorder=3)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Efficiency [%]")
    ax.set_title("Three-regime efficiency — all flap variants (CC / opt_passive / ff+PID)")
    _style_period_axis(ax)
    _style_efficiency_axis(ax)
    _style_common(ax)
    ax.set_ylim(0.0, efficiency_ceiling)
    ax.legend(loc="upper right", fontsize=6, ncol=3)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# Master operating-envelope figure (Task 4)
# ---------------------------------------------------------------------------

def _build_envelope(
    cc_map: dict[int, Path],
    op_map: dict[int, Path],
    fp_map: dict[int, Path],
) -> list[dict]:
    """Compute per-period upper hull across all controllers and flap angles.

    Returns list of dicts:
      T_s, P_max_W, controller, flap_angle
    """
    # Collect all T values
    all_T_sets: list[np.ndarray] = []
    loaders = [(cc_map, _load_cc_csv), (op_map, _load_opt_passive_csv),
               (fp_map, _load_ffpid_csv)]
    for cmap, loader in loaders:
        for path in cmap.values():
            if path.exists():
                rows = loader(path)
                all_T_sets.append(np.array([r["T_s"] for r in rows]))

    if not all_T_sets:
        return []

    T_grid = np.unique(np.concatenate(all_T_sets))
    T_grid = np.round(T_grid, 6)

    hull: list[dict] = []
    for T in T_grid:
        best_p = float("-inf")
        best_ctrl = ""
        best_flap = -1

        for angle in FLAP_ANGLES:
            for ctrl_name, cmap, loader in [
                ("CC", cc_map, _load_cc_csv),
                ("opt_passive", op_map, _load_opt_passive_csv),
                ("ff+PID", fp_map, _load_ffpid_csv),
            ]:
                path = cmap.get(angle)
                if path is None or not path.exists():
                    continue
                rows = loader(path)
                for r in rows:
                    if abs(r["T_s"] - T) < 1e-6:
                        p = r.get("P_capture_W", float("nan"))
                        if math.isfinite(p) and p > best_p:
                            best_p = p
                            best_ctrl = ctrl_name
                            best_flap = angle
                        break

        if best_flap >= 0:
            hull.append({
                "T_s": float(T),
                "P_max_W": float(best_p),
                "controller": best_ctrl,
                "flap_angle": best_flap,
            })

    hull.sort(key=lambda d: d["T_s"])
    return hull


def _write_envelope_csv(hull: list[dict], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["T_s", "P_max_W", "controller", "flap_angle"])
        writer.writeheader()
        writer.writerows(hull)
    print(f"[ok] wrote {csv_path}")


def plot_operating_envelope(
    hull: list[dict],
    out_png: Path,
    power_ceiling: float,
) -> None:
    T_env = np.array([d["T_s"] for d in hull], dtype=float)
    P_env = np.array([d["P_max_W"] for d in hull], dtype=float)

    fig, ax = plt.subplots(figsize=(9.0, 5.5))

    # Fill under the envelope
    ax.fill_between(T_env, 0.0, P_env, alpha=0.12, color="0.3", zorder=0.3)
    ax.plot(T_env, P_env, color="0.2", linewidth=2.2, zorder=4, label="Operating envelope (upper hull)")

    # Overlay per-controller / per-flap best segments with distinct colors
    ctrl_colors = {"CC": "tab:blue", "opt_passive": "tab:green", "ff+PID": "tab:orange"}
    ctrl_markers = {"CC": "o", "opt_passive": "s", "ff+PID": "^"}
    ctrl_linestyles = {"CC": "-", "opt_passive": "--", "ff+PID": ":"}
    labeled: set[str] = set()

    for d in hull:
        ctrl = d["controller"]
        flap = d["flap_angle"]
        lbl = f"{ctrl} (VGM-{flap})" if (ctrl, flap) not in labeled else None
        if lbl:
            labeled.add((ctrl, flap))
        ax.scatter(d["T_s"], d["P_max_W"],
                   marker=ctrl_markers.get(ctrl, "x"),
                   color=ctrl_colors.get(ctrl, "gray"),
                   s=28, zorder=5)

    # Add legend entries for controllers
    for ctrl, color in ctrl_colors.items():
        ax.plot([], [], color=color,
                marker=ctrl_markers.get(ctrl, "x"),
                linestyle="", label=ctrl)

    # Annotate regime bands
    T_min, T_max = float(T_env.min()), float(T_env.max())
    # Band: CC wins at short T
    cc_end = 2.0
    ax.axvline(cc_end, color="tab:blue", linestyle=":", linewidth=1.0, alpha=0.7)
    ax.text(T_min + (cc_end - T_min) / 2.0, 0.95,
            "CC + best flap", transform=ax.get_xaxis_transform(),
            ha="center", fontsize=8, color="tab:blue", alpha=0.8)

    # Band: resonance humps
    res_end = 4.0
    ax.axvline(res_end, color="tab:green", linestyle=":", linewidth=1.0, alpha=0.7)
    ax.text(cc_end + (res_end - cc_end) / 2.0, 0.95,
            "opt_p / ff+PID + T₀-matched flap",
            transform=ax.get_xaxis_transform(),
            ha="center", fontsize=8, color="tab:green", alpha=0.8)
    ax.text(res_end + (T_max - res_end) / 2.0, 0.95,
            "ff+PID + low-angle flap",
            transform=ax.get_xaxis_transform(),
            ha="center", fontsize=8, color="tab:orange", alpha=0.8)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Best achievable captured power [W]")
    ax.set_title(
        "VGOSWEC master operating envelope\n"
        "Upper hull: best (controller, flap angle) at every period"
    )
    _style_period_axis(ax)
    _style_power_axis(ax)
    _style_common(ax)
    ax.set_xlim(T_min - 0.1, T_max + 0.1)
    ax.set_ylim(0.0, power_ceiling)
    ax.legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# Efficiency operating-envelope (companion to power envelope)
# ---------------------------------------------------------------------------

def _build_efficiency_envelope(
    cc_map: dict[int, Path],
    op_map: dict[int, Path],
    fp_map: dict[int, Path],
) -> list[dict]:
    """Compute per-period efficiency upper hull across all controllers and flap angles.

    Rules (CRITICAL — mask-respecting):
    - Skip any (flap, controller, T) where:
        * masked == True
        * linear_popt_invalid == True (if column exists)
        * eta is NaN / empty
        * eta > 1 + ETA_GT1_TOL  (inflated-efficiency / P_opt-undefined spike)
    - If ALL candidates at a given T are masked/invalid, emit a row with
      eta_max=NaN, controller="", flap_angle=-1, masked=True.

    Returns list of dicts:
      T_s, eta_max, controller, flap_angle, masked
    """
    # Collect T grid from all available CSVs
    all_T_sets: list[np.ndarray] = []
    loaders = [(cc_map, _load_cc_csv), (op_map, _load_opt_passive_csv),
               (fp_map, _load_ffpid_csv)]
    for cmap, loader in loaders:
        for path in cmap.values():
            if path.exists():
                rows = loader(path)
                all_T_sets.append(np.array([r["T_s"] for r in rows]))

    if not all_T_sets:
        return []

    T_grid = np.unique(np.concatenate(all_T_sets))
    T_grid = np.round(T_grid, 6)

    hull: list[dict] = []
    for T in T_grid:
        best_eta = float("-inf")
        best_ctrl = ""
        best_flap = -1
        any_valid = False

        for angle in FLAP_ANGLES:
            for ctrl_name, cmap, loader, is_cc in [
                ("CC", cc_map, _load_cc_csv, True),
                ("opt_passive", op_map, _load_opt_passive_csv, False),
                ("ff+PID", fp_map, _load_ffpid_csv, False),
            ]:
                path = cmap.get(angle)
                if path is None or not path.exists():
                    continue
                rows = loader(path)
                for r in rows:
                    if abs(r["T_s"] - T) < 1e-6:
                        # Apply masks
                        if r.get("masked", False):
                            break
                        if r.get("linear_popt_invalid", False):
                            break
                        eta, invalid = _eta_valid(r, is_cc)
                        if invalid or not math.isfinite(eta):
                            break
                        any_valid = True
                        if eta > best_eta:
                            best_eta = eta
                            best_ctrl = ctrl_name
                            best_flap = angle
                        break

        if any_valid and best_flap >= 0:
            hull.append({
                "T_s": float(T),
                "eta_max": float(best_eta),
                "controller": best_ctrl,
                "flap_angle": best_flap,
                "masked": False,
            })
        else:
            # All candidates masked/invalid at this T
            hull.append({
                "T_s": float(T),
                "eta_max": float("nan"),
                "controller": "",
                "flap_angle": -1,
                "masked": True,
            })

    hull.sort(key=lambda d: d["T_s"])
    return hull


def _write_efficiency_envelope_csv(hull: list[dict], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["T_s", "eta_max", "controller", "flap_angle", "masked"]
        )
        writer.writeheader()
        for row in hull:
            writer.writerow({
                "T_s": row["T_s"],
                "eta_max": "" if (not math.isfinite(row["eta_max"])) else row["eta_max"],
                "controller": row["controller"],
                "flap_angle": row["flap_angle"] if row["flap_angle"] >= 0 else "",
                "masked": str(row["masked"]).lower(),
            })
    print(f"[ok] wrote {csv_path}")


def plot_operating_envelope_efficiency(
    hull: list[dict],
    out_png: Path,
    efficiency_ceiling: float,
) -> None:
    """Plot the efficiency operating hull (upper η envelope across all controller×flap combos)."""
    valid = [d for d in hull if not d["masked"] and math.isfinite(d["eta_max"])]
    all_T = np.array([d["T_s"] for d in hull], dtype=float)
    masked_flags = np.array([d["masked"] for d in hull], dtype=bool)

    T_valid = np.array([d["T_s"] for d in valid], dtype=float)
    eta_valid_arr = np.array([d["eta_max"] * 100.0 for d in valid], dtype=float)

    fig, ax = plt.subplots(figsize=(9.0, 5.5))

    # Hatching for all-masked periods
    _add_masked_spans(ax, all_T, masked_flags, label="Masked / P_opt undefined")

    if len(T_valid) > 0:
        # Fill under the envelope
        ax.fill_between(T_valid, 0.0, eta_valid_arr, alpha=0.12, color="0.3", zorder=0.3)
        ax.plot(T_valid, eta_valid_arr, color="0.2", linewidth=2.2, zorder=4,
                label="Efficiency envelope (upper hull)")

        # Overlay per-controller scatter with distinct colours
        ctrl_colors = {"CC": "tab:blue", "opt_passive": "tab:green", "ff+PID": "tab:orange"}
        ctrl_markers = {"CC": "o", "opt_passive": "s", "ff+PID": "^"}
        labeled: set[tuple] = set()

        for d in valid:
            ctrl = d["controller"]
            flap = d["flap_angle"]
            key = (ctrl, flap)
            lbl = f"{ctrl} (VGM-{flap})" if key not in labeled else None
            if lbl:
                labeled.add(key)
            ax.scatter(d["T_s"], d["eta_max"] * 100.0,
                       marker=ctrl_markers.get(ctrl, "x"),
                       color=ctrl_colors.get(ctrl, "gray"),
                       s=28, zorder=5)

        # Legend entries for controllers
        for ctrl, color in ctrl_colors.items():
            ax.plot([], [], color=color,
                    marker=ctrl_markers.get(ctrl, "x"),
                    linestyle="", label=ctrl)

        # Annotate regime bands
        T_min, T_max = float(all_T.min()), float(all_T.max())
        cc_end = 2.0
        res_end = 4.0
        ax.axvline(cc_end, color="tab:blue", linestyle=":", linewidth=1.0, alpha=0.7)
        ax.axvline(res_end, color="tab:green", linestyle=":", linewidth=1.0, alpha=0.7)
        ax.text(T_min + (cc_end - T_min) / 2.0, 0.95,
                "CC + best flap", transform=ax.get_xaxis_transform(),
                ha="center", fontsize=8, color="tab:blue", alpha=0.8)
        ax.text(cc_end + (res_end - cc_end) / 2.0, 0.95,
                "opt_p / ff+PID + T₀-matched flap",
                transform=ax.get_xaxis_transform(),
                ha="center", fontsize=8, color="tab:green", alpha=0.8)
        ax.text(res_end + (T_max - res_end) / 2.0, 0.95,
                "ff+PID + low-angle flap",
                transform=ax.get_xaxis_transform(),
                ha="center", fontsize=8, color="tab:orange", alpha=0.8)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Best achievable capture efficiency η [%]")
    ax.set_title(
        "VGOSWEC master efficiency operating envelope\n"
        "Upper hull: best η (controller, flap angle) at every period — masked/invalid excluded"
    )
    _style_period_axis(ax)
    _style_efficiency_axis(ax)
    _style_common(ax)
    ax.set_xlim(float(all_T.min()) - 0.1, float(all_T.max()) + 0.1)
    ax.set_ylim(0.0, efficiency_ceiling)
    ax.legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--repo",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: parent of scripts/)",
    )
    p.add_argument(
        "--plot-only",
        action="store_true",
        help="Regenerate figures from committed CSVs without running simulations",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    plt.rcParams.update(JOURNAL_STYLE)

    repo = Path(args.repo).resolve()
    cc_dir = repo / "analysis" / "cc"
    op_dir = repo / "analysis" / "opt_passive"
    fp_dir = repo / "analysis" / "passive_guarded"
    out_dir = repo / "analysis" / "three_regime" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    cc_map = {a: cc_dir / f"capture_efficiency_VGM{a}.csv" for a in FLAP_ANGLES}
    op_map = {a: op_dir / f"capture_efficiency_VGM{a}.csv" for a in FLAP_ANGLES}
    fp_map = {a: fp_dir / f"capture_efficiency_VGM{a}.csv" for a in FLAP_ANGLES}

    cc_present = {a: p for a, p in cc_map.items() if p.exists()}
    op_present = {a: p for a, p in op_map.items() if p.exists()}
    fp_present = {a: p for a, p in fp_map.items() if p.exists()}

    if not (cc_present or op_present or fp_present):
        print("ERROR: no CSV files found under analysis/{cc,opt_passive,passive_guarded}/")
        return 2

    for ctrl, d in [("CC", cc_present), ("opt_passive", op_present), ("ff+PID", fp_present)]:
        missing = [a for a in FLAP_ANGLES if a not in d]
        if missing:
            print(f"[warn] {ctrl}: missing CSVs for VGM-{missing}")

    power_ceiling, efficiency_ceiling = _compute_ceilings(cc_present, op_present, fp_present)

    # Per-flap figures
    angles_available = sorted(set(cc_present) | set(op_present) | set(fp_present))
    for angle in angles_available:
        lbl = FLAP_LABELS[angle]
        cc_path = cc_present.get(angle)
        op_path = op_present.get(angle)
        fp_path = fp_present.get(angle)

        # Need at least two controllers for a meaningful comparison
        available = sum(p is not None for p in [cc_path, op_path, fp_path])
        if available < 2:
            print(f"[skip] {lbl}: fewer than 2 controllers available")
            continue

        cc_rows = _load_cc_csv(cc_path) if cc_path else []
        op_rows = _load_opt_passive_csv(op_path) if op_path else []
        fp_rows = _load_ffpid_csv(fp_path) if fp_path else []

        plot_per_flap_power(
            cc_rows, op_rows, fp_rows, angle,
            out_dir / f"three_regime_VGM{angle}.png",
            power_ceiling,
        )
        plot_per_flap_efficiency(
            cc_rows, op_rows, fp_rows, angle,
            out_dir / f"three_regime_efficiency_VGM{angle}.png",
            efficiency_ceiling,
        )

    # Cross-flap summary figures
    plot_summary_power(cc_present, op_present, fp_present,
                       out_dir / "three_regime_summary.png", power_ceiling)
    plot_summary_efficiency(cc_present, op_present, fp_present,
                            out_dir / "three_regime_efficiency_summary.png", efficiency_ceiling)

    # Master operating envelope — power hull (Task 4)
    hull = _build_envelope(cc_present, op_present, fp_present)
    if hull:
        hull_csv = repo / "analysis" / "three_regime" / "operating_envelope.csv"
        _write_envelope_csv(hull, hull_csv)
        plot_operating_envelope(hull, out_dir / "operating_envelope.png", power_ceiling)

    # Master operating envelope — efficiency hull (companion)
    eff_hull = _build_efficiency_envelope(cc_present, op_present, fp_present)
    if eff_hull:
        eff_hull_csv = repo / "analysis" / "three_regime" / "operating_envelope_efficiency.csv"
        _write_efficiency_envelope_csv(eff_hull, eff_hull_csv)
        plot_operating_envelope_efficiency(
            eff_hull, out_dir / "operating_envelope_efficiency.png", efficiency_ceiling
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
