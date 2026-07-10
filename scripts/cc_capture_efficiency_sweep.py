#!/usr/bin/env python3
"""Compute and plot capture efficiency for VGOSWEC CC controllers.

For each available CC flap config across omega=3..12 rad/s:
  - Tune CC per-point: set opt_passive.design_omega = 2*pi/T in scratch YAML.
  - Run headless sim and compute steady-state (second-half) capture power.
  - Decompose power into converted/injected/net from p(t) = -tau*theta_dot.
  - Compute P_opt(T) from H5 Budal bound Fexc^2/(8*B55), mask B55 <= 1e-4.
  - Write per-flap CSV under analysis/cc/
  - Generate per-flap figures (capture-efficiency + injected/converted)

Figures are regenerable from committed CSV with --plot-only.
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

# Extend the exc_ff_pid sweep to include lower-frequency CC behavior; below ~3 rad/s
# VGM-0 approaches the ±1 rad small-angle envelope.
OMEGA_GRID = np.linspace(3.0, 12.0, 19)
PERIOD_GRID = 2.0 * np.pi / OMEGA_GRID
WAVE_HEIGHT_M = 0.05
WAVE_AMPLITUDE_M = 0.025
DURATION_S = 171.0
MASK_B55_THRESHOLD = 1e-4
THETA_LIMIT_RAD = 1.0
PITCH_DOF_INDEX = 4  # 0-based DOF5
MASK_NOTE = f"B55 <= {MASK_B55_THRESHOLD:.0e}"

FLAPS = {
    0: {"label": "VGM-0", "config": "config/vgoswec_0_cc.yaml", "h5": "hydroData/vgoswec_0.h5"},
    10: {"label": "VGM-10", "config": "config/vgoswec_10_cc.yaml", "h5": "hydroData/vgoswec_10.h5"},
    20: {"label": "VGM-20", "config": "config/vgoswec_20_cc.yaml", "h5": "hydroData/vgoswec_20.h5"},
    45: {"label": "VGM-45", "config": "config/vgoswec_45_cc.yaml", "h5": "hydroData/vgoswec_45.h5"},
    90: {"label": "VGM-90", "config": "config/vgoswec_90_cc.yaml", "h5": "hydroData/vgoswec_90.h5"},
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
    omega = 2.0 * math.pi / period_s
    txt = template.read_text()
    txt = _replace_yaml_scalar(txt, "height", f"{WAVE_HEIGHT_M}")
    txt = _replace_yaml_scalar(txt, "period", f"{period_s}")
    txt = _replace_yaml_scalar(txt, "duration", f"{DURATION_S}")
    txt = _replace_yaml_scalar(txt, "design_omega", f"{omega:.10f}")
    scratch.write_text(txt)


def locate_results_csv(repo: Path, scratch: Path) -> Path:
    expected = repo / "output" / f"{scratch.stem}_results.csv"
    if expected.exists():
        return expected
    matches = sorted((repo / "output").glob(f"*{scratch.stem}*results.csv"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No results CSV found for scratch config '{scratch.name}'")


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


def _infer_velocity_column(fieldnames: list[str]) -> str | None:
    if "flap_pitch_vel_rads" in fieldnames:
        return "flap_pitch_vel_rads"
    for name in fieldnames:
        lname = name.lower()
        if "pitch" in lname and "vel" in lname:
            return name
    return None


def _steady_state_arrays(csv_path: Path) -> dict[str, np.ndarray]:
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not rows:
        raise RuntimeError(f"No rows in output CSV: {csv_path}")

    s = rows[len(rows) // 2 :]
    t = np.array([float(r["time_s"]) for r in s], dtype=float)
    pitch = np.array([float(r["flap_pitch_rad"]) for r in s], dtype=float)
    tau = np.array([float(r["pto_torque_nm"]) for r in s], dtype=float)
    power_csv = np.array([float(r["power_w"]) for r in s], dtype=float)

    vel_col = _infer_velocity_column(headers)
    if vel_col is not None:
        vel = np.array([float(r[vel_col]) for r in s], dtype=float)
    else:
        dt = np.diff(t)
        if np.any(dt <= 0.0):
            raise RuntimeError(f"Non-increasing time_s in {csv_path}")
        vel = np.gradient(pitch, t)

    return {
        "headers": np.array(headers, dtype=object),
        "time_s": t,
        "pitch_rad": pitch,
        "pitch_vel_rads": vel,
        "tau_nm": tau,
        "power_csv_w": power_csv,
    }


def decomposition_from_csv(csv_path: Path) -> dict[str, float | list[str]]:
    arr = _steady_state_arrays(csv_path)
    p = -arr["tau_nm"] * arr["pitch_vel_rads"]

    p_converted = float(np.mean(np.maximum(p, 0.0)))
    p_injected = float(np.mean(np.minimum(p, 0.0)))
    p_net = float(np.mean(p))
    p_csv = float(np.mean(arr["power_csv_w"]))
    pitch_amp = float(np.max(np.abs(arr["pitch_rad"])))

    if not np.isclose(p_net, p_converted + p_injected, rtol=1e-6, atol=1e-8):
        raise RuntimeError(
            f"Decomposition mismatch in {csv_path}: net={p_net:.8e}, conv+inj={(p_converted + p_injected):.8e}"
        )
    if not np.isclose(p_net, p_csv, rtol=1e-6, atol=1e-8):
        raise RuntimeError(
            f"power_w mismatch in {csv_path}: p_net={p_net:.8e}, mean(power_w)={p_csv:.8e}"
        )

    return {
        "headers": [str(h) for h in arr["headers"].tolist()],
        "P_capture_W": p_csv,
        "P_converted_W": p_converted,
        "P_injected_W": p_injected,
        "P_net_W": p_net,
        "pitch_amp_rad": pitch_amp,
        "pitch_over_limit": pitch_amp > THETA_LIMIT_RAD,
    }


def run_capture_sweep(repo: Path, demo: Path, flap_angle: int) -> dict[float, dict[str, float | bool | list[str]]]:
    cfg = repo / FLAPS[flap_angle]["config"]
    captures: dict[float, dict[str, float | bool | list[str]]] = {}
    header_printed = False
    with tempfile.TemporaryDirectory(prefix=f"cc-capture-vgm{flap_angle}-", dir="/tmp") as td:
        scratch = Path(td) / f"cc_capture_efficiency_vgm{flap_angle}.yaml"
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
            metrics = decomposition_from_csv(out_csv)
            captures[float(T)] = metrics
            if not header_printed:
                print(f"[info] inspected results header ({out_csv.name}): {', '.join(metrics['headers'])}")
                header_printed = True
    return captures


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
        "pitch_amp_rad",
        "pitch_over_limit",
        "P_converted_W",
        "P_injected_W",
        "P_net_W",
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
            rows.append(
                {
                    "T_s": float(r["T_s"]),
                    "omega_rads": float(r["omega_rads"]),
                    "P_capture_W": float(r["P_capture_W"]),
                    "P_opt_W": float(r["P_opt_W"]) if r["P_opt_W"].strip() else float("nan"),
                    "B55_Nmsrad": float(r["B55_Nmsrad"]),
                    "F_exc_Nm": float(r["F_exc_Nm"]),
                    "eta": float(r["eta"]) if r["eta"].strip() else float("nan"),
                    "pitch_amp_rad": float(r["pitch_amp_rad"]),
                    "pitch_over_limit": str(r["pitch_over_limit"]).strip().lower() == "true",
                    "P_converted_W": float(r["P_converted_W"]),
                    "P_injected_W": float(r["P_injected_W"]),
                    "P_net_W": float(r["P_net_W"]),
                    "masked": str(r["masked"]).strip().lower() == "true",
                }
            )
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


def plot_capture_efficiency(rows: list[dict], flap_angle: int, out_png: Path) -> None:
    meta = FLAPS[flap_angle]
    T = np.array([r["T_s"] for r in rows], dtype=float)
    p_cap = np.array([r["P_capture_W"] for r in rows], dtype=float)
    p_opt = np.array([r["P_opt_W"] for r in rows], dtype=float)
    eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
    masked = np.array([r["masked"] for r in rows], dtype=bool)

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(8.2, 6.0), sharex=True)
    ax0.plot(T, p_cap, marker="o", color="tab:blue", linewidth=1.8, label="$P_{capture}$")
    ax0.plot(T, p_opt, marker="s", color="k", linestyle="--", linewidth=1.4, label="$P_{opt}$")
    ax1.plot(T, eta, marker="o", color="tab:green", linewidth=1.8, label="$\\eta$")

    over = np.array([r["pitch_over_limit"] for r in rows], dtype=bool)
    if np.any(over):
        ax0.scatter(T[over], p_cap[over], marker="x", color="tab:red", label="pitch over ±1 rad")

    for ax in (ax0, ax1):
        for x0, x1 in _masked_spans(T, masked):
            ax.axvspan(x0, x1, facecolor="0.9", edgecolor="0.5", hatch="//", alpha=0.8)
        ax.grid(True, alpha=0.3, linestyle="--")

    ax0.set_ylabel("Power [W]")
    ax1.set_ylabel("Efficiency [%]")
    ax1.set_xlabel("Wave period $T$ [s]")
    ax0.set_title(f"{meta['label']} CC capture efficiency")
    ax0.legend(loc="best", fontsize=8)
    ax1.legend(loc="best", fontsize=8)

    fig.text(0.01, 0.01, f"Mask rule: {MASK_NOTE} N·m·s/rad", fontsize=7, color="0.35")
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def plot_injected_converted(rows: list[dict], flap_angle: int, out_png: Path) -> None:
    meta = FLAPS[flap_angle]
    T = np.array([r["T_s"] for r in rows], dtype=float)
    p_conv = np.array([r["P_converted_W"] for r in rows], dtype=float)
    p_inj = np.array([r["P_injected_W"] for r in rows], dtype=float)
    p_net = np.array([r["P_net_W"] for r in rows], dtype=float)
    masked = np.array([r["masked"] for r in rows], dtype=bool)

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.bar(T, p_conv, width=0.03, color="tab:green", alpha=0.7, label="Converted (+)")
    ax.bar(T, p_inj, width=0.03, color="tab:red", alpha=0.7, label="Injected (-)")
    ax.plot(T, p_net, color="k", marker="o", linewidth=1.5, label="Net")

    for x0, x1 in _masked_spans(T, masked):
        ax.axvspan(x0, x1, facecolor="0.9", edgecolor="0.5", hatch="//", alpha=0.8)

    ax.axhline(0.0, color="0.3", linewidth=1.0)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("Power [W]")
    ax.set_title(f"{meta['label']} CC injected vs converted power")
    ax.legend(loc="best", fontsize=8)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)


def plot_summary(csv_map: dict[int, Path], out_dir: Path) -> None:
    if len(csv_map) <= 1:
        return

    fig1, ax1 = plt.subplots(figsize=(8.4, 4.6))
    fig2, ax2 = plt.subplots(figsize=(8.4, 4.6))
    cmap = plt.cm.viridis(np.linspace(0.15, 0.9, len(csv_map)))

    for color, angle in zip(cmap, sorted(csv_map.keys())):
        rows = load_efficiency_csv(csv_map[angle])
        T = np.array([r["T_s"] for r in rows], dtype=float)
        eta = np.array([r["eta"] for r in rows], dtype=float) * 100.0
        p_net = np.array([r["P_net_W"] for r in rows], dtype=float)
        ax1.plot(T, eta, marker="o", linewidth=1.8, color=color, label=FLAPS[angle]["label"])
        ax2.plot(T, p_net, marker="o", linewidth=1.8, color=color, label=FLAPS[angle]["label"])

    ax1.set_xlabel("Wave period $T$ [s]")
    ax1.set_ylabel("Capture efficiency $\\eta$ [%]")
    ax1.set_title("CC capture efficiency summary")
    ax1.grid(True, alpha=0.3, linestyle="--")
    ax1.legend(loc="best", fontsize=8, ncol=2)

    ax2.set_xlabel("Wave period $T$ [s]")
    ax2.set_ylabel("Net absorbed power [W]")
    ax2.set_title("CC net absorbed power summary")
    ax2.grid(True, alpha=0.3, linestyle="--")
    ax2.legend(loc="best", fontsize=8, ncol=2)

    out_dir.mkdir(parents=True, exist_ok=True)
    fig1.tight_layout()
    fig2.tight_layout()
    fig1.savefig(out_dir / "capture_efficiency_summary_CC.png")
    fig2.savefig(out_dir / "injected_converted_summary_CC.png")
    plt.close(fig1)
    plt.close(fig2)


def available_cc_flaps(repo: Path) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    for angle, meta in FLAPS.items():
        cfg = repo / meta["config"]
        if cfg.exists():
            out[angle] = meta
        else:
            print(f"[warn] missing CC config; skipping {meta['label']}: {cfg}")
    return out


def compute_and_write_csvs(repo: Path, demo: Path, run_sim: bool) -> dict[int, Path]:
    csv_map: dict[int, Path] = {}
    flaps = available_cc_flaps(repo)
    if not flaps:
        raise RuntimeError("No CC config files found; nothing to sweep")

    for angle, meta in flaps.items():
        captures: dict[float, dict[str, float | bool | list[str]]] = {}
        if run_sim:
            print(f"[run] sweeping CC capture power for {meta['label']}...")
            captures = run_capture_sweep(repo, demo, angle)

        omega, b55, fexc, p_opt, masked = popt_curve_from_h5(repo / meta["h5"], PERIOD_GRID)
        rows: list[dict] = []
        for i, T in enumerate(PERIOD_GRID):
            data = captures.get(float(T), {})
            p_capture = float(data.get("P_capture_W", float("nan")))
            p_conv = float(data.get("P_converted_W", float("nan")))
            p_inj = float(data.get("P_injected_W", float("nan")))
            p_net = float(data.get("P_net_W", float("nan")))
            pitch_amp = float(data.get("pitch_amp_rad", float("nan")))
            pitch_over = bool(data.get("pitch_over_limit", False)) if data else False
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
                    "pitch_amp_rad": f"{pitch_amp:.8e}",
                    "pitch_over_limit": "true" if pitch_over else "false",
                    "P_converted_W": f"{p_conv:.8e}",
                    "P_injected_W": f"{p_inj:.8e}",
                    "P_net_W": f"{p_net:.8e}",
                    "masked": "true" if masked[i] else "false",
                }
            )

        out_csv = repo / "analysis" / "cc" / f"capture_efficiency_CC_VGM{angle}.csv"
        write_efficiency_csv(out_csv, rows)
        csv_map[angle] = out_csv
        print(f"[ok] wrote {out_csv}")

    return csv_map


def regenerate_plots_from_csv(repo: Path, csv_map: dict[int, Path]) -> None:
    out_dir = repo / "analysis" / "cc" / "figures"
    for angle, csv_path in csv_map.items():
        rows = load_efficiency_csv(csv_path)
        plot_capture_efficiency(rows, angle, out_dir / f"capture_efficiency_CC_VGM{angle}.png")
        print(f"[ok] wrote {out_dir / f'capture_efficiency_CC_VGM{angle}.png'}")
        plot_injected_converted(rows, angle, out_dir / f"injected_converted_VGM{angle}.png")
        print(f"[ok] wrote {out_dir / f'injected_converted_VGM{angle}.png'}")

    plot_summary(csv_map, out_dir)
    if len(csv_map) > 1:
        print(f"[ok] wrote {out_dir / 'capture_efficiency_summary_CC.png'}")
        print(f"[ok] wrote {out_dir / 'injected_converted_summary_CC.png'}")


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
        flaps = available_cc_flaps(repo)
        if not flaps:
            print("ERROR: No CC config files found")
            return 2
        csv_map = {angle: repo / "analysis" / "cc" / f"capture_efficiency_CC_VGM{angle}.csv" for angle in flaps}
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

    try:
        csv_map = compute_and_write_csvs(repo, demo, run_sim=True)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 2
    regenerate_plots_from_csv(repo, csv_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
