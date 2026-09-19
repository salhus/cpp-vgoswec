#!/usr/bin/env python3
"""Plot passive vs opt_passive stage figures from committed CSVs."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from passive_vs_optpassive_sweep import FLAPS, JOURNAL_STYLE, load_efficiency_csv


def _load_resonance_periods(csv_path: Path) -> dict[int, float]:
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "angle_deg" not in reader.fieldnames or "cpp_zerocross_wn_rads" not in reader.fieldnames:
            raise RuntimeError(
                f"Expected columns 'angle_deg' and 'cpp_zerocross_wn_rads' in {csv_path}"
            )
        periods: dict[int, float] = {}
        for row in reader:
            wn = float(row["cpp_zerocross_wn_rads"])
            periods[int(row["angle_deg"])] = (2.0 * math.pi) / wn
    if not periods:
        raise RuntimeError(f"No resonance rows found in {csv_path}")
    return periods


def _csv_map(repo: Path, subdir: str) -> dict[int, Path]:
    return {
        angle: repo / "analysis" / subdir / f"capture_efficiency_VGM{angle}.csv"
        for angle in FLAPS
    }


def _style_axes(ax) -> None:
    ax.grid(True, which="major", linestyle="--", alpha=0.5)
    ax.grid(True, which="minor", linestyle=":", alpha=0.35)
    ax.minorticks_on()
    ax.set_axisbelow(True)


def _paired_capture_arrays(
    passive_csv: Path,
    opt_csv: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    passive_rows = load_efficiency_csv(passive_csv)
    opt_rows = load_efficiency_csv(opt_csv)
    t_passive = np.array([row["T_s"] for row in passive_rows], dtype=float)
    t_opt = np.array([row["T_s"] for row in opt_rows], dtype=float)
    if t_passive.shape != t_opt.shape or not np.array_equal(t_passive, t_opt):
        raise RuntimeError(
            f"Mismatched T_s grids between {passive_csv.name} and {opt_csv.name}"
        )
    p_passive = np.array([row["P_capture_W"] for row in passive_rows], dtype=float)
    p_opt = np.array([row["P_capture_W"] for row in opt_rows], dtype=float)
    return t_passive, p_passive, p_opt


def plot_per_flap(
    passive_map: dict[int, Path],
    opt_map: dict[int, Path],
    t_res: dict[int, float],
    out_png: Path,
) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(11.0, 6.5), sharex=True, sharey=True)
    axes_flat = axes.flatten()

    for idx, angle in enumerate(sorted(FLAPS)):
        ax = axes_flat[idx]
        t_values, p_passive, p_opt = _paired_capture_arrays(passive_map[angle], opt_map[angle])

        ax.plot(t_values, p_passive, linestyle="--", linewidth=1.8, color="tab:blue", label="passive")
        ax.plot(t_values, p_opt, linestyle="-", linewidth=1.8, color="tab:orange", label="opt_passive")
        ax.axvline(t_res[angle], linestyle=":", linewidth=1.4, color="0.25", label="$T_{res}$")
        ax.set_title(FLAPS[angle]["label"])
        _style_axes(ax)

    axes_flat[0].legend(loc="best", fontsize=8)
    for ax in axes[1, :]:
        ax.set_xlabel("Wave period $T$ [s]")
    for ax in axes[:, 0]:
        ax.set_ylabel("$P_{capture}$ [W]")
    axes_flat[-1].axis("off")

    fig.suptitle("Passive vs opt_passive capture power by flap")
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_all_flaps(opt_map: dict[int, Path], t_res: dict[int, float], out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    colors = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAPS)))

    for color, angle in zip(colors, sorted(FLAPS)):
        rows = load_efficiency_csv(opt_map[angle])
        t = np.array([row["T_s"] for row in rows], dtype=float)
        p = np.array([row["P_capture_W"] for row in rows], dtype=float)
        ax.plot(t, p, linewidth=1.9, color=color, label=FLAPS[angle]["label"])
        ax.axvline(t_res[angle], linestyle=":", linewidth=1.0, color=color, alpha=0.9)

    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel("$P_{capture}$ [W]")
    ax.set_title("opt_passive capture power across all flaps")
    _style_axes(ax)
    ax.legend(loc="best", fontsize=8, ncol=2)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def plot_stage_gain(passive_map: dict[int, Path], opt_map: dict[int, Path], out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    colors = plt.cm.viridis(np.linspace(0.15, 0.9, len(FLAPS)))

    for color, angle in zip(colors, sorted(FLAPS)):
        t, p_passive, p_opt = _paired_capture_arrays(passive_map[angle], opt_map[angle])
        ratio = np.divide(
            p_opt,
            p_passive,
            out=np.full_like(p_opt, np.nan, dtype=float),
            where=np.isfinite(p_opt) & np.isfinite(p_passive) & (p_passive > 0.0),
        )
        valid = np.isfinite(ratio) & (ratio > 0.0)
        ax.plot(t[valid], ratio[valid], linewidth=1.8, color=color, label=FLAPS[angle]["label"])

    ax.axhline(1.0, linestyle="--", linewidth=1.2, color="0.2")
    ax.set_xlabel("Wave period $T$ [s]")
    ax.set_ylabel(r"$P_{\mathrm{opt\,passive}} / P_{\mathrm{passive}}$ [-]")
    ax.set_title("opt_passive stage gain over passive")
    ax.set_yscale("log")
    _style_axes(ax)
    ax.legend(loc="best", fontsize=8, ncol=2)

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    print(f"[ok] wrote {out_png}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: parent of scripts/)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plt.rcParams.update(JOURNAL_STYLE)
    repo = Path(args.repo).resolve()

    passive_map = _csv_map(repo, "passive")
    opt_map = _csv_map(repo, "opt_passive")
    missing = [path for path in [*passive_map.values(), *opt_map.values()] if not path.exists()]
    if missing:
        print(f"ERROR: Missing capture-efficiency CSVs, first missing file: {missing[0]}")
        return 2

    t_res = _load_resonance_periods(repo / "docs" / "freedecay_validation.csv")
    missing_res = [angle for angle in FLAPS if angle not in t_res]
    if missing_res:
        print(f"ERROR: Missing resonance rows for flap angles: {missing_res}")
        return 2
    out_dir = repo / "docs" / "img"
    plot_per_flap(passive_map, opt_map, t_res, out_dir / "opt_passive_stage_per_flap.png")
    plot_all_flaps(opt_map, t_res, out_dir / "opt_passive_stage_all_flaps.png")
    plot_stage_gain(passive_map, opt_map, out_dir / "opt_passive_stage_gain.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
