#!/usr/bin/env python3
"""Passive vs optimal-passive damper capture-efficiency sweep for VGOSWEC flap variants.

For each flap angle variant (VGM-0,10,20,45,90) across T=0.5..7.0 s, runs BOTH
passive (fixed B_pto = B55(ω₀)) and opt_passive (B_opt = |Z_intrinsic(ω₀)|)
controllers and computes:

  - P_capture(T): steady-state (second-half) mean absorbed power.
  - P_opt(T): theoretical optimum from each flap H5 using body1 pitch hydrodynamics
    (radiation_damping/components/5_5 + excitation/mag[dof=5,dir=0], de-normalised).
  - eta(T) = P_capture / P_opt where defined.

Controller comparison physics:
  - At ω₀ (design resonance), opt_passive B_opt ≈ B55(ω₀) = passive B_pto; curves coincide.
  - Off-resonance, B_opt = |Z_intrinsic(ω)| > B55(ω₀) ⟹ opt_passive ≥ passive.
  - Both passive controllers bracket the CC / ff+PID envelope from below.

Output:
  - Per-flap CSVs under analysis/passive/ and analysis/opt_passive/
  - Per-flap figures under analysis/passive/figures/ and analysis/opt_passive/figures/
  - Passive vs opt_passive comparison figures under analysis/passive_vs_optpassive/figures/

Use --plot-only to regenerate all figures from committed CSVs without running the solver.

Period grid T = 0.5–7.0 s (0.25 s steps) — identical to the CC / ff+PID grids so all
four controllers' curves share x-values point-for-point.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
import tempfile
from pathlib import Path

import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import AutoMinorLocator, MultipleLocator

# ---------------------------------------------------------------------------
# Shared constants (match the CC / ff+PID sweep scripts exactly)
# ---------------------------------------------------------------------------
PERIOD_GRID = np.round(np.arange(0.5, 7.01, 0.25), 2)  # T = 0.5, 0.75, …, 7.0 s (27 pts)
WAVE_HEIGHT_M = 0.05
WAVE_AMPLITUDE_M = WAVE_HEIGHT_M / 2.0
DURATION_S = 171.0
MASK_B55_THRESHOLD = 1e-4
ETA_GT1_TOL = 1e-6
PITCH_DOF_INDEX = 4  # 0-based, DOF5 (pitch)
MASK_NOTE = f"B55 <= {MASK_B55_THRESHOLD:.0e}"

FLAPS = {
    0: {
        "label": "VGM-0",
        "passive_config": "config/vgoswec_0_passive.yaml",
        "opt_passive_config": "config/vgoswec_0_opt_passive.yaml",
        "h5": "hydroData/vgoswec_0.h5",
        "omega0": 1.07,
    },
    10: {
        "label": "VGM-10",
        "passive_config": "config/vgoswec_10_passive.yaml",
        "opt_passive_config": "config/vgoswec_10_opt_passive.yaml",
        "h5": "hydroData/vgoswec_10.h5",
        "omega0": 1.468,
    },
    20: {
        "label": "VGM-20",
        "passive_config": "config/vgoswec_20_passive.yaml",
        "opt_passive_config": "config/vgoswec_20_opt_passive.yaml",
        "h5": "hydroData/vgoswec_20.h5",
        "omega0": 1.568,
    },
    45: {
        "label": "VGM-45",
        "passive_config": "config/vgoswec_45_passive.yaml",
        "opt_passive_config": "config/vgoswec_45_opt_passive.yaml",
        "h5": "hydroData/vgoswec_45.h5",
        "omega0": 1.84,
    },
    90: {
        "label": "VGM-90",
        "passive_config": "config/vgoswec_90_passive.yaml",
        "opt_passive_config": "config/vgoswec_90_opt_passive.yaml",
        "h5": "hydroData/vgoswec_90.h5",
        "omega0": 2.094,
    },
}

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
# Simulation helpers
# ---------------------------------------------------------------------------

def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _replace_yaml_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*).*$", re.MULTILINE)
    out, n = pattern.subn(rf"\g<1>{value}", text, count=1)
    if n != 1:
        raise RuntimeError(f"Could not update key '{key}' in scratch config")
    return out


def prepare_passive_scratch(template: Path, scratch: Path, period_s: float) -> None:
    txt = template.read_text()
    txt = _replace_yaml_scalar(txt, "height", f"{WAVE_HEIGHT_M}")
    txt = _replace_yaml_scalar(txt, "period", f"{period_s}")
    txt = _replace_yaml_scalar(txt, "duration", f"{DURATION_S}")
    scratch.write_text(txt)


def prepare_opt_passive_scratch(template: Path, scratch: Path, period_s: float) -> None:
    txt = template.read_text()
    txt = _replace_yaml_scalar(txt, "height", f"{WAVE_HEIGHT_M}")
    txt = _replace_yaml_scalar(txt, "period", f"{period_s}")
    txt = _replace_yaml_scalar(txt, "duration", f"{DURATION_S}")
    # Update design_omega to match this period's excitation frequency
    txt = _replace_yaml_scalar(txt, "design_omega", f"{(2.0 * math.pi) / period_s:.8f}")
    scratch.write_text(txt)


def locate_results_csv(repo: Path, scratch: Path) -> Path:
    expected = repo / "output" / f"{scratch.stem}_results.csv"
    if expected.exists():
        return expected
    matches = sorted((repo / "output").glob(f"*{scratch.stem}*results.csv"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No results CSV found for scratch config '{scratch.name}'")


def steady_state_mean_power(csv_path: Path) -> float:
    with csv_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise RuntimeError(f"No rows in output CSV: {csv_path}")
    pw = np.array([float(r["power_w"]) for r in rows], dtype=float)
    return float(np.mean(pw[len(pw) // 2:]))


def run_capture_sweep(
    repo: Path,
    demo: Path,
    flap_angle: int,
    controller_type: str,
) -> dict[float, float]:
    """Run a single-controller capture sweep across PERIOD_GRID.

    controller_type: 'passive' or 'opt_passive'
    """
    meta = FLAPS[flap_angle]
    cfg_key = f"{controller_type}_config"
    cfg = repo / meta[cfg_key]
    prepare_fn = prepare_opt_passive_scratch if controller_type == "opt_passive" else prepare_passive_scratch

    captures: dict[float, float] = {}
    with tempfile.TemporaryDirectory(
        prefix=f"{controller_type}-vgm{flap_angle}-", dir="/tmp"
    ) as td:
        scratch = Path(td) / f"{controller_type}_vgm{flap_angle}.yaml"
        for T in PERIOD_GRID:
            prepare_fn(cfg, scratch, float(T))
            cmd = [
                str(demo),
                "--config", str(scratch),
                "--data-dir", str(repo),
                "--no-viz",
                "--wave-period", f"{T:.2f}",
                "--wave-height", f"{WAVE_HEIGHT_M:.4f}",
                "--duration", f"{DURATION_S:.1f}",
            ]
            run = run_cmd(cmd, repo)
            if run.returncode != 0:
                raise RuntimeError(
                    f"Simulation failed for VGM-{flap_angle} ({controller_type}) at T={T:.2f}s\n"
                    f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
                )
            out_csv = locate_results_csv(repo, scratch)
            captures[float(T)] = steady_state_mean_power(out_csv)
    return captures


# ---------------------------------------------------------------------------
# H5 hydrodynamics (same de-normalization as all other sweep scripts)
# ---------------------------------------------------------------------------

def _extract_component_column(arr: np.ndarray, w_rads: np.ndarray) -> np.ndarray:
    if arr.ndim == 1:
        if arr.shape[0] != w_rads.shape[0]:
            raise RuntimeError("Unexpected 1-D component length")
        return arr.astype(float)
    if arr.ndim != 2:
        raise RuntimeError(f"Unsupported component shape: {arr.shape}")
    if arr.shape[0] == w_rads.shape[0] and arr.shape[1] == 2:
        return arr[:, 1].astype(float)
    if arr.shape[1] == w_rads.shape[0] and arr.shape[0] == 2:
        return arr[1, :].astype(float)
    if arr.shape[0] == w_rads.shape[0]:
        return arr[:, -1].astype(float)
    if arr.shape[1] == w_rads.shape[0]:
        return arr[-1, :].astype(float)
    raise RuntimeError(f"Could not align component shape {arr.shape} with w length {w_rads.shape[0]}")


def popt_curve_from_h5(
    h5_path: Path, periods_s: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (omega_targets, B55, Fexc, P_opt, masked) at each period in periods_s."""
    with h5py.File(h5_path, "r") as h5:
        w = np.array(h5["simulation_parameters/w"], dtype=float).squeeze()
        rho = float(np.array(h5["simulation_parameters/rho"], dtype=float).squeeze())
        g = float(np.array(h5["simulation_parameters/g"], dtype=float).squeeze())
        b55_raw = np.array(h5["body1/hydro_coeffs/radiation_damping/components/5_5"], dtype=float)
        b55_norm = _extract_component_column(b55_raw, w)
        mag = np.array(h5["body1/hydro_coeffs/excitation/mag"], dtype=float)
        if mag.ndim != 3:
            raise RuntimeError(f"Unsupported excitation/mag shape: {mag.shape}")
        fexc_norm = mag[PITCH_DOF_INDEX, 0, :]

    order = np.argsort(w)
    w = w[order]
    b55_norm = b55_norm[order]
    fexc_norm = fexc_norm[order]

    b55 = b55_norm * rho * w
    fexc = fexc_norm * rho * g * WAVE_AMPLITUDE_M

    omega_targets = (2.0 * math.pi) / periods_s
    b55_t = np.interp(omega_targets, w, b55)
    fexc_t = np.interp(omega_targets, w, fexc)

    masked = b55_t <= MASK_B55_THRESHOLD
    p_opt_t = np.full_like(b55_t, np.nan, dtype=float)
    valid = ~masked
    p_opt_t[valid] = (fexc_t[valid] ** 2) / (8.0 * b55_t[valid])

    return omega_targets, b55_t, fexc_t, p_opt_t, masked


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

CSV_COLS = [
    "T_s", "omega_rads", "P_capture_W", "P_opt_W",
    "B55_Nmsrad", "F_exc_Nm", "eta", "masked",
]


def write_efficiency_csv(out_csv: Path, rows: list[dict]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_efficiency_csv(csv_path: Path) -> list[dict]:
    rows = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            out = {
                "T_s": float(r["T_s"]),
                "omega_rads": float(r["omega_rads"]),
                "P_capture_W": float(r["P_capture_W"]) if r.get("P_capture_W", "").strip() else float("nan"),
                "P_opt_W": float(r["P_opt_W"]) if r.get("P_opt_W", "").strip() else float("nan"),
                "B55_Nmsrad": float(r["B55_Nmsrad"]),
                "F_exc_Nm": float(r["F_exc_Nm"]),
                "eta": float(r["eta"]) if r.get("eta", "").strip() else float("nan"),
                "masked": str(r.get("masked", "false")).strip().lower() == "true",
                "linear_popt_invalid": False,
            }
            if (
                (not out["masked"])
                and (not np.isfinite(out["eta"]))
                and np.isfinite(out["P_capture_W"])
                and np.isfinite(out["P_opt_W"])
                and out["P_opt_W"] > 0.0
            ):
                out["eta"] = out["P_capture_W"] / out["P_opt_W"]
            out["linear_popt_invalid"] = bool(
                np.isfinite(out["eta"]) and out["eta"] > (1.0 + ETA_GT1_TOL)
            )
            rows.append(out)
    rows.sort(key=lambda d: d["T_s"])
    return rows


def _build_csv_rows(
    captures: dict[float, float],
    omega: np.ndarray,
    b55: np.ndarray,
    fexc: np.ndarray,
    p_opt: np.ndarray,
    masked: np.ndarray,
) -> list[dict]:
    rows: list[dict] = []
    for i, T in enumerate(PERIOD_GRID):
        p_capture = captures.get(float(T), float("nan"))
        eta = float("nan")
        if not masked[i] and np.isfinite(p_capture) and p_opt[i] > 0:
            eta = p_capture / p_opt[i]
        rows.append({
            "T_s": f"{T:.2f}",
            "omega_rads": f"{omega[i]:.8f}",
            "P_capture_W": f"{p_capture:.8e}" if np.isfinite(p_capture) else "",
            "P_opt_W": "" if masked[i] else f"{p_opt[i]:.8e}",
            "B55_Nmsrad": f"{b55[i]:.8e}",
            "F_exc_Nm": f"{fexc[i]:.8e}",
            "eta": "" if masked[i] or not np.isfinite(eta) else f"{eta:.8e}",
            "masked": "true" if masked[i] else "false",
        })
    return rows


# ---------------------------------------------------------------------------
# Plotting helpers (mirror cc/ff+PID style exactly)
# ---------------------------------------------------------------------------

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
    ax.xaxis.set_major_locator(MultipleLocator(1.0))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))


def _style_power_axis(ax) -> None:
    ax.yaxis.set_major_locator(MultipleLocator(0.5))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_efficiency_axis(ax, major_step: float = 10.0, minor_divisions: int = 2) -> None:
    ax.yaxis.set_major_locator(MultipleLocator(major_step))
    ax.yaxis.set_minor_locator(AutoMinorLocator(minor_divisions))


def _style_common_axes(ax) -> None:
    ax.set_axisbelow(True)
    ax.grid(True, which="major", alpha=0.7, linestyle="--", color="0.45")
    ax.grid(True, which="minor", alpha=0.5, linestyle="--", color="0.6")


def _add_masked_spans(ax, periods: np.ndarray, masked: np.ndarray) -> None:
    for x0, x1 in _masked_spans(periods, masked):
        ax.axvspan(x0, x1, facecolor="0.92", edgecolor="0.45", hatch="//",
                   alpha=0.50, linewidth=0.0, zorder=0.1)


def _ceil_to_step(value: float, step: float) -> float:
    if (not np.isfinite(value)) or value <= 0.0:
        return step
    return float(math.ceil(value / step) * step)


def _shared_power_ceiling(passive_csv_map: dict[int, Path], opt_csv_map: dict[int, Path]) -> float:
    maxima: list[float] = []
    for csv_map in (passive_csv_map, opt_csv_map):
        for path in csv_map.values():
            if not path.exists():
                continue
            rows = load_efficiency_csv(path)
            for r in rows:
                for key in ("P_capture_W", "P_opt_W"):
                    v = r.get(key, float("nan"))
                    if np.isfinite(v):
                        maxima.append(float(v))
    return _ceil_to_step(max(maxima) if maxima else float("nan"), 0.25)


def _shared_efficiency_ceiling(passive_csv_map: dict[int, Path], opt_csv_map: dict[int, Path]) -> float:
    maxima: list[float] = []
    for csv_map in (passive_csv_map, opt_csv_map):
        for path in csv_map.values():
            if not path.exists():
                continue
            rows = load_efficiency_csv(path)
            for r in rows:
                if (not r["masked"]) and np.isfinite(r["eta"]):
                    maxima.append(float(r["eta"] * 100.0))
    return _ceil_to_step(max(maxima) if maxima else float("nan"), 5.0)


# ---------------------------------------------------------------------------
# Per-controller per-flap figure
# ---------------------------------------------------------------------------

def plot_per_flap(
    rows: list[dict],
    flap_angle: int,
    controller_label: str,
    out_png: Path,
    power_ceiling: float,
    efficiency_ceiling: float,
) -> None:
    meta = FLAPS[flap_angle]
    T = np.array([r["T_s"] for r in rows], dtype=float)
    p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
    p_opt = np.array([r["P_opt_W"] for r in rows], dtype=float)
    eta = np.array([r["eta"] for r in rows], dtype=float)
    masked = np.array([r["masked"] for r in rows], dtype=bool)
    eta_pct = eta * 100.0

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.2, 6.0), sharex=True)

    ax0.plot(T, p_opt, marker="s", color="k", linestyle="--", linewidth=1.4,
             label="$P_{opt}$", zorder=3)
    valid_cap = np.isfinite(p_cap)
    if np.any(valid_cap):
        ax0.plot(T[valid_cap], p_cap[valid_cap], marker="o", color="tab:blue",
                 linewidth=1.8, label="$P_{capture}$", zorder=3)

    valid_eta = (~masked) & np.isfinite(eta_pct)
    if np.any(valid_eta):
        ax1.plot(T[valid_eta], eta_pct[valid_eta], marker="o", color="tab:green",
                 linewidth=1.8, label="$\\eta$", zorder=3)

    for ax in (ax0, ax1):
        _style_period_axis(ax)
        _add_masked_spans(ax, T, masked)
        _style_common_axes(ax)
    _style_power_axis(ax0)
    _style_efficiency_axis(ax1, major_step=10.0, minor_divisions=5)
    ax0.set_ylim(0.0, power_ceiling)
    ax1.set_ylim(0.0, efficiency_ceiling)

    ax0.set_ylabel("Power [W]")
    ax1.set_ylabel("Efficiency [%]")
    ax1.set_xlabel("Wave period $T$ [s]")
    ax0.set_title(f"{meta['label']} capture efficiency ({controller_label})")
    ax0.legend(loc="best", fontsize=8)
    ax1.legend(loc="best", fontsize=8)

    fig.text(
        0.01, 0.01,
        f"Mask rule: {MASK_NOTE} N·m·s/rad (reactive-limited).",
        fontsize=7, color="0.35",
    )
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_summary(
    csv_map: dict[int, Path],
    controller_label: str,
    out_png: Path,
    power_ceiling: float,
    efficiency_ceiling: float,
) -> None:
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.4, 7.0), sharex=True)
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(csv_map)))

    for color, angle in zip(cmap, sorted(csv_map.keys())):
        rows = load_efficiency_csv(csv_map[angle])
        T = np.array([r["T_s"] for r in rows], dtype=float)
        p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
        eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
        masked = np.array([r["masked"] for r in rows], dtype=bool)
        valid_eta = (~masked) & np.isfinite(eta)
        valid_cap = np.isfinite(p_cap)
        label = FLAPS[angle]["label"]
        if np.any(valid_cap):
            ax0.plot(T[valid_cap], p_cap[valid_cap], marker="o", linewidth=1.8,
                     color=color, label=label, zorder=3)
        if np.any(valid_eta):
            ax1.plot(T[valid_eta], eta[valid_eta], marker="o", linewidth=1.8,
                     color=color, label=label, zorder=3)

    ax0.set_ylabel("Power [W]")
    ax0.set_title(f"Capture summary — {controller_label} across VGOSWEC flap variants")
    _style_period_axis(ax0)
    _style_power_axis(ax0)
    _style_common_axes(ax0)
    ax0.set_ylim(0.0, power_ceiling)
    ax0.legend(loc="best", fontsize=8, ncol=2)

    ax1.set_xlabel("Wave period $T$ [s]")
    ax1.set_ylabel("Capture efficiency $\\eta$ [%]")
    _style_period_axis(ax1)
    _style_efficiency_axis(ax1)
    _style_common_axes(ax1)
    ax1.set_ylim(0.0, efficiency_ceiling)
    ax1.legend(loc="best", fontsize=8, ncol=2)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# Passive vs opt_passive comparison figures
# ---------------------------------------------------------------------------

def plot_per_flap_comparison(
    passive_rows: list[dict],
    opt_rows: list[dict],
    flap_angle: int,
    out_png: Path,
    power_ceiling: float,
) -> None:
    """Per-flap overlay: both dampers + P_opt reference on shared T axis."""
    meta = FLAPS[flap_angle]
    label = meta["label"]

    T_p = np.array([r["T_s"] for r in passive_rows], dtype=float)
    p_cap_p = np.array([r["P_capture_W"] for r in passive_rows], dtype=float)
    p_opt = np.array([r["P_opt_W"] for r in passive_rows], dtype=float)
    masked_p = np.array([r["masked"] for r in passive_rows], dtype=bool)

    T_o = np.array([r["T_s"] for r in opt_rows], dtype=float)
    p_cap_o = np.array([r["P_capture_W"] for r in opt_rows], dtype=float)
    masked_o = np.array([r["masked"] for r in opt_rows], dtype=bool)

    all_T = np.union1d(T_p, T_o)
    p_mask_map = {round(T_p[i], 6): masked_p[i] for i in range(len(T_p))}
    o_mask_map = {round(T_o[i], 6): masked_o[i] for i in range(len(T_o))}
    combined_masked = np.array(
        [p_mask_map.get(round(t, 6), False) or o_mask_map.get(round(t, 6), False)
         for t in all_T],
        dtype=bool,
    )

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.4, 7.0), sharex=True)

    # Top panel: captured power
    finite_popt = np.isfinite(p_opt)
    if np.any(finite_popt):
        ax0.plot(T_p[finite_popt], p_opt[finite_popt], marker="^", color="k",
                 linestyle="--", linewidth=1.4, zorder=3, label="$P_{opt}$")

    valid_p = np.isfinite(p_cap_p)
    if np.any(valid_p):
        ax0.plot(T_p[valid_p], p_cap_p[valid_p], marker="o", color="tab:blue",
                 linewidth=1.8, zorder=3, label="passive")

    valid_o = np.isfinite(p_cap_o)
    if np.any(valid_o):
        ax0.plot(T_o[valid_o], p_cap_o[valid_o], marker="s", color="tab:orange",
                 linewidth=1.8, zorder=3, label="opt_passive")

    # Bottom panel: efficiency
    eta_p = np.array([r["eta"] for r in passive_rows], dtype=float) * 100.0
    eta_o = np.array([r["eta"] for r in opt_rows], dtype=float) * 100.0

    valid_ep = (~masked_p) & np.isfinite(eta_p)
    valid_eo = (~masked_o) & np.isfinite(eta_o)
    if np.any(valid_ep):
        ax1.plot(T_p[valid_ep], eta_p[valid_ep], marker="o", color="tab:blue",
                 linewidth=1.8, label="passive $\\eta$", zorder=3)
    if np.any(valid_eo):
        ax1.plot(T_o[valid_eo], eta_o[valid_eo], marker="s", color="tab:orange",
                 linewidth=1.8, linestyle="--", label="opt_passive $\\eta$", zorder=3)

    for ax in (ax0, ax1):
        _style_period_axis(ax)
        _add_masked_spans(ax, all_T, combined_masked)
        _style_common_axes(ax)

    _style_power_axis(ax0)
    _style_efficiency_axis(ax1, major_step=10.0, minor_divisions=5)

    ax0.set_ylim(0.0, power_ceiling)
    ax1.set_ylim(0.0, 110.0)
    ax0.set_ylabel("Captured power [W]")
    ax1.set_ylabel("Efficiency [%]")
    ax1.set_xlabel("Wave period $T$ [s]")
    ax0.set_title(f"{label} — passive vs opt_passive on shared $T$ axis")
    ax0.legend(loc="best", fontsize=8)
    ax1.legend(loc="best", fontsize=8)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_summary_comparison(
    passive_csv_map: dict[int, Path],
    opt_csv_map: dict[int, Path],
    out_png: Path,
    power_ceiling: float,
) -> None:
    """Cross-flap summary: passive vs opt_passive captured power for all angles."""
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAPS)))

    for color, angle in zip(cmap, sorted(FLAPS.keys())):
        lbl = FLAPS[angle]["label"]
        if angle in passive_csv_map and passive_csv_map[angle].exists():
            rows = load_efficiency_csv(passive_csv_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
            valid = np.isfinite(p_cap)
            if np.any(valid):
                ax.plot(T[valid], p_cap[valid], marker="o", linewidth=1.6, color=color,
                        linestyle="-", label=f"{lbl} passive", zorder=3)
        if angle in opt_csv_map and opt_csv_map[angle].exists():
            rows = load_efficiency_csv(opt_csv_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
            valid = np.isfinite(p_cap)
            if np.any(valid):
                ax.plot(T[valid], p_cap[valid], marker="s", linewidth=1.4, color=color,
                        linestyle="--", label=f"{lbl} opt_passive", alpha=0.85, zorder=3)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Captured power [W]")
    ax.set_title("Passive vs opt_passive captured power — all VGOSWEC flap variants")
    _style_period_axis(ax)
    _style_power_axis(ax)
    _style_common_axes(ax)
    ax.set_ylim(0.0, power_ceiling)
    ax.legend(loc="best", fontsize=7, ncol=2)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_summary_efficiency_comparison(
    passive_csv_map: dict[int, Path],
    opt_csv_map: dict[int, Path],
    out_png: Path,
    efficiency_ceiling: float,
) -> None:
    """Cross-flap efficiency summary: passive vs opt_passive for all angles."""
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAPS)))

    for color, angle in zip(cmap, sorted(FLAPS.keys())):
        lbl = FLAPS[angle]["label"]
        if angle in passive_csv_map and passive_csv_map[angle].exists():
            rows = load_efficiency_csv(passive_csv_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
            masked = np.array([r["masked"] for r in rows], dtype=bool)
            valid = (~masked) & np.isfinite(eta)
            if np.any(valid):
                ax.plot(T[valid], eta[valid], marker="o", linewidth=1.6, color=color,
                        linestyle="-", label=f"{lbl} passive", zorder=3)
        if angle in opt_csv_map and opt_csv_map[angle].exists():
            rows = load_efficiency_csv(opt_csv_map[angle])
            T = np.array([r["T_s"] for r in rows], dtype=float)
            eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
            masked = np.array([r["masked"] for r in rows], dtype=bool)
            valid = (~masked) & np.isfinite(eta)
            if np.any(valid):
                ax.plot(T[valid], eta[valid], marker="s", linewidth=1.4, color=color,
                        linestyle="--", label=f"{lbl} opt_passive", alpha=0.85, zorder=3)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Efficiency [%]")
    ax.set_title("Passive vs opt_passive efficiency — all VGOSWEC flap variants")
    _style_period_axis(ax)
    _style_efficiency_axis(ax)
    _style_common_axes(ax)
    ax.set_ylim(0.0, efficiency_ceiling)
    ax.legend(loc="best", fontsize=7, ncol=2)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


# ---------------------------------------------------------------------------
# Main sweep + CSV writing
# ---------------------------------------------------------------------------

def compute_and_write_csvs(repo: Path, demo: Path, run_sim: bool) -> tuple[dict[int, Path], dict[int, Path]]:
    passive_csv_map: dict[int, Path] = {}
    opt_csv_map: dict[int, Path] = {}

    for angle, meta in FLAPS.items():
        h5_path = repo / meta["h5"]
        if not h5_path.exists():
            print(f"[warn] skipping {meta['label']}: missing hydro H5 {h5_path}")
            continue

        omega, b55, fexc, p_opt, masked = popt_curve_from_h5(h5_path, PERIOD_GRID)

        for ctrl in ("passive", "opt_passive"):
            cfg_path = repo / meta[f"{ctrl}_config"]
            if not cfg_path.exists():
                print(f"[warn] skipping {meta['label']} {ctrl}: missing config {cfg_path}")
                continue

            captures: dict[float, float] = {}
            if run_sim:
                print(f"[run] sweeping {ctrl} for {meta['label']}...")
                captures = run_capture_sweep(repo, demo, angle, ctrl)

            rows = _build_csv_rows(captures, omega, b55, fexc, p_opt, masked)

            if ctrl == "passive":
                out_csv = repo / "analysis" / "passive" / f"capture_efficiency_VGM{angle}.csv"
                write_efficiency_csv(out_csv, rows)
                passive_csv_map[angle] = out_csv
            else:
                out_csv = repo / "analysis" / "opt_passive" / f"capture_efficiency_VGM{angle}.csv"
                write_efficiency_csv(out_csv, rows)
                opt_csv_map[angle] = out_csv
            print(f"[ok] wrote {out_csv}")

    return passive_csv_map, opt_csv_map


def regenerate_plots_from_csv(
    repo: Path,
    passive_csv_map: dict[int, Path],
    opt_csv_map: dict[int, Path],
) -> None:
    power_ceiling = _shared_power_ceiling(passive_csv_map, opt_csv_map)
    efficiency_ceiling = _shared_efficiency_ceiling(passive_csv_map, opt_csv_map)

    # --- per-flap figures for each controller ---
    for ctrl, csv_map, ctrl_label, subdir in (
        ("passive", passive_csv_map, "passive damper", "passive"),
        ("opt_passive", opt_csv_map, "optimal passive", "opt_passive"),
    ):
        for angle, csv_path in csv_map.items():
            rows = load_efficiency_csv(csv_path)
            out_png = repo / "analysis" / subdir / "figures" / f"capture_efficiency_VGM{angle}.png"
            plot_per_flap(rows, angle, ctrl_label, out_png, power_ceiling, efficiency_ceiling)

        summary_png = repo / "analysis" / subdir / "figures" / "capture_efficiency_summary.png"
        plot_summary(csv_map, ctrl_label, summary_png, power_ceiling, efficiency_ceiling)

    # --- passive vs opt_passive comparison ---
    comp_dir = repo / "analysis" / "passive_vs_optpassive" / "figures"
    angles_available = sorted(set(passive_csv_map.keys()) | set(opt_csv_map.keys()))
    for angle in angles_available:
        p_path = passive_csv_map.get(angle)
        o_path = opt_csv_map.get(angle)
        if p_path is None or not p_path.exists():
            print(f"[skip] VGM-{angle}: missing passive CSV")
            continue
        if o_path is None or not o_path.exists():
            print(f"[skip] VGM-{angle}: missing opt_passive CSV")
            continue
        passive_rows = load_efficiency_csv(p_path)
        opt_rows = load_efficiency_csv(o_path)
        out_png = comp_dir / f"passive_vs_optpassive_VGM{angle}.png"
        plot_per_flap_comparison(passive_rows, opt_rows, angle, out_png, power_ceiling)

    summary_png = comp_dir / "passive_vs_optpassive_summary.png"
    plot_summary_comparison(passive_csv_map, opt_csv_map, summary_png, power_ceiling)

    summary_eta_png = comp_dir / "passive_vs_optpassive_efficiency_summary.png"
    plot_summary_efficiency_comparison(passive_csv_map, opt_csv_map, summary_eta_png, efficiency_ceiling)


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
        "--demo",
        default="build/demo_vgoswec",
        help="Path to demo binary, relative to repo if not absolute",
    )
    p.add_argument(
        "--plot-only",
        action="store_true",
        help="Skip simulations/CSV generation and regenerate figures from committed CSVs",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    plt.rcParams.update(JOURNAL_STYLE)

    repo = Path(args.repo).resolve()
    demo = Path(args.demo)
    if not demo.is_absolute():
        demo = repo / demo

    if args.plot_only:
        passive_csv_map = {
            angle: repo / "analysis" / "passive" / f"capture_efficiency_VGM{angle}.csv"
            for angle in FLAPS
        }
        opt_csv_map = {
            angle: repo / "analysis" / "opt_passive" / f"capture_efficiency_VGM{angle}.csv"
            for angle in FLAPS
        }
        missing = [p for p in list(passive_csv_map.values()) + list(opt_csv_map.values())
                   if not p.exists()]
        if missing:
            print("ERROR: Missing CSV(s) for --plot-only mode:")
            for m in missing:
                print(f"  - {m}")
            return 2
        regenerate_plots_from_csv(repo, passive_csv_map, opt_csv_map)
        return 0

    if not demo.exists():
        print(f"ERROR: Missing binary: {demo}")
        print("Build first (or use --plot-only if CSVs already exist).")
        return 2

    passive_csv_map, opt_csv_map = compute_and_write_csvs(repo, demo, run_sim=True)
    if not passive_csv_map and not opt_csv_map:
        print("ERROR: No flap configurations were available to process")
        return 2
    regenerate_plots_from_csv(repo, passive_csv_map, opt_csv_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
