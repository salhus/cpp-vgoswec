#!/usr/bin/env python3
"""Re-tabulate hydro-derived capture-efficiency columns without re-running sims."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from passive_vs_optpassive_sweep import FLAPS, popt_curve_from_h5

TARGET_COLUMNS = ("B55_Nmsrad", "F_exc_Nm", "P_opt_W", "masked", "eta")
CSV_GROUPS = (("passive", "analysis/passive"), ("opt_passive", "analysis/opt_passive"))


def _format_float(value: float) -> str:
    return f"{value:.8e}"


def _load_csv_exact(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not reader.fieldnames:
        raise RuntimeError(f"CSV is missing a header row: {csv_path}")
    if not rows:
        raise RuntimeError(f"CSV has no rows: {csv_path}")
    return list(reader.fieldnames), rows


def _retabulate_rows(rows: list[dict[str, str]], h5_path: Path) -> list[dict[str, str]]:
    periods_s = np.array([float(row["T_s"]) for row in rows], dtype=float)
    _, b55, fexc, p_opt, masked = popt_curve_from_h5(h5_path, periods_s)

    updated_rows: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        updated = dict(row)
        updated["B55_Nmsrad"] = _format_float(float(b55[idx]))
        updated["F_exc_Nm"] = _format_float(float(fexc[idx]))
        updated["masked"] = "true" if bool(masked[idx]) else "false"
        if bool(masked[idx]):
            updated["P_opt_W"] = ""
            updated["eta"] = ""
        else:
            updated["P_opt_W"] = _format_float(float(p_opt[idx]))
            p_capture_text = row.get("P_capture_W", "").strip()
            if p_capture_text:
                p_capture = float(p_capture_text)
                updated["eta"] = _format_float(p_capture / float(p_opt[idx]))
            else:
                updated["eta"] = ""
        updated_rows.append(updated)
    return updated_rows


def _write_csv_exact(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _masked_summary(before_rows: list[dict[str, str]], after_rows: list[dict[str, str]]) -> tuple[int, int, int]:
    before = [str(row.get("masked", "false")).strip().lower() == "true" for row in before_rows]
    after = [str(row.get("masked", "false")).strip().lower() == "true" for row in after_rows]
    changed = sum(1 for b, a in zip(before, after) if b != a)
    return sum(before), sum(after), changed


def retabulate_csv(csv_path: Path, h5_path: Path, *, write: bool) -> tuple[int, int, int]:
    fieldnames, rows = _load_csv_exact(csv_path)
    missing = [column for column in TARGET_COLUMNS if column not in fieldnames]
    if missing:
        raise RuntimeError(f"CSV missing required columns {missing}: {csv_path}")

    updated_rows = _retabulate_rows(rows, h5_path)
    summary = _masked_summary(rows, updated_rows)
    if write:
        _write_csv_exact(csv_path, fieldnames, updated_rows)
    return summary


def iter_targets(repo: Path):
    for angle, meta in sorted(FLAPS.items()):
        h5_path = repo / meta["h5"]
        for label, rel_dir in CSV_GROUPS:
            csv_path = repo / rel_dir / f"capture_efficiency_VGM{angle}.csv"
            yield label, angle, csv_path, h5_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print masked-change summary without writing CSVs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    saw_target = False

    for label, angle, csv_path, h5_path in iter_targets(repo):
        if not csv_path.exists():
            print(f"[skip] {label} VGM-{angle}: missing CSV {csv_path}")
            continue
        if not h5_path.exists():
            print(f"[skip] {label} VGM-{angle}: missing H5 {h5_path}")
            continue
        saw_target = True
        masked_before, masked_after, changed = retabulate_csv(csv_path, h5_path, write=not args.dry_run)
        verb = "would update" if args.dry_run else "updated"
        print(
            f"[{verb}] {label} VGM-{angle}: masked {masked_before} -> {masked_after} "
            f"({changed} rows changed)"
        )

    if not saw_target:
        print("ERROR: No target CSV/H5 pairs found")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
