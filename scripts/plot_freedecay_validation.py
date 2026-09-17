#!/usr/bin/env python3
"""Plot free-decay natural-frequency validation across VGOSWEC geometries.

Uses the shared free-decay analysis helpers and writes the same CSV/provenance
summary as ``scripts/freedecay_validation.py``. By default the script reads
existing ``output/vgoswec_*_freedecay_results.csv`` files when present and
falls back to embedded 2026-09-17 campaign values otherwise, with an explicit
warning block. Use ``--strict`` to exit non-zero if any geometry is not backed
by a clean CSV read.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from freedecay_validation import (  # noqa: E402
    analyse,
    print_source_warnings,
    rows_needing_attention,
    write_csv,
)


def write_plot(rows: List[dict], out_png: Path) -> None:
    rows = sorted(rows, key=lambda r: int(r["angle_deg"]))
    x = [int(r["angle_deg"]) for r in rows]
    paper = [float(r["paper_wn_rads"]) for r in rows]
    cpp_zc = [float(r["cpp_zerocross_wn_rads"]) for r in rows]
    cpp_fft = [float(r["cpp_fft_wn_rads"]) for r in rows]

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit non-zero if any geometry uses fallback or stale-post-failure data.",
    )
    args = parser.parse_args()

    rows = analyse(REPO_ROOT, run_sims=False)
    out_png = REPO_ROOT / "docs" / "img" / "freedecay_validation.png"
    out_csv = REPO_ROOT / "docs" / "freedecay_validation.csv"

    print_source_warnings(rows)
    write_plot(rows, out_png)
    write_csv(rows, REPO_ROOT)

    if rows_needing_attention(rows):
        print("Generated plot/CSV with mixed provenance; see warnings above.")
    else:
        print("Generated plot/CSV using output/vgoswec_*_freedecay_results.csv data.")

    print(f"Wrote: {out_png}")
    print(f"Wrote: {out_csv}")

    if args.strict:
        flagged = rows_needing_attention(rows)
        if flagged:
            names = ", ".join(f"{r['config']} ({r['source']})" for r in flagged)
            print(f"ERROR: --strict rejected non-primary provenance rows: {names}")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
