#!/usr/bin/env python3
"""Re-tabulate hydro-derived capture-efficiency columns without re-running sims.

Covers all four committed analysis trees:
  - analysis/passive
  - analysis/opt_passive
  - analysis/cc
  - analysis/passive_guarded
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from passive_vs_optpassive_sweep import FLAPS, popt_curve_from_h5

TARGET_COLUMNS = ("B55_Nmsrad", "F_exc_Nm", "P_opt_W", "masked", "eta", "linear_popt_invalid")
REQUIRED_COLUMNS = ("T_s", "P_capture_W", "B55_Nmsrad", "F_exc_Nm", "P_opt_W", "masked", "eta")
CC_REQUIRED_COLUMNS = ("linear_popt_invalid",)
CSV_GROUPS = (
    ("passive", "analysis/passive"),
    ("opt_passive", "analysis/opt_passive"),
    ("cc", "analysis/cc"),
    ("passive_guarded", "analysis/passive_guarded"),
)
ETA_GT1_TOL = 1e-6


def _format_float(value: float) -> str:
    return f"{value:.8e}"


def _load_csv_from_text(text: str, source: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not reader.fieldnames:
        raise RuntimeError(f"CSV is missing a header row: {source}")
    if not rows:
        raise RuntimeError(f"CSV has no rows: {source}")
    return list(reader.fieldnames), rows


def _load_csv_exact(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    return _load_csv_from_text(csv_path.read_text(), str(csv_path))


def _ensure_linear_popt_column(
    fieldnames: list[str], rows: list[dict[str, str]]
) -> tuple[list[str], list[dict[str, str]]]:
    if "linear_popt_invalid" in fieldnames or "reactive_cancellation_limited" not in fieldnames:
        return fieldnames, rows
    insert_at = fieldnames.index("reactive_cancellation_limited")
    updated_fieldnames = list(fieldnames)
    updated_fieldnames.insert(insert_at, "linear_popt_invalid")
    updated_rows = [dict(row, linear_popt_invalid="false") for row in rows]
    return updated_fieldnames, updated_rows


def _retabulate_rows(rows: list[dict[str, str]], h5_path: Path) -> list[dict[str, str]]:
    periods_s = np.array([float(row["T_s"]) for row in rows], dtype=float)
    _, b55, fexc, p_opt, masked = popt_curve_from_h5(h5_path, periods_s)

    updated_rows: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        updated = dict(row)
        updated["B55_Nmsrad"] = _format_float(float(b55[idx]))
        updated["F_exc_Nm"] = _format_float(float(fexc[idx]))
        updated["masked"] = "true" if bool(masked[idx]) else "false"
        linear_popt_invalid = False
        if bool(masked[idx]):
            updated["P_opt_W"] = ""
            updated["eta"] = ""
        else:
            updated["P_opt_W"] = _format_float(float(p_opt[idx]))
            p_capture_text = row.get("P_capture_W", "").strip()
            if p_capture_text:
                p_capture = float(p_capture_text)
                if np.isfinite(p_capture) and np.isfinite(p_opt[idx]) and float(p_opt[idx]) > 0.0:
                    eta = p_capture / float(p_opt[idx])
                    updated["eta"] = _format_float(eta)
                    reactive_cancellation_limited = (
                        str(row.get("reactive_cancellation_limited", "false")).strip().lower() == "true"
                    )
                    if not reactive_cancellation_limited and eta > (1.0 + ETA_GT1_TOL):
                        linear_popt_invalid = True
                else:
                    updated["eta"] = ""
            else:
                updated["eta"] = ""
        if "linear_popt_invalid" in updated:
            updated["linear_popt_invalid"] = "true" if linear_popt_invalid else "false"
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


def _count_eta_gt1_rows(rows: list[dict[str, str]], *, tol: float = ETA_GT1_TOL) -> int:
    count = 0
    for row in rows:
        eta_text = str(row.get("eta", "")).strip()
        if eta_text and float(eta_text) > 1.0 + tol:
            count += 1
    return count


def _non_target_differences(
    before_fieldnames: list[str],
    before_rows: list[dict[str, str]],
    after_fieldnames: list[str],
    after_rows: list[dict[str, str]],
) -> list[str]:
    problems: list[str] = []
    if before_fieldnames != after_fieldnames:
        problems.append("header fieldnames changed")
        return problems
    if len(before_rows) != len(after_rows):
        problems.append(f"row count changed: {len(before_rows)} -> {len(after_rows)}")
        return problems

    checked_columns = [name for name in before_fieldnames if name not in TARGET_COLUMNS]
    for row_idx, (before, after) in enumerate(zip(before_rows, after_rows), start=2):
        for column in checked_columns:
            if before.get(column, "") != after.get(column, ""):
                problems.append(
                    f"line {row_idx} column {column!r} changed: "
                    f"{before.get(column, '')!r} -> {after.get(column, '')!r}"
                )
    return problems


def _non_target_digest(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    checked_columns = [name for name in fieldnames if name not in TARGET_COLUMNS]
    digest = hashlib.sha256()
    for row in rows:
        for column in checked_columns:
            digest.update(column.encode("utf-8"))
            digest.update(b"=")
            digest.update(str(row.get(column, "")).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def verify_targets(targets: list[dict[str, object]], *, strict_eta: bool = False) -> int:
    eta_counts = {label: 0 for label, _ in CSV_GROUPS}
    verify_failed = False

    for target in targets:
        label = str(target["label"])
        angle = int(target["angle"])
        before_fieldnames = list(target["fieldnames"])
        before_rows = list(target["before_rows"])
        after_rows = list(target["after_rows"])
        eta_counts[label] += _count_eta_gt1_rows(after_rows)
        problems = _non_target_differences(before_fieldnames, before_rows, before_fieldnames, after_rows)
        if problems:
            verify_failed = True
            print(f"[verify] {label} VGM-{angle}: NON-TARGET COLUMN DRIFT DETECTED")
            for problem in problems[:5]:
                print(f"[verify]   - {problem}")
            if len(problems) > 5:
                print(f"[verify]   - ... {len(problems) - 5} more")
        else:
            checked = sum(1 for name in before_fieldnames if name not in TARGET_COLUMNS)
            before_hash = _non_target_digest(before_fieldnames, before_rows)
            after_hash = _non_target_digest(before_fieldnames, after_rows)
            print(
                f"[verify] {label} VGM-{angle}: non-target columns unchanged "
                f"({checked} columns, sha256 {before_hash[:12]} == {after_hash[:12]})"
            )

    print(f"[verify] eta > 1 + {ETA_GT1_TOL:g} counts by tree:")
    for label, _ in CSV_GROUPS:
        count = eta_counts[label]
        print(f"[verify]   {label}: {count}")
        if count > 0:
            print(
                "[verify]     note: rows above unity are reported as findings and are not "
                "silently masked by this script"
            )

    eta_findings = any(count > 0 for count in eta_counts.values())
    if eta_findings:
        if strict_eta:
            print("[verify] FAIL: at least one tree still contains eta > 1 + tolerance findings")
        else:
            print("[verify] note: eta > 1 findings are reported but do not fail verification by default")
    return 1 if (verify_failed or (strict_eta and eta_findings)) else 0


def _retabulate_csv_contents(
    csv_path: Path, h5_path: Path
) -> tuple[list[str], list[dict[str, str]], list[dict[str, str]]]:
    fieldnames, rows = _load_csv_exact(csv_path)
    fieldnames, rows = _ensure_linear_popt_column(fieldnames, rows)
    required_columns = REQUIRED_COLUMNS
    if "reactive_cancellation_limited" in fieldnames:
        required_columns = (*required_columns, *CC_REQUIRED_COLUMNS)
    missing = [column for column in required_columns if column not in fieldnames]
    if missing:
        raise RuntimeError(f"CSV missing required columns {missing}: {csv_path}")
    updated_rows = _retabulate_rows(rows, h5_path)
    return fieldnames, rows, updated_rows


def retabulate_csv(csv_path: Path, h5_path: Path, *, write: bool) -> tuple[int, int, int]:
    fieldnames, rows, updated_rows = _retabulate_csv_contents(csv_path, h5_path)
    summary = _masked_summary(rows, updated_rows)
    if write and updated_rows != rows:
        _write_csv_exact(csv_path, fieldnames, updated_rows)
    return summary


def iter_targets(repo: Path) -> Iterator[tuple[str, int, Path, Path]]:
    """Yield (label, flap angle, CSV path, hinge-H5 path) retabulation targets."""
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
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After processing, report eta>1 counts by tree and confirm non-target columns "
        "match HEAD for every touched CSV",
    )
    parser.add_argument(
        "--strict-eta",
        action="store_true",
        help="With --verify, return a non-zero exit code if any eta > 1 + tolerance findings remain",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    saw_target = False
    processed_targets: list[dict[str, object]] = []

    for label, angle, csv_path, h5_path in iter_targets(repo):
        if not csv_path.exists():
            print(f"[skip] {label} VGM-{angle}: missing CSV {csv_path}")
            continue
        if not h5_path.exists():
            print(f"[skip] {label} VGM-{angle}: missing H5 {h5_path}")
            continue
        saw_target = True
        fieldnames, before_rows, after_rows = _retabulate_csv_contents(csv_path, h5_path)
        processed_targets.append(
            {
                "label": label,
                "angle": angle,
                "fieldnames": fieldnames,
                "before_rows": before_rows,
                "after_rows": after_rows,
            }
        )
        masked_before, masked_after, changed = _masked_summary(before_rows, after_rows)
        if not args.dry_run and after_rows != before_rows:
            _write_csv_exact(csv_path, fieldnames, after_rows)
        verb = "would update" if args.dry_run else "updated"
        print(
            f"[{verb}] {label} VGM-{angle}: masked {masked_before} -> {masked_after} "
            f"({changed} rows changed)"
        )

    if not saw_target:
        print("ERROR: No target CSV/H5 pairs found")
        return 2
    if args.verify:
        return verify_targets(processed_targets, strict_eta=args.strict_eta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
