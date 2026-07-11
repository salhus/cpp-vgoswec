#!/usr/bin/env python3
"""CC vs exc_ff_pid comparison overlay on a shared T=0.5–7 s period axis.

Loads per-flap CSVs from analysis/cc/ (complex-conjugate controller) and
analysis/passive_guarded/ (tuned exc_ff_pid controller) and produces:

Per-flap figure (analysis/comparison/figures/cc_vs_ffpid_VGM<angle>.png):
  Top panel   — P_capture vs T for both controllers on the same axes, with
                annotated "CC regime" (short T) / "ff+PID regime" (long T) and
                a dashed vertical line at the crossover period.
  Bottom panel — CC reactive ratio |P_injected| / P_converted vs T; the region
                where the ratio > 0.5 is shaded as "reactive-heavy (impractical)".

Cross-flap summary (analysis/comparison/figures/cc_vs_ffpid_summary.png):
  captured-power overlay for all flap angles (CC and ff+PID, separate line styles).

Matching efficiency figures are also generated:
  - analysis/comparison/figures/cc_vs_ffpid_efficiency_VGM<angle>.png
  - analysis/comparison/figures/cc_vs_ffpid_efficiency_summary.png

Use --plot-only to regenerate figures from committed CSVs without simulations.

Two-regime result (VGM-0):
  CC wins short periods T≈0.5–1 s (low reactive burden).
  ff+PID wins long periods T≳4 s (outside CC's clean absorption range).
  Crossover ≈ T≈3 s.
  CC's long-period "wins" are reactive-heavy (|inj|/conv → ~0.9) and impractical.
  CC matches the Budal theoretical bound in simulation (validated correct implementation).
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
from matplotlib.ticker import AutoMinorLocator, MaxNLocator, MultipleLocator

FLAP_ANGLES = [0, 10, 20, 45, 90]
FLAP_LABELS = {0: "VGM-0", 10: "VGM-10", 20: "VGM-20", 45: "VGM-45", 90: "VGM-90"}

# Threshold above which CC reactive ratio is flagged as "reactive-heavy (impractical)".
REACTIVE_HEAVY_THRESHOLD = 0.5
ETA_GT1_TOL = 1e-6
ETA_INVALID_LABEL = "η > 1: linear $P_{opt}$ invalid (short-period)"

# Vertical offset (in axis-fraction units) for the "reactive-heavy" label above the threshold line.
REACTIVE_LABEL_OFFSET = 0.03

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
# CSV loading helpers
# ---------------------------------------------------------------------------

def _load_cc_csv(csv_path: Path) -> list[dict]:
    """Load a CC efficiency CSV (includes P_converted_W and P_injected_W columns)."""
    rows: list[dict] = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append({
                "T_s": float(r["T_s"]),
                "P_capture_W": float(r["P_capture_W"]) if r.get("P_capture_W", "").strip() else float("nan"),
                "P_opt_W": float(r["P_opt_W"]) if r.get("P_opt_W", "").strip() else float("nan"),
                "P_converted_W": float(r["P_converted_W"]) if r.get("P_converted_W", "").strip() else float("nan"),
                "P_injected_W": float(r["P_injected_W"]) if r.get("P_injected_W", "").strip() else float("nan"),
                "eta": float(r["eta"]) if r.get("eta", "").strip() else float("nan"),
                "masked": str(r.get("masked", "false")).strip().lower() == "true",
                "linear_popt_invalid": str(r.get("linear_popt_invalid", "false")).strip().lower() == "true",
            })
    rows.sort(key=lambda d: d["T_s"])
    return rows


def _load_ffpid_csv(csv_path: Path) -> list[dict]:
    """Load an exc_ff_pid efficiency CSV."""
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


def _eta_with_flag(row: dict) -> tuple[float, bool]:
    eta = row["eta"]
    if (
        (not row["masked"])
        and (not math.isfinite(eta))
        and math.isfinite(row["P_capture_W"])
        and math.isfinite(row["P_opt_W"])
        and row["P_opt_W"] > 0.0
    ):
        eta = row["P_capture_W"] / row["P_opt_W"]
    invalid = bool(row.get("linear_popt_invalid", False) or (math.isfinite(eta) and eta > (1.0 + ETA_GT1_TOL)))
    return eta, invalid


def _reactive_ratio(p_injected: float, p_converted: float) -> float:
    """Return |P_injected| / P_converted, guarding against divide-by-zero."""
    if not (math.isfinite(p_injected) and math.isfinite(p_converted)):
        return float("nan")
    if p_converted <= 0.0:
        return float("nan")
    return abs(p_injected) / p_converted


def _masked_spans(periods: np.ndarray, masked: np.ndarray) -> list[tuple[float, float]]:
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


def _style_period_axis(ax) -> None:
    ax.xaxis.set_major_locator(MultipleLocator(0.5))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))


def _style_power_axis(ax) -> None:
    ax.yaxis.set_major_locator(MaxNLocator(nbins=8, min_n_ticks=6))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_efficiency_axis(ax) -> None:
    ax.yaxis.set_major_locator(MultipleLocator(5.0))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_ratio_axis(ax) -> None:
    ax.yaxis.set_major_locator(MaxNLocator(nbins=8, min_n_ticks=6))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_common_axes(ax) -> None:
    ax.set_axisbelow(True)
    ax.grid(True, which="major", alpha=0.3, linestyle="--")
    ax.grid(True, which="minor", alpha=0.15, linestyle="--")


def _add_masked_spans(ax, periods: np.ndarray, masked: np.ndarray) -> None:
    for x0, x1 in _masked_spans(periods, masked):
        ax.axvspan(
            x0,
            x1,
            facecolor="0.96",
            edgecolor="0.70",
            hatch="//",
            alpha=0.35,
            linewidth=0.0,
            zorder=0.1,
        )


# ---------------------------------------------------------------------------
# Per-flap comparison figure
# ---------------------------------------------------------------------------

def _find_crossover(T_cc: np.ndarray, p_cc: np.ndarray,
                    T_fp: np.ndarray, p_fp: np.ndarray) -> float | None:
    """Interpolate the crossover period where CC and ff+PID P_capture are equal.

    Returns the approximate T of the first sign change in (p_cc - p_ffpid), or None
    if the curves do not cross on the shared domain.
    """
    # Build on shared T grid (inner join)
    T_shared = np.intersect1d(np.round(T_cc, 6), np.round(T_fp, 6))
    if T_shared.size < 2:
        return None

    def _interp(T_src: np.ndarray, p_src: np.ndarray, T_tgt: np.ndarray) -> np.ndarray:
        return np.interp(T_tgt, T_src, p_src, left=float("nan"), right=float("nan"))

    diff = _interp(T_cc, p_cc, T_shared) - _interp(T_fp, p_fp, T_shared)
    sign_changes = np.where(np.diff(np.sign(diff[np.isfinite(diff)])))[0]
    if len(sign_changes) == 0:
        return None
    # Take the first sign change
    T_finite = T_shared[np.isfinite(diff)]
    i = sign_changes[0]
    # Linear interpolation within the interval
    t0, t1 = float(T_finite[i]), float(T_finite[i + 1])
    d0, d1 = float(diff[np.isfinite(diff)][i]), float(diff[np.isfinite(diff)][i + 1])
    if d1 == d0:
        return (t0 + t1) / 2.0
    return float(t0 - d0 * (t1 - t0) / (d1 - d0))


def plot_per_flap_comparison(
    cc_rows: list[dict],
    fp_rows: list[dict],
    flap_angle: int,
    out_png: Path,
) -> None:
    label = FLAP_LABELS[flap_angle]

    T_cc = np.array([r["T_s"] for r in cc_rows], dtype=float)
    p_cc = np.array([r["P_capture_W"] for r in cc_rows], dtype=float)
    p_conv = np.array([r["P_converted_W"] for r in cc_rows], dtype=float)
    p_inj = np.array([r["P_injected_W"] for r in cc_rows], dtype=float)
    masked_cc = np.array([r["masked"] for r in cc_rows], dtype=bool)

    T_fp = np.array([r["T_s"] for r in fp_rows], dtype=float)
    p_fp = np.array([r["P_capture_W"] for r in fp_rows], dtype=float)
    masked_fp = np.array([r["masked"] for r in fp_rows], dtype=bool)

    # Reactive ratio per point (guard against divide-by-zero and masked rows)
    react_ratio = np.array([
        float("nan") if masked_cc[i] else _reactive_ratio(p_inj[i], p_conv[i])
        for i in range(len(T_cc))
    ], dtype=float)

    crossover_T = _find_crossover(T_cc, p_cc, T_fp, p_fp)

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.4, 7.0), sharex=True)

    # --- Top panel: P_capture comparison ---
    ax0.plot(T_cc, p_cc, marker="o", color="tab:blue", linewidth=1.8,
             zorder=3,
             label="CC captured")
    ax0.plot(T_fp, p_fp, marker="s", color="tab:orange", linewidth=1.8,
             zorder=3,
             label="ff+PID captured")

    # Masked shading for both controllers
    all_T = np.union1d(T_cc, T_fp)
    # Build combined masked array for display (mask where either set is masked)
    T_cc_set = set(np.round(T_cc, 6))
    T_fp_set = set(np.round(T_fp, 6))
    cc_mask_map = {round(T_cc[i], 6): masked_cc[i] for i in range(len(T_cc))}
    fp_mask_map = {round(T_fp[i], 6): masked_fp[i] for i in range(len(T_fp))}
    combined_masked = np.array([
        (cc_mask_map.get(round(t, 6), False) or fp_mask_map.get(round(t, 6), False))
        for t in all_T
    ], dtype=bool)
    for ax in (ax0, ax1):
        _style_period_axis(ax)
        _add_masked_spans(ax, all_T, combined_masked)
        _style_common_axes(ax)

    if crossover_T is not None:
        ax0.axvline(crossover_T, color="gray", linestyle="--", linewidth=1.2,
                    label=f"Crossover T≈{crossover_T:.1f} s")

    # Annotate regime bands (only if axis has enough range)
    T_all = np.concatenate([T_cc, T_fp])
    T_min, T_max = float(T_all.min()), float(T_all.max())
    if crossover_T is not None and crossover_T > T_min + 0.5:
        ax0.text(
            (T_min + crossover_T) / 2.0, 0.92, "CC regime",
            transform=ax0.get_xaxis_transform(), ha="center", fontsize=8,
            color="tab:blue", alpha=0.7,
        )
    if crossover_T is not None and crossover_T < T_max - 0.5:
        ax0.text(
            (crossover_T + T_max) / 2.0, 0.92, "ff+PID regime",
            transform=ax0.get_xaxis_transform(), ha="center", fontsize=8,
            color="tab:orange", alpha=0.7,
        )

    ax0.set_ylabel("captured power [W]")
    ax0.set_title(f"{label} — CC vs ff+PID capture power on shared T axis")
    ax0.legend(loc="best", fontsize=8)
    _style_power_axis(ax0)

    # --- Bottom panel: CC reactive ratio ---
    ax1.plot(T_cc, react_ratio, marker="o", color="tab:red", linewidth=1.8,
             zorder=3,
             label="CC reactive ratio $|P_{inj}|/P_{conv}$")
    ax1.axhline(REACTIVE_HEAVY_THRESHOLD, color="0.4", linestyle=":", linewidth=1.2)

    # Shade reactive-heavy region (ratio > threshold)
    react_heavy = np.where(
        np.isfinite(react_ratio) & (react_ratio > REACTIVE_HEAVY_THRESHOLD),
        True, False
    ).astype(bool)
    # Shade between threshold and curve
    ax1.fill_between(
        T_cc, REACTIVE_HEAVY_THRESHOLD, np.where(react_ratio > REACTIVE_HEAVY_THRESHOLD, react_ratio, REACTIVE_HEAVY_THRESHOLD),
        alpha=0.18, color="tab:red", label="Reactive-heavy (impractical)",
    )
    ax1.text(
        0.99, REACTIVE_HEAVY_THRESHOLD + REACTIVE_LABEL_OFFSET,
        "reactive-heavy (impractical)",
        transform=ax1.get_yaxis_transform(), ha="right", va="bottom",
        fontsize=7, color="0.4",
    )
    ax1.set_ylabel("Reactive ratio $|P_{inj}|/P_{conv}$")
    ax1.set_xlabel("Wave period $T$ [s]")
    ax1.set_ylim(bottom=0.0)
    ax1.legend(loc="best", fontsize=8)
    _style_ratio_axis(ax1)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# Cross-flap summary figure
# ---------------------------------------------------------------------------

def plot_summary_comparison(
    cc_csv_map: dict[int, Path],
    fp_csv_map: dict[int, Path],
    out_png: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAP_ANGLES)))

    for color, angle in zip(cmap, FLAP_ANGLES):
        lbl = FLAP_LABELS[angle]
        if angle in cc_csv_map and cc_csv_map[angle].exists():
            cc_rows = _load_cc_csv(cc_csv_map[angle])
            T_cc = np.array([r["T_s"] for r in cc_rows], dtype=float)
            p_cc = np.array([r["P_capture_W"] for r in cc_rows], dtype=float)
            ax.plot(T_cc, p_cc, marker="o", linewidth=1.6, color=color,
                    linestyle="-", label=f"{lbl} CC", zorder=3)
        if angle in fp_csv_map and fp_csv_map[angle].exists():
            fp_rows = _load_ffpid_csv(fp_csv_map[angle])
            T_fp = np.array([r["T_s"] for r in fp_rows], dtype=float)
            p_fp = np.array([r["P_capture_W"] for r in fp_rows], dtype=float)
            ax.plot(T_fp, p_fp, marker="s", linewidth=1.4, color=color,
                    linestyle="--", label=f"{lbl} ff+PID", alpha=0.85, zorder=3)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("captured power [W]")
    ax.set_title("CC vs ff+PID captured power — all VGOSWEC flap variants (shared T axis)")
    _style_period_axis(ax)
    _style_power_axis(ax)
    _style_common_axes(ax)
    ax.legend(loc="best", fontsize=7, ncol=2)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_per_flap_efficiency_comparison(
    cc_rows: list[dict],
    fp_rows: list[dict],
    flap_angle: int,
    out_png: Path,
) -> None:
    label = FLAP_LABELS[flap_angle]
    T_cc = np.array([r["T_s"] for r in cc_rows], dtype=float)
    masked_cc = np.array([r["masked"] for r in cc_rows], dtype=bool)
    eta_cc_info = [_eta_with_flag(r) for r in cc_rows]
    eta_cc = np.array([v[0] for v in eta_cc_info], dtype=float) * 100.0
    invalid_cc = np.array([v[1] for v in eta_cc_info], dtype=bool)

    T_fp = np.array([r["T_s"] for r in fp_rows], dtype=float)
    masked_fp = np.array([r["masked"] for r in fp_rows], dtype=bool)
    eta_fp_info = [_eta_with_flag(r) for r in fp_rows]
    eta_fp = np.array([v[0] for v in eta_fp_info], dtype=float) * 100.0
    invalid_fp = np.array([v[1] for v in eta_fp_info], dtype=bool)

    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    valid_cc = (~masked_cc) & np.isfinite(eta_cc)
    valid_fp = (~masked_fp) & np.isfinite(eta_fp)
    ax.plot(T_cc[valid_cc], eta_cc[valid_cc], marker="o", color="tab:blue", linewidth=1.8, label="CC $\\eta$", zorder=3)
    ax.plot(T_fp[valid_fp], eta_fp[valid_fp], marker="s", color="tab:orange", linewidth=1.8, linestyle="--", label="ff+PID $\\eta$", zorder=3)

    if np.any(valid_cc & invalid_cc):
        ax.plot(
            T_cc[valid_cc & invalid_cc],
            eta_cc[valid_cc & invalid_cc],
            marker="o",
            linestyle="None",
            markerfacecolor="none",
            markeredgecolor="tab:blue",
            markeredgewidth=1.4,
            label=ETA_INVALID_LABEL,
            zorder=3,
        )
    if np.any(valid_fp & invalid_fp):
        ax.plot(
            T_fp[valid_fp & invalid_fp],
            eta_fp[valid_fp & invalid_fp],
            marker="s",
            linestyle="None",
            markerfacecolor="none",
            markeredgecolor="tab:orange",
            markeredgewidth=1.4,
            zorder=3,
        )

    all_T = np.union1d(T_cc, T_fp)
    cc_mask_map = {round(T_cc[i], 6): masked_cc[i] for i in range(len(T_cc))}
    fp_mask_map = {round(T_fp[i], 6): masked_fp[i] for i in range(len(T_fp))}
    combined_masked = np.array(
        [cc_mask_map.get(round(t, 6), False) or fp_mask_map.get(round(t, 6), False) for t in all_T],
        dtype=bool,
    )
    _style_period_axis(ax)
    _style_efficiency_axis(ax)
    _add_masked_spans(ax, all_T, combined_masked)
    _style_common_axes(ax)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Efficiency [%]")
    ax.set_title(f"{label} — CC vs ff+PID efficiency on shared T axis")
    ax.legend(loc="best", fontsize=8)
    ax.text(
        0.01,
        0.02,
        "η > 100% is shown and flagged; this indicates linear $P_{opt}$ underestimates the true optimum in that regime.",
        transform=ax.transAxes,
        fontsize=7,
        color="0.35",
    )

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_summary_efficiency_comparison(
    cc_csv_map: dict[int, Path],
    fp_csv_map: dict[int, Path],
    out_png: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAP_ANGLES)))

    for color, angle in zip(cmap, FLAP_ANGLES):
        lbl = FLAP_LABELS[angle]
        if angle in cc_csv_map and cc_csv_map[angle].exists():
            cc_rows = _load_cc_csv(cc_csv_map[angle])
            T_cc = np.array([r["T_s"] for r in cc_rows], dtype=float)
            eta_cc_info = [_eta_with_flag(r) for r in cc_rows]
            eta_cc = np.array([v[0] for v in eta_cc_info], dtype=float) * 100.0
            invalid_cc = np.array([v[1] for v in eta_cc_info], dtype=bool)
            masked_cc = np.array([r["masked"] for r in cc_rows], dtype=bool)
            valid_cc = (~masked_cc) & np.isfinite(eta_cc)
            ax.plot(T_cc[valid_cc], eta_cc[valid_cc], marker="o", linewidth=1.6, color=color, linestyle="-", label=f"{lbl} CC", zorder=3)
            if np.any(valid_cc & invalid_cc):
                ax.plot(
                    T_cc[valid_cc & invalid_cc],
                    eta_cc[valid_cc & invalid_cc],
                    marker="o",
                    linestyle="None",
                    markerfacecolor="none",
                    markeredgecolor=color,
                    markeredgewidth=1.4,
                    zorder=3,
                )
        if angle in fp_csv_map and fp_csv_map[angle].exists():
            fp_rows = _load_ffpid_csv(fp_csv_map[angle])
            T_fp = np.array([r["T_s"] for r in fp_rows], dtype=float)
            eta_fp_info = [_eta_with_flag(r) for r in fp_rows]
            eta_fp = np.array([v[0] for v in eta_fp_info], dtype=float) * 100.0
            invalid_fp = np.array([v[1] for v in eta_fp_info], dtype=bool)
            masked_fp = np.array([r["masked"] for r in fp_rows], dtype=bool)
            valid_fp = (~masked_fp) & np.isfinite(eta_fp)
            ax.plot(T_fp[valid_fp], eta_fp[valid_fp], marker="s", linewidth=1.4, color=color, linestyle="--", label=f"{lbl} ff+PID", alpha=0.85, zorder=3)
            if np.any(valid_fp & invalid_fp):
                ax.plot(
                    T_fp[valid_fp & invalid_fp],
                    eta_fp[valid_fp & invalid_fp],
                    marker="s",
                    linestyle="None",
                    markerfacecolor="none",
                    markeredgecolor=color,
                    markeredgewidth=1.4,
                    zorder=3,
                )

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Efficiency [%]")
    ax.set_title("CC vs ff+PID efficiency — all VGOSWEC flap variants (shared T axis)")
    _style_period_axis(ax)
    _style_efficiency_axis(ax)
    _style_common_axes(ax)
    ax.legend(loc="best", fontsize=7, ncol=2)
    ax.text(
        0.01,
        0.02,
        "Open markers: η > 1 (linear $P_{opt}$ invalid). η > 100% points are shown and flagged.",
        transform=ax.transAxes,
        fontsize=7,
        color="0.35",
    )

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
    fp_dir = repo / "analysis" / "passive_guarded"
    out_dir = repo / "analysis" / "comparison" / "figures"

    cc_csv_map = {a: cc_dir / f"capture_efficiency_VGM{a}.csv" for a in FLAP_ANGLES}
    fp_csv_map = {a: fp_dir / f"capture_efficiency_VGM{a}.csv" for a in FLAP_ANGLES}

    # Check availability
    cc_present = {a: p for a, p in cc_csv_map.items() if p.exists()}
    fp_present = {a: p for a, p in fp_csv_map.items() if p.exists()}

    if not cc_present and not fp_present:
        print("ERROR: No CSV files found in analysis/cc/ or analysis/passive_guarded/.")
        print("Run the sweep scripts first, or use --plot-only if CSVs already exist.")
        return 2

    if not cc_present:
        print("[warn] No CC CSVs found — comparison figures will show ff+PID only.")
    if not fp_present:
        print("[warn] No ff+PID CSVs found — comparison figures will show CC only.")

    angles_available = sorted(set(cc_present.keys()) | set(fp_present.keys()))

    for angle in angles_available:
        lbl = FLAP_LABELS[angle]
        cc_path = cc_present.get(angle)
        fp_path = fp_present.get(angle)

        if cc_path is None or fp_path is None:
            print(f"[skip] {lbl}: missing {'CC' if cc_path is None else 'ff+PID'} CSV")
            continue

        cc_rows = _load_cc_csv(cc_path)
        fp_rows = _load_ffpid_csv(fp_path)

        out_png = out_dir / f"cc_vs_ffpid_VGM{angle}.png"
        plot_per_flap_comparison(cc_rows, fp_rows, angle, out_png)
        out_eta_png = out_dir / f"cc_vs_ffpid_efficiency_VGM{angle}.png"
        plot_per_flap_efficiency_comparison(cc_rows, fp_rows, angle, out_eta_png)

    # Cross-flap summary
    summary_png = out_dir / "cc_vs_ffpid_summary.png"
    plot_summary_comparison(cc_present, fp_present, summary_png)
    summary_eta_png = out_dir / "cc_vs_ffpid_efficiency_summary.png"
    plot_summary_efficiency_comparison(cc_present, fp_present, summary_eta_png)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
