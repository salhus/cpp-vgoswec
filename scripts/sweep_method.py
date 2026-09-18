from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np

DEFAULT_PERIOD_STEP = 0.25
PERIOD_MIN_S = 0.5
PERIOD_MAX_S = 7.0
PERIOD_GRID = np.round(np.arange(PERIOD_MIN_S, PERIOD_MAX_S + 0.01, DEFAULT_PERIOD_STEP), 2)
WAVE_HEIGHT_M = 0.05
WAVE_AMPLITUDE_M = WAVE_HEIGHT_M / 2.0
RAMP_S = 10.0
N_AVG = 20
TIMESTEP_S = 0.01
MASK_B55_THRESHOLD = 1e-4
PROVENANCE_CSV_COLS = ["duration_s", "dt_s", "period_step_s", "n_settle", "n_avg"]
TIME_COLUMN_CANDIDATES = ("time_s", "time", "t_s", "t")


def replace_yaml_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*).*$", re.MULTILINE)
    out, n = pattern.subn(rf"\g<1>{value}", text, count=1)
    if n != 1:
        raise RuntimeError(f"Could not update key '{key}' in scratch config")
    return out


def duration_for_period(period_s: float, n_cycles: int) -> float:
    return RAMP_S + n_cycles * period_s


def build_period_grid(step_s: float) -> np.ndarray:
    if not (step_s > 0.0):
        raise ValueError("period step must be > 0")
    period_grid = np.round(np.arange(PERIOD_MIN_S, PERIOD_MAX_S + 0.01, step_s), 2)
    if period_grid.size == 0:
        raise ValueError("period grid is empty")
    if np.unique(period_grid).size != period_grid.size:
        raise ValueError(
            "period step must be compatible with the 0.01 s rounded grid representation"
        )
    if period_grid[0] != PERIOD_MIN_S or period_grid[-1] != PERIOD_MAX_S:
        raise ValueError("period step must preserve the inclusive 0.5 s to 7.0 s sweep bounds")
    return period_grid


def load_output_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not rows:
        raise RuntimeError(f"No rows in output CSV: {csv_path}")
    if not reader.fieldnames:
        raise RuntimeError("Output CSV is missing a header row")
    return list(reader.fieldnames), rows


def time_column_name(fieldnames: list[str]) -> str:
    for key in TIME_COLUMN_CANDIDATES:
        if key in fieldnames:
            return key
    raise RuntimeError(f"Could not find a time column in output CSV header: {fieldnames}")


def whole_cycle_tail_slice(
    fieldnames: list[str],
    rows: list[dict[str, str]],
    period_s: float,
    n_avg: int = N_AVG,
) -> tuple[slice, float]:
    time_key = time_column_name(fieldnames)
    times = np.array([float(r[time_key]) for r in rows], dtype=float)
    if times.size < 2:
        raise RuntimeError(f"Need at least two output samples to estimate dt: {times.size}")
    dt_s = float(np.median(np.diff(times)))
    if not (dt_s > 0.0):
        raise RuntimeError(f"Invalid non-positive dt inferred from {fieldnames}: {dt_s}")
    n_samples = int(round((n_avg * period_s) / dt_s))
    if n_samples < 10:
        raise RuntimeError(
            f"Steady-state averaging window is undersampled: {n_samples} samples "
            f"over final {n_avg} cycles"
        )
    if n_samples > len(rows):
        raise RuntimeError(
            f"Steady-state averaging window exceeds record length: need {n_samples}, "
            f"have {len(rows)}"
        )
    return slice(len(rows) - n_samples, None), dt_s


def provenance_fields(
    period_s: float,
    period_step_s: float,
    n_settle: int,
    n_avg: int,
    n_cycles: int,
) -> dict[str, str]:
    return {
        "duration_s": f"{duration_for_period(period_s, n_cycles):.8e}",
        "dt_s": f"{TIMESTEP_S:.8e}",
        "period_step_s": f"{period_step_s:.8e}",
        "n_settle": str(n_settle),
        "n_avg": str(n_avg),
    }


def parse_provenance_fields(row: dict[str, str]) -> dict[str, float | int]:
    return {
        "duration_s": float(row["duration_s"]) if row.get("duration_s", "").strip() else float("nan"),
        "dt_s": float(row["dt_s"]) if row.get("dt_s", "").strip() else float("nan"),
        "period_step_s": float(row["period_step_s"]) if row.get("period_step_s", "").strip() else float("nan"),
        "n_settle": int(row["n_settle"]) if row.get("n_settle", "").strip() else 0,
        "n_avg": int(row["n_avg"]) if row.get("n_avg", "").strip() else 0,
    }


def write_efficiency_csv(out_csv: Path, rows: list[dict], fieldnames: list[str]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
