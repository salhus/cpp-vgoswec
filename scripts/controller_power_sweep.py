#!/usr/bin/env python3
import csv
import math
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List
from pathlib import Path


WAVE_H = 0.028
WAVE_A = WAVE_H / 2.0
PERIODS_S = [6.00, 4.49, 3.42, 3.00, 2.50, 2.00, 1.57]
TRANSIENT_PERIODS = 10
TOTAL_PERIODS = 40
B55_FLOOR = 1e-9


def run_cmd(cmd: List[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=capture,
        check=False,
    )


def parse_hydro_report(stdout: str) -> Dict[float, dict]:
    out: Dict[float, dict] = {}
    for line in stdout.splitlines():
        if not line.startswith("HYDRO_REPORT_ROW,"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 10:
            raise RuntimeError(f"Unexpected hydro-report row format: {line}")
        t_s = round(float(parts[1]), 2)
        out[t_s] = {
            "omega_rads": float(parts[2]),
            "A55": float(parts[3]),
            "B55": float(parts[4]),
            "Fexc55": float(parts[5]),
            "wave_A_m": float(parts[6]),
            "F_exc": float(parts[7]),
            "P_opt_W": float(parts[8]),
            "B55_floor_applied": int(parts[9]) == 1,
        }
    if len(out) != len(PERIODS_S):
        raise RuntimeError(
            f"Hydro report returned {len(out)} rows; expected {len(PERIODS_S)}"
        )
    return out


def summarize_run(csv_path: Path, period_s: float) -> dict:
    rows = []
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append(
                (
                    float(r["time_s"]),
                    float(r["flap_pitch_rad"]),
                    float(r["flap_pitch_vel_rads"]),
                    float(r["pto_torque_nm"]),
                    float(r["power_w"]),
                )
            )
    if not rows:
        raise RuntimeError(f"No data rows in {csv_path}")

    t0 = TRANSIENT_PERIODS * period_s
    t1 = TOTAL_PERIODS * period_s
    win = [r for r in rows if t0 <= r[0] <= t1]
    if not win:
        raise RuntimeError(
            f"No samples in steady-state window [{t0:.3f}, {t1:.3f}] s for {csv_path}"
        )

    power_mean_raw = sum(r[4] for r in win) / len(win)
    tau_omega_vals = [r[3] * r[2] for r in win]
    tau_omega_mean = sum(tau_omega_vals) / len(tau_omega_vals)
    tau_omega_neg_frac = sum(1 for v in tau_omega_vals if v < 0.0) / len(tau_omega_vals)
    peak_pitch = max(abs(r[1]) for r in win)
    rms_pitch = math.sqrt(sum((r[1] ** 2) for r in win) / len(win))

    return {
        "P_mean_raw_W": power_mean_raw,
        "tau_omega_mean": tau_omega_mean,
        "tau_omega_neg_frac": tau_omega_neg_frac,
        "peak_pitch_rad": peak_pitch,
        "rms_pitch_rad": rms_pitch,
    }


def make_plot(rows: List[dict], out_png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_ctrl: Dict[str, List[dict]] = {}
    for r in rows:
        by_ctrl.setdefault(r["controller"], []).append(r)
    for rs in by_ctrl.values():
        rs.sort(key=lambda x: x["T_s"], reverse=True)

    periods = sorted({r["T_s"] for r in rows}, reverse=True)
    p_opt_by_t = {r["T_s"]: r["P_opt_W"] for r in rows}
    p_opt = [p_opt_by_t[t] for t in periods]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for ctrl, rs in sorted(by_ctrl.items()):
        xs = [r["T_s"] for r in rs]
        ys = [r["P_mean_W"] for r in rs]
        ax0.plot(xs, ys, marker="o", label=ctrl)
        ax1.semilogy(xs, [max(y, 1e-12) for y in ys], marker="o", label=ctrl)

    ax0.plot(periods, p_opt, "k--", marker="x", label="P_opt (theoretical)")
    ax1.semilogy(periods, [max(y, 1e-12) for y in p_opt], "k--", marker="x", label="P_opt (theoretical)")

    for ax in (ax0, ax1):
        ax.axvline(3.42, color="gray", linestyle=":", linewidth=1.2, label="VGM45 resonance (3.42 s)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")

    ax0.set_ylabel("Mean absorbed power [W]")
    ax1.set_ylabel("Mean absorbed power [W] (log)")
    ax1.set_xlabel("Wave period T [s]")
    fig.suptitle(
        "Controller power-vs-period sweep (regular waves, H=0.028 m)\n"
        "Hydro coefficients from de-normalized H5 (BEMIO convention)"
    )
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def render_markdown(rows: List[dict], included_optional: bool, out_md: Path) -> None:
    rows_sorted = sorted(rows, key=lambda r: (r["controller"], -r["T_s"]))
    headers = [
        "controller",
        "T_s",
        "omega_rads",
        "wave_H_m",
        "wave_A_m",
        "P_mean_W",
        "P_opt_W",
        "capture_ratio",
        "peak_pitch_rad",
        "rms_pitch_rad",
        "tau_omega_neg_frac",
    ]
    table = []
    table.append("| " + " | ".join(headers) + " |")
    table.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows_sorted:
        table.append(
            "| "
            + " | ".join(
                [
                    str(r["controller"]),
                    f'{r["T_s"]:.2f}',
                    f'{r["omega_rads"]:.6f}',
                    f'{r["wave_H_m"]:.3f}',
                    f'{r["wave_A_m"]:.3f}',
                    f'{r["P_mean_W"]:.6e}',
                    f'{r["P_opt_W"]:.6e}',
                    f'{r["capture_ratio"]:.6e}',
                    f'{r["peak_pitch_rad"]:.6e}',
                    f'{r["rms_pitch_rad"]:.6e}',
                    f'{r["tau_omega_neg_frac"]:.6f}',
                ]
            )
            + " |"
        )

    cc_rows = [r for r in rows if r["controller"] == "cc"]
    cc_res = min(cc_rows, key=lambda r: abs(r["T_s"] - 3.42)) if cc_rows else None
    best_capture = max(rows, key=lambda r: r["capture_ratio"])
    best_power = max(rows, key=lambda r: r["P_mean_W"])
    notch_rows = [r for r in rows if r.get("P_opt_floor_applied")]

    interpretation = [
        f"- Highest mean absorbed power in this sweep: `{best_power['controller']}` at T={best_power['T_s']:.2f} s with P_mean={best_power['P_mean_W']:.6e} W.",
        f"- Highest capture ratio observed: `{best_capture['controller']}` at T={best_capture['T_s']:.2f} s with capture_ratio={best_capture['capture_ratio']:.6e}.",
    ]
    if cc_res is not None:
        interpretation.append(
            "- At resonance (T=3.42 s), `cc` shows "
            f"peak|pitch|={cc_res['peak_pitch_rad']:.6e} rad and capture_ratio={cc_res['capture_ratio']:.6e}, "
            "consistent with reactive-limited behavior near the radiation-damping notch."
        )
    if notch_rows:
        periods = ", ".join(f"{r['T_s']:.2f}" for r in sorted(notch_rows, key=lambda x: -x["T_s"]))
        interpretation.append(
            f"- Theoretical P_opt used B55 floor {B55_FLOOR:.1e} N·m·s/rad at periods [{periods}] to avoid Inf/NaN at the damping notch."
        )
    interpretation.append(
        f"- `exc_ff_pid` controller {'was included' if included_optional else 'was excluded (did not run cleanly)'} in this sweep."
    )

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(
        "\n".join(
            [
                "# Controller power comparison (ω = 1–4 rad/s)",
                "",
                "## Setup",
                "- Regular waves with fixed height H = 0.028 m (A = H/2 = 0.014 m) for all periods/controllers.",
                "- Period sweep: 6.00, 4.49, 3.42, 3.00, 2.50, 2.00, 1.57 s.",
                "- Controllers: passive, opt_passive, cc, and exc_ff_pid only if run was stable.",
                "- Hydro coefficients from existing de-normalized H5 accessors (BEMIO convention; rho_eff from A55 match).",
                "- Steady-state averaging window: discard first 10 periods, average periods 10–40.",
                "- Sign convention: absorbed power is positive and computed from `power_w` with a global sign check against `-tau*omega`.",
                "",
                "## Results table",
                *table,
                "",
                "## Plot",
                "- `output/controller_power_sweep.png`",
                "",
                "## Interpretation",
                *interpretation,
                "",
            ]
        )
        + "\n"
    )


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    demo = repo / "build" / "demo_vgoswec"
    if not demo.exists():
        print(f"ERROR: Missing binary: {demo}", file=sys.stderr)
        print("Build first: cmake -S . -B build && cmake --build build -j$(nproc)", file=sys.stderr)
        return 2

    controller_configs = {
        "passive": "config/vgoswec_45_passive.yaml",
        "opt_passive": "config/vgoswec_45_opt_passive.yaml",
        "cc": "config/vgoswec_45_cc.yaml",
        "exc_ff_pid": "config/vgoswec_45_exc_ff_pid.yaml",
    }

    hydro_cmd = [
        str(demo),
        "--config",
        controller_configs["cc"],
        "--data-dir",
        str(repo),
        "--no-viz",
        "--wave-height",
        f"{WAVE_H}",
        "--hydro-report",
    ]
    hydro_run = run_cmd(hydro_cmd, repo, capture=True)
    if hydro_run.returncode != 0:
        print(hydro_run.stdout)
        print(hydro_run.stderr, file=sys.stderr)
        raise RuntimeError("Hydro report run failed")
    hydro = parse_hydro_report(hydro_run.stdout)

    controllers = ["passive", "opt_passive", "cc"]
    include_exc = True
    probe_T = 3.42
    probe_cmd = [
        str(demo),
        "--config",
        controller_configs["exc_ff_pid"],
        "--controller",
        "exc_ff_pid",
        "--data-dir",
        str(repo),
        "--no-viz",
        "--wave-period",
        f"{probe_T}",
        "--wave-height",
        f"{WAVE_H}",
        "--duration",
        f"{TOTAL_PERIODS * probe_T}",
    ]
    probe = run_cmd(probe_cmd, repo, capture=True)
    if probe.returncode != 0:
        include_exc = False
        print("NOTE: exc_ff_pid probe run failed; excluding exc_ff_pid from sweep.")
    if include_exc:
        controllers.append("exc_ff_pid")

    tmpdir = Path(tempfile.mkdtemp(prefix="cpp-vgoswec-controller-sweep-", dir="/tmp"))
    results = []
    power_sign = None

    for ctrl in controllers:
        for T_s in PERIODS_S:
            dur_s = TOTAL_PERIODS * T_s
            cmd = [
                str(demo),
                "--config",
                controller_configs[ctrl],
                "--controller",
                ctrl,
                "--data-dir",
                str(repo),
                "--no-viz",
                "--wave-period",
                f"{T_s}",
                "--wave-height",
                f"{WAVE_H}",
                "--duration",
                f"{dur_s}",
            ]
            run = run_cmd(cmd, repo, capture=True)
            if run.returncode != 0:
                raise RuntimeError(
                    f"Run failed for {ctrl} at T={T_s:.2f}s\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
                )
            src_csv = repo / "output" / "vgoswec_45_results.csv"
            dst_csv = tmpdir / f"{ctrl}_T{T_s:.2f}.csv"
            shutil.copyfile(src_csv, dst_csv)
            m = summarize_run(dst_csv, T_s)

            if power_sign is None and ctrl == "passive":
                expected_abs = -m["tau_omega_mean"]
                d1 = abs(m["P_mean_raw_W"] - expected_abs)
                d2 = abs((-m["P_mean_raw_W"]) - expected_abs)
                power_sign = 1.0 if d1 <= d2 else -1.0
                print(
                    f"Power sign check (passive): using {'power_w' if power_sign > 0 else '-power_w'} "
                    "as absorbed power convention."
                )

            if power_sign is None:
                power_sign = 1.0
            P_mean = power_sign * m["P_mean_raw_W"]
            key = round(T_s, 2)
            h = hydro[key]
            P_opt = h["P_opt_W"]
            capture_ratio = P_mean / P_opt if P_opt > 0.0 else float("nan")

            results.append(
                {
                    "controller": ctrl,
                    "T_s": T_s,
                    "omega_rads": (2.0 * math.pi / T_s),
                    "wave_H_m": WAVE_H,
                    "wave_A_m": WAVE_A,
                    "P_mean_W": P_mean,
                    "P_opt_W": P_opt,
                    "capture_ratio": capture_ratio,
                    "peak_pitch_rad": m["peak_pitch_rad"],
                    "rms_pitch_rad": m["rms_pitch_rad"],
                    "tau_omega_neg_frac": m["tau_omega_neg_frac"],
                    "P_opt_floor_applied": h["B55_floor_applied"],
                }
            )

    out_csv = repo / "output" / "controller_power_sweep.csv"
    out_png = repo / "output" / "controller_power_sweep.png"
    out_md = repo / "docs" / "controller_power_comparison.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    cols = [
        "controller",
        "T_s",
        "omega_rads",
        "wave_H_m",
        "wave_A_m",
        "P_mean_W",
        "P_opt_W",
        "capture_ratio",
        "peak_pitch_rad",
        "rms_pitch_rad",
        "tau_omega_neg_frac",
    ]
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in sorted(results, key=lambda x: (x["controller"], -x["T_s"])):
            w.writerow({k: r[k] for k in cols})

    print(
        f"{'controller':<12} {'T_s':>6} {'omega':>10} {'P_mean [W]':>14} {'P_opt [W]':>14} "
        f"{'capture':>11} {'peak|th|':>12} {'rms th':>12} {'tau*w<0':>10}"
    )
    for r in sorted(results, key=lambda x: (x["controller"], -x["T_s"])):
        print(
            f"{r['controller']:<12} {r['T_s']:6.2f} {r['omega_rads']:10.4f} "
            f"{r['P_mean_W']:14.6e} {r['P_opt_W']:14.6e} {r['capture_ratio']:11.3e} "
            f"{r['peak_pitch_rad']:12.4e} {r['rms_pitch_rad']:12.4e} {r['tau_omega_neg_frac']:10.4f}"
        )

    make_plot(results, out_png)
    render_markdown(results, include_exc, out_md)

    print(f"\nWrote: {out_csv}")
    print(f"Wrote: {out_png}")
    print(f"Wrote: {out_md}")
    print(f"Per-run raw CSVs kept in: {tmpdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
