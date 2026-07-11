#!/usr/bin/env python3
"""Compute and plot capture efficiency for tuned VGOSWEC exc_ff_pid controllers.

For each flap angle variant (VGM-0,10,20,45,90) across T=0.5..7.0 s:
  - Run tuned controller headless and compute steady-state mean absorbed power
    (second half of run) => P_capture(T)
  - Compute P_opt(T) from body1 pitch hydrodynamics in H5
    (radiation_damping/components/5_5 + excitation/mag[dof=5,dir=0], de-normalized)
  - Mask reactive-limited points where B55 <= 1e-4
  - Write per-flap CSVs under analysis/passive_guarded/
  - Generate per-flap and cross-flap figures under analysis/passive_guarded/figures/

Figures are regenerable from CSV with --plot-only.

Note: below T≈1.5 s, exc_ff_pid is outside its tuned band (designed for T=2–7 s);
expected low power capture in the short-period region is not an error.
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
from matplotlib.ticker import AutoMinorLocator, MaxNLocator, MultipleLocator

# Shared period grid T = 0.5 … 7.0 s (uniform in T, 0.25 s steps) — identical to the
# CC sweep grid so both controllers' curves share x-values point-for-point.
# Note: below T≈1.5 s, exc_ff_pid is outside its tuned band (designed for T=2–7 s);
# expected low power capture in the short-period region is not an error.
PERIOD_GRID = np.round(np.arange(0.5, 7.01, 0.25), 2)  # T = 0.5, 0.75, 1.0, …, 7.0 s (27 points)
WAVE_HEIGHT_M = 0.05
WAVE_AMPLITUDE_M = WAVE_HEIGHT_M / 2.0
DURATION_S = 171.0
MASK_B55_THRESHOLD = 1e-4
ETA_GT1_TOL = 1e-6
PITCH_DOF_INDEX = 4  # 0-based, DOF5 (pitch)
MASK_NOTE = f"B55 <= {MASK_B55_THRESHOLD:.0e}"
ETA_GT1_NOTE = f"eta > {1.0 + ETA_GT1_TOL:.6f}"
ETA_INVALID_LABEL = "η > 1: linear $P_{opt}$ invalid (short-period)"

FLAPS = {
    0: {
        "label": "VGM-0",
        "config": "config/vgoswec_0_exc_ff_pid.yaml",
        "h5": "hydroData/vgoswec_0.h5",
    },
    10: {
        "label": "VGM-10",
        "config": "config/vgoswec_10_exc_ff_pid.yaml",
        "h5": "hydroData/vgoswec_10.h5",
    },
    20: {
        "label": "VGM-20",
        "config": "config/vgoswec_20_exc_ff_pid.yaml",
        "h5": "hydroData/vgoswec_20.h5",
    },
    45: {
        "label": "VGM-45",
        "config": "config/vgoswec_45_exc_ff_pid.yaml",
        "h5": "hydroData/vgoswec_45.h5",
    },
    90: {
        "label": "VGM-90",
        "config": "config/vgoswec_90_exc_ff_pid.yaml",
        "h5": "hydroData/vgoswec_90.h5",
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


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _replace_yaml_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*).*$", re.MULTILINE)
    out, n = pattern.subn(rf"\g<1>{value}", text, count=1)
    if n != 1:
        raise RuntimeError(f"Could not update key '{key}' in scratch config")
    return out


def prepare_scratch_config(template: Path, scratch: Path, period_s: float) -> None:
    txt = template.read_text()
    txt = _replace_yaml_scalar(txt, "height", f"{WAVE_HEIGHT_M}")
    txt = _replace_yaml_scalar(txt, "period", f"{period_s}")
    txt = _replace_yaml_scalar(txt, "duration", f"{DURATION_S}")
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
    return float(np.mean(pw[len(pw) // 2 :]))


def run_capture_sweep(repo: Path, demo: Path, flap_angle: int) -> dict[float, float]:
    cfg = repo / FLAPS[flap_angle]["config"]
    captures: dict[float, float] = {}
    with tempfile.TemporaryDirectory(prefix=f"capture-eff-vgm{flap_angle}-", dir="/tmp") as td:
        scratch = Path(td) / f"capture_efficiency_vgm{flap_angle}.yaml"
        for T in PERIOD_GRID:
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
                f"{DURATION_S:.1f}",
            ]
            run = run_cmd(cmd, repo)
            if run.returncode != 0:
                raise RuntimeError(
                    f"Simulation failed for VGM-{flap_angle} at T={T:.2f}s\n"
                    f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
                )
            out_csv = locate_results_csv(repo, scratch)
            captures[float(T)] = steady_state_mean_power(out_csv)
    return captures


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

    # Fallback: pick the column/row that best matches frequency length.
    if arr.shape[0] == w_rads.shape[0]:
        return arr[:, -1].astype(float)
    if arr.shape[1] == w_rads.shape[0]:
        return arr[-1, :].astype(float)
    raise RuntimeError(f"Could not align component shape {arr.shape} with w length {w_rads.shape[0]}")


def popt_curve_from_h5(h5_path: Path, periods_s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
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


def write_efficiency_csv(out_csv: Path, rows: list[dict]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "T_s",
        "omega_rads",
        "P_capture_W",
        "P_opt_W",
        "B55_Nmsrad",
        "F_exc_Nm",
        "eta",
        "masked",
    ]
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
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
                "P_capture_W": float(r["P_capture_W"]) if r["P_capture_W"].strip() else float("nan"),
                "P_opt_W": float(r["P_opt_W"]) if r["P_opt_W"].strip() else float("nan"),
                "B55_Nmsrad": float(r["B55_Nmsrad"]),
                "F_exc_Nm": float(r["F_exc_Nm"]),
                "eta": float(r["eta"]) if r["eta"].strip() else float("nan"),
                "masked": str(r["masked"]).strip().lower() == "true",
                "linear_popt_invalid": str(r.get("linear_popt_invalid", "false")).strip().lower() == "true",
            }
            if (
                (not out["masked"])
                and (not np.isfinite(out["eta"]))
                and np.isfinite(out["P_capture_W"])
                and np.isfinite(out["P_opt_W"])
                and out["P_opt_W"] > 0.0
            ):
                out["eta"] = out["P_capture_W"] / out["P_opt_W"]
            out["linear_popt_invalid"] = bool(out["linear_popt_invalid"] or (np.isfinite(out["eta"]) and out["eta"] > (1.0 + ETA_GT1_TOL)))
            rows.append(out)
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
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=4))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_efficiency_axis(ax) -> None:
    ax.yaxis.set_major_locator(MultipleLocator(10.0))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))


def _style_common_axes(ax) -> None:
    ax.set_axisbelow(True)
    ax.grid(True, which="major", alpha=0.55, linestyle="--")
    ax.grid(True, which="minor", alpha=0.30, linestyle="--")


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


def plot_per_flap(rows: list[dict], flap_angle: int, out_png: Path) -> None:
    meta = FLAPS[flap_angle]
    T = np.array([r["T_s"] for r in rows], dtype=float)
    p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
    p_opt = np.array([r["P_opt_W"] for r in rows], dtype=float)
    eta = np.array([r["eta"] for r in rows], dtype=float)
    masked = np.array([r["masked"] for r in rows], dtype=bool)
    linear_invalid = np.array([r["linear_popt_invalid"] for r in rows], dtype=bool)

    eta_pct = eta * 100.0

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.2, 6.0), sharex=True)

    ax0.plot(T, p_cap, marker="o", color="tab:blue", linewidth=1.8, label="$P_{capture}$", zorder=3)
    ax0.plot(T, p_opt, marker="s", color="k", linestyle="--", linewidth=1.4, label="$P_{opt}$", zorder=3)
    normal_eta = (~masked) & np.isfinite(eta_pct) & (~linear_invalid)
    invalid_eta = (~masked) & np.isfinite(eta_pct) & linear_invalid
    if np.any(normal_eta):
        ax1.plot(T[normal_eta], eta_pct[normal_eta], marker="o", color="tab:green", linewidth=1.8, label="$\\eta$", zorder=3)
    if np.any(invalid_eta):
        ax1.plot(
            T[invalid_eta],
            eta_pct[invalid_eta],
            marker="o",
            linestyle="None",
            markerfacecolor="none",
            markeredgecolor="tab:red",
            markeredgewidth=1.4,
            label=ETA_INVALID_LABEL,
            zorder=3,
        )

    for ax in (ax0, ax1):
        _style_period_axis(ax)
        _add_masked_spans(ax, T, masked)
        _style_common_axes(ax)
    _style_power_axis(ax0)
    _style_efficiency_axis(ax1)

    ax0.set_ylabel("Power [W]")
    ax1.set_ylabel("Efficiency [%]")
    ax1.set_xlabel("Wave period $T$ [s]")

    ax0.legend(loc="best", fontsize=8)
    ax1.legend(loc="best", fontsize=8)

    title = f"{meta['label']} capture efficiency"
    ax0.set_title(title)

    fig.text(
        0.01,
        0.01,
        (
            f"Mask rule: {MASK_NOTE} N·m·s/rad (reactive-limited). "
            "η > 100% points are shown and flagged; this indicates linear $P_{opt}$ underestimates the true optimum in that regime."
        ),
        fontsize=7,
        color="0.35",
    )

    fig.tight_layout(rect=[0, 0.03, 1, 1])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def plot_summary(csv_map: dict[int, Path], out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(csv_map)))

    for color, angle in zip(cmap, sorted(csv_map.keys())):
        rows = load_efficiency_csv(csv_map[angle])
        T = np.array([r["T_s"] for r in rows], dtype=float)
        eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
        masked = np.array([r["masked"] for r in rows], dtype=bool)
        linear_invalid = np.array([r["linear_popt_invalid"] for r in rows], dtype=bool)
        normal_eta = (~masked) & np.isfinite(eta) & (~linear_invalid)
        invalid_eta = (~masked) & np.isfinite(eta) & linear_invalid
        ax.plot(T[normal_eta], eta[normal_eta], marker="o", linewidth=1.8, color=color, label=FLAPS[angle]["label"], zorder=3)
        if np.any(invalid_eta):
            ax.plot(
                T[invalid_eta],
                eta[invalid_eta],
                marker="o",
                linestyle="None",
                markerfacecolor="none",
                markeredgecolor=color,
                markeredgewidth=1.4,
                zorder=3,
            )

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Capture efficiency $\\eta$ [%]")
    ax.set_title("Capture efficiency summary — tuned exc_ff_pid across VGOSWEC flap variants")
    _style_period_axis(ax)
    _style_efficiency_axis(ax)
    _style_common_axes(ax)
    ax.legend(loc="best", fontsize=8, ncol=2)
    ax.text(
        0.01,
        0.02,
        (
            f"Masked points omitted where {MASK_NOTE}. "
            f"Flagged markers indicate {ETA_GT1_NOTE}: linear $P_{{opt}}$ invalid (short-period)."
        ),
        transform=ax.transAxes,
        fontsize=7,
        color="0.35",
    )

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def compute_and_write_csvs(repo: Path, demo: Path, run_sim: bool) -> dict[int, Path]:
    csv_map: dict[int, Path] = {}

    for angle, meta in FLAPS.items():
        captures = {}
        if run_sim:
            print(f"[run] sweeping capture power for {meta['label']}...")
            captures = run_capture_sweep(repo, demo, angle)

        omega, b55, fexc, p_opt, masked = popt_curve_from_h5(repo / meta["h5"], PERIOD_GRID)
        rows: list[dict] = []
        for i, T in enumerate(PERIOD_GRID):
            p_capture = captures.get(float(T), float("nan"))
            eta = float("nan")
            if not masked[i] and np.isfinite(p_capture):
                eta = p_capture / p_opt[i]
            rows.append(
                {
                    "T_s": f"{T:.2f}",
                    "omega_rads": f"{omega[i]:.8f}",
                    "P_capture_W": f"{p_capture:.8e}",
                    "P_opt_W": "" if masked[i] else f"{p_opt[i]:.8e}",
                    "B55_Nmsrad": f"{b55[i]:.8e}",
                    "F_exc_Nm": f"{fexc[i]:.8e}",
                    "eta": "" if masked[i] or not np.isfinite(eta) else f"{eta:.8e}",
                    "masked": "true" if masked[i] else "false",
                }
            )

        out_csv = repo / "analysis" / "passive_guarded" / f"capture_efficiency_VGM{angle}.csv"
        write_efficiency_csv(out_csv, rows)
        csv_map[angle] = out_csv
        print(f"[ok] wrote {out_csv}")

    return csv_map


def regenerate_plots_from_csv(repo: Path, csv_map: dict[int, Path]) -> None:
    for angle, csv_path in csv_map.items():
        rows = load_efficiency_csv(csv_path)
        out_png = repo / "analysis" / "passive_guarded" / "figures" / f"capture_efficiency_VGM{angle}.png"
        plot_per_flap(rows, angle, out_png)
        print(f"[ok] wrote {out_png}")

    summary_png = repo / "analysis" / "passive_guarded" / "figures" / "capture_efficiency_summary.png"
    plot_summary(csv_map, summary_png)
    print(f"[ok] wrote {summary_png}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]), help="Repository root")
    p.add_argument("--demo", default="build/demo_vgoswec", help="Path to demo binary, relative to repo if not absolute")
    p.add_argument("--plot-only", action="store_true", help="Skip simulations/CSV generation and regenerate figures from committed CSVs")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    plt.rcParams.update(JOURNAL_STYLE)

    repo = Path(args.repo).resolve()
    demo = Path(args.demo)
    if not demo.is_absolute():
        demo = repo / demo

    if args.plot_only:
        csv_map = {angle: repo / "analysis" / "passive_guarded" / f"capture_efficiency_VGM{angle}.csv" for angle in FLAPS}
        missing = [p for p in csv_map.values() if not p.exists()]
        if missing:
            print("ERROR: Missing CSV(s) for --plot-only mode:")
            for m in missing:
                print(f"  - {m}")
            return 2
        regenerate_plots_from_csv(repo, csv_map)
        return 0

    if not demo.exists():
        print(f"ERROR: Missing binary: {demo}")
        print("Build first (or use --plot-only if CSVs already exist).")
        return 2

    csv_map = compute_and_write_csvs(repo, demo, run_sim=True)
    regenerate_plots_from_csv(repo, csv_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
