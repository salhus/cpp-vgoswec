#!/usr/bin/env python3
"""Compute and plot capture efficiency for tuned VGOSWEC cc controllers.

Uses the shared period-aware sweep method from sweep_method.py and flags
reactive-cancellation-limited points where |P_capture| / P_converted is below
the numerical-residual tolerance.
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
import tempfile
from pathlib import Path

import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import AutoMinorLocator, MultipleLocator

from sweep_method import (
    DEFAULT_PERIOD_STEP,
    MASK_B55_THRESHOLD,
    N_AVG,
    PERIOD_GRID,
    PROVENANCE_CSV_COLS,
    TIMESTEP_S,
    WAVE_AMPLITUDE_M,
    WAVE_HEIGHT_M,
    build_period_grid,
    duration_for_period as _duration_for_period,
    load_output_rows,
    parse_provenance_fields,
    provenance_fields,
    replace_yaml_scalar,
    whole_cycle_tail_slice,
    write_efficiency_csv as _write_efficiency_csv,
)

# Shared period grid T = 0.5 … 7.0 s (uniform in T, 0.25 s steps) — identical to the
# ff+PID sweep grid so both controllers' curves share x-values point-for-point.
# Note: above T≈3–4 s CC becomes reactive-heavy (|inj|/conv → ~0.9). These are
# expected regime limits (CC is theoretically correct but practically demanding at
# long periods), not errors; the reactive ratio is plotted explicitly in the comparison.
N_SETTLE = 260
N_CYCLES = N_SETTLE + N_AVG
ETA_GT1_TOL = 1e-6
REACTIVE_RESIDUAL_TOL = 1e-2
PITCH_DOF_INDEX = 4
MASK_NOTE = f"B55 <= {MASK_B55_THRESHOLD:.0e}"
REACTIVE_NOTE = f"|P_capture| / P_converted < {REACTIVE_RESIDUAL_TOL:.0e}"

FLAPS = {
    0: {"label": "VGM-0", "config": "config/vgoswec_0_cc.yaml", "h5": "hydroData/hinged_vgoswec_0.h5"},
    10: {"label": "VGM-10", "config": "config/vgoswec_10_cc.yaml", "h5": "hydroData/hinged_vgoswec_10.h5"},
    20: {"label": "VGM-20", "config": "config/vgoswec_20_cc.yaml", "h5": "hydroData/hinged_vgoswec_20.h5"},
    45: {"label": "VGM-45", "config": "config/vgoswec_45_cc.yaml", "h5": "hydroData/hinged_vgoswec_45.h5"},
    90: {"label": "VGM-90", "config": "config/vgoswec_90_cc.yaml", "h5": "hydroData/hinged_vgoswec_90.h5"},
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


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def duration_for_period(period_s: float) -> float:
    return _duration_for_period(period_s, N_CYCLES)


def prepare_scratch_config(template: Path, scratch: Path, period_s: float) -> None:
    duration_s = duration_for_period(period_s)
    txt = template.read_text()
    txt = replace_yaml_scalar(txt, "height", f"{WAVE_HEIGHT_M}")
    txt = replace_yaml_scalar(txt, "period", f"{period_s}")
    txt = replace_yaml_scalar(txt, "duration", f"{duration_s}")
    txt = replace_yaml_scalar(txt, "timestep", f"{TIMESTEP_S}")
    txt = replace_yaml_scalar(txt, "design_omega", f"{(2.0 * math.pi) / period_s:.8f}")
    scratch.write_text(txt)


def locate_results_csv(repo: Path, scratch: Path) -> Path:
    expected = repo / "output" / f"{scratch.stem}_results.csv"
    if expected.exists():
        return expected
    matches = sorted((repo / "output").glob(f"*{scratch.stem}*results.csv"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No results CSV found for scratch config '{scratch.name}'")


def _first_present_col(rows: list[dict[str, str]], names: list[str]) -> str:
    keys = rows[0].keys()
    for name in names:
        if name in keys:
            return name
    raise RuntimeError(f"None of expected columns found: {names}")


def steady_state_metrics(csv_path: Path, period_s: float) -> tuple[float, float, float]:
    fieldnames, rows = load_output_rows(csv_path)
    steady_state_slice, _ = whole_cycle_tail_slice(fieldnames, rows, period_s, N_AVG)
    p_col = _first_present_col(rows, ["power_w"])
    tau_col = _first_present_col(rows, ["pto_torque_nm"])
    vel_col = _first_present_col(rows, ["flap_pitch_vel_rads", "flap_pitch_rate_rads"])

    p_net = np.array([float(r[p_col]) for r in rows], dtype=float)[steady_state_slice]
    tau = np.array([float(r[tau_col]) for r in rows], dtype=float)[steady_state_slice]
    vel = np.array([float(r[vel_col]) for r in rows], dtype=float)[steady_state_slice]

    inst_pto = -tau * vel
    p_converted = float(np.mean(np.maximum(inst_pto, 0.0)))
    p_injected = float(np.mean(np.maximum(-inst_pto, 0.0)))
    return float(np.mean(p_net)), p_converted, p_injected


def run_capture_sweep(
    repo: Path,
    demo: Path,
    flap_angle: int,
    period_grid: np.ndarray,
) -> dict[float, tuple[float, float, float]]:
    cfg = repo / FLAPS[flap_angle]["config"]
    captures: dict[float, tuple[float, float, float]] = {}
    with tempfile.TemporaryDirectory(prefix=f"cc-capture-eff-vgm{flap_angle}-", dir="/tmp") as td:
        scratch = Path(td) / f"cc_capture_efficiency_vgm{flap_angle}.yaml"
        for T in period_grid:
            duration_s = duration_for_period(float(T))
            prepare_scratch_config(cfg, scratch, float(T))
            cmd = [
                str(demo),
                "--config",
                str(scratch),
                "--data-dir",
                str(repo),
                "--no-viz",
                "--wave-period",
                f"{T:.2f}",
                "--wave-height",
                f"{WAVE_HEIGHT_M:.4f}",
                "--duration",
                f"{duration_s:.1f}",
            ]
            run = run_cmd(cmd, repo)
            if run.returncode != 0:
                raise RuntimeError(
                    f"Simulation failed for VGM-{flap_angle} at T={T:.2f}s\n"
                    f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
                )
            out_csv = locate_results_csv(repo, scratch)
            captures[float(T)] = steady_state_metrics(out_csv, float(T))
    return captures


def _extract_component_column(component_array: np.ndarray, omega_rads: np.ndarray) -> np.ndarray:
    if component_array.ndim == 1:
        if component_array.shape[0] != omega_rads.shape[0]:
            raise RuntimeError("Unexpected 1-D component length")
        return component_array.astype(float)
    if component_array.ndim != 2:
        raise RuntimeError(f"Unsupported component shape: {component_array.shape}")
    if component_array.shape[0] == omega_rads.shape[0] and component_array.shape[1] == 2:
        return component_array[:, 1].astype(float)
    if component_array.shape[1] == omega_rads.shape[0] and component_array.shape[0] == 2:
        return component_array[1, :].astype(float)
    if component_array.shape[0] == omega_rads.shape[0]:
        return component_array[:, -1].astype(float)
    if component_array.shape[1] == omega_rads.shape[0]:
        return component_array[-1, :].astype(float)
    raise RuntimeError(f"Could not align component shape {component_array.shape} with w length {omega_rads.shape[0]}")


def popt_curve_from_h5(h5_path: Path, periods_s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with h5py.File(h5_path, "r") as h5:
        omega_rads = np.array(h5["simulation_parameters/w"], dtype=float).squeeze()
        rho = float(np.array(h5["simulation_parameters/rho"], dtype=float).squeeze())
        g = float(np.array(h5["simulation_parameters/g"], dtype=float).squeeze())
        b55_raw = np.array(h5["body1/hydro_coeffs/radiation_damping/components/5_5"], dtype=float)
        b55_norm = _extract_component_column(b55_raw, omega_rads)
        mag = np.array(h5["body1/hydro_coeffs/excitation/mag"], dtype=float)
        if mag.ndim != 3:
            raise RuntimeError(f"Unsupported excitation/mag shape: {mag.shape}")
        fexc_norm = mag[PITCH_DOF_INDEX, 0, :]

    order = np.argsort(omega_rads)
    omega_rads = omega_rads[order]
    b55_norm = b55_norm[order]
    fexc_norm = fexc_norm[order]
    b55 = np.maximum(0.0, b55_norm * rho * omega_rads)
    fexc = fexc_norm * rho * g * WAVE_AMPLITUDE_M

    omega_targets = (2.0 * math.pi) / periods_s
    b55_t = np.interp(omega_targets, omega_rads, b55)
    fexc_t = np.interp(omega_targets, omega_rads, fexc)
    masked = b55_t <= MASK_B55_THRESHOLD
    p_opt_t = np.full_like(b55_t, np.nan, dtype=float)
    valid = ~masked
    p_opt_t[valid] = (fexc_t[valid] ** 2) / (8.0 * b55_t[valid])
    return omega_targets, b55_t, fexc_t, p_opt_t, masked


CSV_COLS = [
    "T_s",
    "omega_rads",
    "P_capture_W",
    "P_opt_W",
    "B55_Nmsrad",
    "F_exc_Nm",
    "P_converted_W",
    "P_injected_W",
    "eta",
    "masked",
    "linear_popt_invalid",
    "reactive_cancellation_limited",
    *PROVENANCE_CSV_COLS,
]


def _reactive_cancellation_limited(p_capture: float, p_converted: float) -> bool:
    if not (np.isfinite(p_capture) and np.isfinite(p_converted)):
        return False
    if p_converted <= 0.0:
        return False
    return abs(p_capture) / p_converted < REACTIVE_RESIDUAL_TOL


def _row_excluded(row: dict) -> bool:
    return bool(
        row.get("masked", False)
        or row.get("linear_popt_invalid", False)
        or row.get("reactive_cancellation_limited", False)
    )


def write_efficiency_csv(out_csv: Path, rows: list[dict]) -> None:
    _write_efficiency_csv(out_csv, rows, CSV_COLS)


def load_efficiency_csv(csv_path: Path) -> list[dict]:
    rows = []
    _, raw_rows = load_output_rows(csv_path)
    for r in raw_rows:
        row = {
            "T_s": float(r["T_s"]),
            "omega_rads": float(r["omega_rads"]) if r.get("omega_rads", "").strip() else float("nan"),
            "P_capture_W": float(r["P_capture_W"]) if r.get("P_capture_W", "").strip() else float("nan"),
            "P_opt_W": float(r["P_opt_W"]) if r.get("P_opt_W", "").strip() else float("nan"),
            "B55_Nmsrad": float(r["B55_Nmsrad"]) if r.get("B55_Nmsrad", "").strip() else float("nan"),
            "F_exc_Nm": float(r["F_exc_Nm"]) if r.get("F_exc_Nm", "").strip() else float("nan"),
            "P_converted_W": float(r["P_converted_W"]) if r.get("P_converted_W", "").strip() else float("nan"),
            "P_injected_W": float(r["P_injected_W"]) if r.get("P_injected_W", "").strip() else float("nan"),
            "eta": float(r["eta"]) if r.get("eta", "").strip() else float("nan"),
            "masked": str(r.get("masked", "false")).strip().lower() == "true",
            "linear_popt_invalid": str(r.get("linear_popt_invalid", "false")).strip().lower() == "true",
            "reactive_cancellation_limited": str(
                r.get("reactive_cancellation_limited", "false")
            ).strip().lower() == "true",
            **parse_provenance_fields(r),
        }
        if (
            (not row["masked"])
            and (not np.isfinite(row["eta"]))
            and np.isfinite(row["P_capture_W"])
            and np.isfinite(row["P_opt_W"])
            and row["P_opt_W"] > 0.0
        ):
            row["eta"] = row["P_capture_W"] / row["P_opt_W"]
        row["linear_popt_invalid"] = bool(
            row["linear_popt_invalid"] or (np.isfinite(row["eta"]) and row["eta"] > (1.0 + ETA_GT1_TOL))
        )
        row["reactive_cancellation_limited"] = bool(
            row["reactive_cancellation_limited"]
            or _reactive_cancellation_limited(row["P_capture_W"], row["P_converted_W"])
        )
        if row["reactive_cancellation_limited"]:
            row["eta"] = float("nan")
        rows.append(row)
    rows.sort(key=lambda d: d["T_s"])
    return rows


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
        ax.axvspan(
            x0,
            x1,
            facecolor="0.92",
            edgecolor="0.45",
            hatch="//",
            alpha=0.50,
            linewidth=0.0,
            zorder=0.1,
        )


def _ceil_to_step(value: float, step: float) -> float:
    if (not np.isfinite(value)) or value <= 0.0:
        return step
    return float(math.ceil(value / step) * step)


def _numeric_column_values(csv_path: Path, column: str) -> list[float]:
    vals: list[float] = []
    with csv_path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            raw = str(r.get(column, "")).strip()
            if not raw:
                continue
            try:
                vals.append(float(raw))
            except ValueError:
                continue
    return vals


def _shared_power_ceiling(repo: Path, csv_map: dict[int, Path]) -> float:
    maxima: list[float] = []
    csv_paths = list(csv_map.values())
    csv_paths.extend(
        [
            repo / "analysis" / "passive_guarded" / f"capture_efficiency_VGM{angle}.csv"
            for angle in FLAPS
            if (repo / "analysis" / "passive_guarded" / f"capture_efficiency_VGM{angle}.csv").exists()
        ]
    )
    for csv_path in csv_paths:
        maxima.extend(v for v in _numeric_column_values(csv_path, "P_capture_W") if np.isfinite(v))
        maxima.extend(v for v in _numeric_column_values(csv_path, "P_opt_W") if np.isfinite(v))
    return _ceil_to_step(max(maxima) if maxima else float("nan"), 0.25)


def _shared_efficiency_ceiling(repo: Path, csv_map: dict[int, Path]) -> float:
    maxima: list[float] = []
    csv_paths = list(csv_map.values())
    csv_paths.extend(
        [
            repo / "analysis" / "passive_guarded" / f"capture_efficiency_VGM{angle}.csv"
            for angle in FLAPS
            if (repo / "analysis" / "passive_guarded" / f"capture_efficiency_VGM{angle}.csv").exists()
        ]
    )
    for csv_path in csv_paths:
        maxima.extend(float(eta * 100.0) for eta in _numeric_column_values(csv_path, "eta") if np.isfinite(eta))
    return _ceil_to_step(max(maxima) if maxima else float("nan"), 5.0)


def _breakdown_power_ceiling(csv_map: dict[int, Path]) -> float:
    maxima: list[float] = []
    for csv_path in csv_map.values():
        maxima.extend(v for v in _numeric_column_values(csv_path, "P_capture_W") if np.isfinite(v))
        maxima.extend(v for v in _numeric_column_values(csv_path, "P_converted_W") if np.isfinite(v))
        maxima.extend(v for v in _numeric_column_values(csv_path, "P_injected_W") if np.isfinite(v))
    return _ceil_to_step(max(maxima) if maxima else float("nan"), 0.25)


def _display_mask(rows: list[dict]) -> np.ndarray:
    return np.array([_row_excluded(r) for r in rows], dtype=bool)


def plot_per_flap(rows: list[dict], flap_angle: int, out_png: Path, power_ceiling: float, efficiency_ceiling: float) -> None:
    meta = FLAPS[flap_angle]
    T = np.array([r["T_s"] for r in rows], dtype=float)
    p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
    p_opt = np.array([r["P_opt_W"] for r in rows], dtype=float)
    eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
    masked = np.array([r["masked"] for r in rows], dtype=bool)
    display_mask = _display_mask(rows)
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.2, 6.0), sharex=True)
    valid_cap = (~display_mask) & np.isfinite(p_cap)
    if np.any(valid_cap):
        ax0.plot(T[valid_cap], p_cap[valid_cap], marker="o", color="tab:blue", linewidth=1.8, label="captured", zorder=3)
    ax0.plot(T, p_opt, marker="s", color="k", linestyle="--", linewidth=1.4, label="$P_{opt}$", zorder=3)
    valid_eta = (~display_mask) & np.isfinite(eta)
    if np.any(valid_eta):
        ax1.plot(T[valid_eta], eta[valid_eta], marker="o", color="tab:green", linewidth=1.8, label="$\\eta$", zorder=3)
    for ax in (ax0, ax1):
        _style_period_axis(ax)
        _add_masked_spans(ax, T, display_mask)
        _style_common_axes(ax)
    _style_power_axis(ax0)
    _style_efficiency_axis(ax1)
    ax0.set_ylim(0.0, power_ceiling)
    ax1.set_ylim(0.0, 110.0)
    ax0.set_ylabel("Power [W]")
    ax1.set_ylabel("Efficiency [%]")
    ax1.set_xlabel("Wave period $T$ [s]")
    ax0.set_title(f"{meta['label']} capture efficiency (cc)")
    ax0.legend(loc="best", fontsize=8)
    ax1.legend(loc="best", fontsize=8)
    spans = _masked_spans(T, display_mask)
    if spans:
        x0, x1 = spans[len(spans) // 2]
        ax0.text(
            (x0 + x1) / 2.0,
            0.07,
            "hatched: masked / cancellation-limited",
            transform=ax0.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=7,
            color="0.35",
        )
    fig.text(
        0.01,
        0.01,
        f"Hatched exclusions: {MASK_NOTE} or {REACTIVE_NOTE}.",
        fontsize=7,
        color="0.35",
    )
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def plot_summary(csv_map: dict[int, Path], out_png: Path, power_ceiling: float, efficiency_ceiling: float) -> None:
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.4, 7.0), sharex=True)
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(csv_map)))
    for color, angle in zip(cmap, sorted(csv_map.keys())):
        rows = load_efficiency_csv(csv_map[angle])
        T = np.array([r["T_s"] for r in rows], dtype=float)
        p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
        eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
        display_mask = _display_mask(rows)
        label = FLAPS[angle]["label"]
        valid_eta = (~display_mask) & np.isfinite(eta)
        valid_cap = (~display_mask) & np.isfinite(p_cap)
        ax0.plot(T[valid_cap], p_cap[valid_cap], marker="o", linewidth=1.8, color=color, label=label, zorder=3)
        ax1.plot(T[valid_eta], eta[valid_eta], marker="o", linewidth=1.8, color=color, label=label, zorder=3)
    ax0.set_ylabel("Power [W]")
    ax0.set_title("Capture summary — tuned cc across VGOSWEC flap variants")
    _style_period_axis(ax0)
    _style_power_axis(ax0)
    _style_common_axes(ax0)
    ax0.set_ylim(0.0, 3.0)
    ax0.legend(loc="best", fontsize=8, ncol=2)
    ax1.set_xlabel("Wave period $T$ [s]")
    ax1.set_ylabel("Capture efficiency $\\eta$ [%]")
    _style_period_axis(ax1)
    _style_efficiency_axis(ax1)
    _style_common_axes(ax1)
    ax1.set_ylim(0.0, 110.0)
    ax1.legend(loc="best", fontsize=8, ncol=2)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def plot_power_breakdown(rows: list[dict], flap_angle: int, out_png: Path, breakdown_ceiling: float) -> None:
    meta = FLAPS[flap_angle]
    T = np.array([r["T_s"] for r in rows], dtype=float)
    display_mask = _display_mask(rows)
    converted = np.array([r["P_converted_W"] for r in rows], dtype=float)
    injected = np.array([r["P_injected_W"] for r in rows], dtype=float)
    captured = np.array([r["P_capture_W"] for r in rows], dtype=float)

    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    valid = ~display_mask
    ax.plot(T[valid], injected[valid], marker="x", linestyle="--", linewidth=1.5, color="tab:orange", label="injected", zorder=3)
    ax.plot(T[valid], converted[valid], marker="o", linewidth=1.8, color="tab:blue", label="converted", zorder=3)
    ax.plot(T[valid], captured[valid], marker="s", linewidth=1.8, color="tab:green", label="captured", zorder=3)
    _add_masked_spans(ax, T, display_mask)
    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Power [W]")
    ax.set_title(f"{meta['label']} CC power breakdown")
    _style_period_axis(ax)
    _style_power_axis(ax)
    _style_common_axes(ax)
    ax.set_ylim(0.0, breakdown_ceiling)
    ax.legend(loc="best", fontsize=8)
    ax.text(
        0.01,
        0.02,
        "captured = converted − injected",
        transform=ax.transAxes,
        fontsize=8,
        color="0.35",
    )
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def _build_csv_rows(
    period_grid: np.ndarray,
    period_step_s: float,
    captures: dict[float, tuple[float, float, float]],
    omega: np.ndarray,
    b55: np.ndarray,
    fexc: np.ndarray,
    p_opt: np.ndarray,
    masked: np.ndarray,
) -> list[dict]:
    rows: list[dict] = []
    for i, T in enumerate(period_grid):
        p_capture, p_converted, p_injected = captures.get(
            float(T), (float("nan"), float("nan"), float("nan"))
        )
        linear_popt_invalid = False
        reactive_cancellation_limited = _reactive_cancellation_limited(p_capture, p_converted)
        eta = float("nan")
        if not masked[i] and not reactive_cancellation_limited and np.isfinite(p_capture) and p_opt[i] > 0.0:
            eta_candidate = p_capture / p_opt[i]
            if eta_candidate > (1.0 + ETA_GT1_TOL):
                linear_popt_invalid = True
            else:
                eta = eta_candidate
        rows.append(
            {
                "T_s": f"{T:.2f}",
                "omega_rads": f"{omega[i]:.8f}",
                "P_capture_W": f"{p_capture:.8e}" if np.isfinite(p_capture) else "",
                "P_opt_W": "" if masked[i] else f"{p_opt[i]:.8e}",
                "B55_Nmsrad": f"{b55[i]:.8e}",
                "F_exc_Nm": f"{fexc[i]:.8e}",
                "P_converted_W": f"{p_converted:.8e}" if np.isfinite(p_converted) else "",
                "P_injected_W": f"{p_injected:.8e}" if np.isfinite(p_injected) else "",
                "eta": "" if masked[i] or reactive_cancellation_limited or linear_popt_invalid or not np.isfinite(eta) else f"{eta:.8e}",
                "masked": "true" if masked[i] else "false",
                "linear_popt_invalid": "true" if linear_popt_invalid else "false",
                "reactive_cancellation_limited": "true" if reactive_cancellation_limited else "false",
                **provenance_fields(float(T), period_step_s, N_SETTLE, N_AVG, N_CYCLES),
            }
        )
    return rows


def compute_and_write_csvs(
    repo: Path,
    demo: Path,
    run_sim: bool,
    period_grid: np.ndarray,
    period_step_s: float,
) -> dict[int, Path]:
    csv_map: dict[int, Path] = {}
    for angle, meta in FLAPS.items():
        cfg = repo / meta["config"]
        h5 = repo / meta["h5"]
        if not cfg.exists():
            print(f"[warn] skipping {meta['label']}: missing config {cfg}")
            continue
        if not h5.exists():
            print(f"[warn] skipping {meta['label']}: missing hydro H5 {h5}")
            continue

        captures: dict[float, tuple[float, float, float]] = {}
        if run_sim:
            print(f"[run] sweeping capture power for {meta['label']}...")
            captures = run_capture_sweep(repo, demo, angle, period_grid)

        omega, b55, fexc, p_opt, masked = popt_curve_from_h5(h5, period_grid)
        rows = _build_csv_rows(period_grid, period_step_s, captures, omega, b55, fexc, p_opt, masked)
        out_csv = repo / "analysis" / "cc" / f"capture_efficiency_VGM{angle}.csv"
        write_efficiency_csv(out_csv, rows)
        csv_map[angle] = out_csv
        print(f"[ok] wrote {out_csv}")
    return csv_map


def regenerate_plots_from_csv(repo: Path, csv_map: dict[int, Path]) -> None:
    power_ceiling = _shared_power_ceiling(repo, csv_map)
    efficiency_ceiling = _shared_efficiency_ceiling(repo, csv_map)
    breakdown_ceiling = _breakdown_power_ceiling(csv_map)
    for angle, csv_path in csv_map.items():
        rows = load_efficiency_csv(csv_path)
        out_png = repo / "analysis" / "cc" / "figures" / f"capture_efficiency_VGM{angle}.png"
        plot_per_flap(rows, angle, out_png, power_ceiling, efficiency_ceiling)
        print(f"[ok] wrote {out_png}")
        power_png = repo / "analysis" / "cc" / "figures" / f"power_breakdown_VGM{angle}.png"
        plot_power_breakdown(rows, angle, power_png, breakdown_ceiling)
        print(f"[ok] wrote {power_png}")
    summary_png = repo / "analysis" / "cc" / "figures" / "capture_efficiency_summary.png"
    plot_summary(csv_map, summary_png, power_ceiling, efficiency_ceiling)
    print(f"[ok] wrote {summary_png}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]), help="Repository root")
    p.add_argument("--demo", default="build/demo_vgoswec", help="Path to demo binary, relative to repo if not absolute")
    p.add_argument("--plot-only", action="store_true", help="Skip simulations/CSV generation and regenerate figures from committed CSVs")
    p.add_argument(
        "--period-step",
        type=float,
        default=DEFAULT_PERIOD_STEP,
        help="Period grid step in seconds (default: %(default)s)",
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
        csv_map = {angle: repo / "analysis" / "cc" / f"capture_efficiency_VGM{angle}.csv" for angle in FLAPS}
        present = {a: p for a, p in csv_map.items() if p.exists()}
        if not present:
            print("ERROR: No analysis/cc CSVs found for --plot-only mode")
            return 2
        regenerate_plots_from_csv(repo, present)
        return 0
    if not demo.exists():
        print(f"ERROR: Missing binary: {demo}")
        print("Build first (or use --plot-only if CSVs already exist).")
        return 2
    period_grid = build_period_grid(args.period_step)
    print(
        "[grid] period-step="
        f"{args.period_step:g} s, points={len(period_grid)}, "
        f"first={period_grid[0]:.2f} s, last={period_grid[-1]:.2f} s"
    )
    csv_map = compute_and_write_csvs(
        repo,
        demo,
        run_sim=True,
        period_grid=period_grid,
        period_step_s=args.period_step,
    )
    if not csv_map:
        print("ERROR: No flap configurations were available to process")
        return 2
    regenerate_plots_from_csv(repo, csv_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
