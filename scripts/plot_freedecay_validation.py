#!/usr/bin/env python3
"""Plot free-decay natural-frequency validation across VGOSWEC geometries.

Uses embedded validated fallback values, and can optionally recompute C++ FFT/zero-cross
values from output/vgoswec_*_freedecay_results.csv if those files exist.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


FALLBACK_ROWS = [
    {"config": "VGM-0",  "angle_deg": 0,  "paper_wn": 1.07, "paper_Ts": 5.86, "paper_zeta_1e4": 5.8, "cpp_zc": 1.072, "cpp_fft": 1.083},
    {"config": "VGM-10", "angle_deg": 10, "paper_wn": 1.46, "paper_Ts": 4.29, "paper_zeta_1e4": 4.3, "cpp_zc": 1.468, "cpp_fft": 1.517},
    {"config": "VGM-20", "angle_deg": 20, "paper_wn": 1.57, "paper_Ts": 4.01, "paper_zeta_1e4": 4.1, "cpp_zc": 1.568, "cpp_fft": 1.517},
    {"config": "VGM-45", "angle_deg": 45, "paper_wn": 1.84, "paper_Ts": 3.42, "paper_zeta_1e4": 3.5, "cpp_zc": 1.837, "cpp_fft": 1.819},
    {"config": "VGM-90", "angle_deg": 90, "paper_wn": 2.10, "paper_Ts": 2.99, "paper_zeta_1e4": 3.2, "cpp_zc": 2.094, "cpp_fft": 2.058},
]


def _load_series(csv_path: Path) -> Tuple[np.ndarray, np.ndarray]:
    t: List[float] = []
    x: List[float] = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                ti = float(row["time_s"])
                xi = float(row["flap_pitch_rad"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (math.isfinite(ti) and math.isfinite(xi)):
                continue
            t.append(ti)
            x.append(xi)
    if len(t) < 16:
        raise RuntimeError(f"Insufficient valid samples in {csv_path}")

    order = np.argsort(np.asarray(t))
    tt = np.asarray(t, dtype=float)[order]
    xx = np.asarray(x, dtype=float)[order]
    return tt, xx


def _estimate_wn(csv_path: Path, transient_s: float = 2.0) -> Tuple[float, float]:
    t, x = _load_series(csv_path)

    mask = t >= (t[0] + transient_s)
    t = t[mask]
    x = x[mask]
    if len(t) < 16:
        raise RuntimeError(f"Not enough post-transient samples in {csv_path}")

    x = x - np.mean(x)
    dt = float(np.median(np.diff(t)))
    if dt <= 0.0:
        raise RuntimeError(f"Non-positive dt in {csv_path}")

    freqs = np.fft.rfftfreq(len(x), d=dt)
    amps = np.abs(np.fft.rfft(x))
    if len(amps) > 0:
        amps[0] = 0.0
    k = int(np.argmax(amps))
    wn_fft = float(2.0 * math.pi * freqs[k])

    zc: List[float] = []
    for i in range(1, len(x)):
        if x[i - 1] < 0.0 <= x[i]:
            dx = x[i] - x[i - 1]
            if abs(dx) < 1e-12:
                continue
            alpha = -x[i - 1] / dx
            zc.append(float(t[i - 1] + alpha * (t[i] - t[i - 1])))
    if len(zc) < 2:
        raise RuntimeError(f"Insufficient zero-crossings in {csv_path}")

    periods = np.diff(np.asarray(zc, dtype=float))
    T_med = float(np.median(periods))
    wn_zc = float(2.0 * math.pi / T_med)
    return wn_fft, wn_zc


def compute_rows(repo_root: Path) -> Tuple[List[dict], bool]:
    rows = [dict(r) for r in FALLBACK_ROWS]
    output_dir = repo_root / "output"
    all_found = True

    for row in rows:
        deg = int(row["angle_deg"])
        csv_path = output_dir / f"vgoswec_{deg}_freedecay_results.csv"
        if not csv_path.exists():
            all_found = False
            continue
        try:
            wn_fft, wn_zc = _estimate_wn(csv_path)
            row["cpp_fft"] = wn_fft
            row["cpp_zc"] = wn_zc
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"WARN: {csv_path}: {exc}. Using embedded fallback values.")
            all_found = False

    return rows, all_found


def write_plot(rows: List[dict], out_png: Path) -> None:
    rows = sorted(rows, key=lambda r: int(r["angle_deg"]))
    x = [int(r["angle_deg"]) for r in rows]
    paper = [float(r["paper_wn"]) for r in rows]
    cpp_zc = [float(r["cpp_zc"]) for r in rows]
    cpp_fft = [float(r["cpp_fft"]) for r in rows]

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.plot(x, paper, marker="o", linewidth=2.0, label="Paper Table 2 ω_n")
    ax.plot(x, cpp_zc, marker="s", linewidth=2.0, label="C++ zero-cross ω_n")
    ax.plot(x, cpp_fft, marker="^", linewidth=2.0, label="C++ FFT peak ω_n")

    ax.set_title("VGOSWEC free-decay natural frequency validation")
    ax.set_xlabel("Flap angle [deg]")
    ax.set_ylabel("Natural frequency ω_n [rad/s]")
    ax.set_xticks(x)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def write_csv(rows: List[dict], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "config",
            "angle_deg",
            "paper_wn_rads",
            "paper_Ts_s",
            "paper_zeta_1e4",
            "cpp_zerocross_wn_rads",
            "cpp_fft_wn_rads",
            "zerocross_err_pct",
        ])
        for r in sorted(rows, key=lambda rr: int(rr["angle_deg"])):
            paper = float(r["paper_wn"])
            zc = float(r["cpp_zc"])
            err = (zc - paper) / paper * 100.0
            writer.writerow([
                r["config"],
                int(r["angle_deg"]),
                f"{paper:.3f}",
                f"{float(r['paper_Ts']):.2f}",
                f"{float(r['paper_zeta_1e4']):.1f}",
                f"{zc:.3f}",
                f"{float(r['cpp_fft']):.3f}",
                f"{err:.1f}",
            ])


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    rows, used_measured = compute_rows(repo)

    out_png = repo / "docs" / "img" / "freedecay_validation.png"
    out_csv = repo / "docs" / "freedecay_validation.csv"

    write_plot(rows, out_png)
    write_csv(rows, out_csv)

    if used_measured:
        print("Generated plot/CSV using measured output/vgoswec_*_freedecay_results.csv data.")
    else:
        print("Generated plot/CSV with embedded validated fallback values (missing/partial output CSVs).")

    print(f"Wrote: {out_png}")
    print(f"Wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
