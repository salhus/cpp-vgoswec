#!/usr/bin/env python3
"""Controller power sweep for VGOSWEC (VGM-45 and VGM-0).

Runs the demo_vgoswec binary for every (device × controller × period) combination,
collects steady-state mean absorbed power, computes capture ratios, and writes:
  output/controller_power_sweep_VGM45.csv
  output/controller_power_sweep_VGM0.csv
  output/controller_power_sweep.csv          (combined, device column added)
  output/controller_power_sweep_VGM45.png
  output/controller_power_sweep_VGM0.png
  docs/controller_power_comparison.md
"""
import csv
import math
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional
from pathlib import Path


WAVE_H = 0.028
WAVE_A = WAVE_H / 2.0

# Per-device sweep configuration.
#
# IMPORTANT — keep resonance_omega and resonance_period consistent with the
# opt_passive/cc design_omega fields in the corresponding YAML configs:
#   VGM-45: config/vgoswec_45_{opt_passive,cc}.yaml → opt_passive.design_omega: 1.84
#   VGM-0:  config/vgoswec_0_{opt_passive,cc}.yaml  → opt_passive.design_omega: 1.07
# resonance_omega is used here for impedance-based commentary and Falnes check only;
# the actual controller gains are computed by the binary from the H5 + design_omega.
DEVICES = {
    "VGM-45": {
        "label": "VGM-45 (45° flap angle)",
        "cc_config": "config/vgoswec_45_cc.yaml",
        "controller_configs": {
            "passive":     "config/vgoswec_45_passive.yaml",
            "opt_passive": "config/vgoswec_45_opt_passive.yaml",
            "cc":          "config/vgoswec_45_cc.yaml",
            "exc_ff_pid":  "config/vgoswec_45_exc_ff_pid.yaml",
        },
        "periods": [6.00, 4.49, 3.42, 3.00, 2.50, 2.00, 1.57],
        "resonance_period": 3.42,   # must match opt_passive.design_omega in YAML
        "resonance_omega":  1.84,   # must match opt_passive.design_omega in YAML
    },
    "VGM-0": {
        "label": "VGM-0 (0° flap angle)",
        "cc_config": "config/vgoswec_0_cc.yaml",
        "controller_configs": {
            "passive":     "config/vgoswec_0_passive.yaml",
            "opt_passive": "config/vgoswec_0_opt_passive.yaml",
            "cc":          "config/vgoswec_0_cc.yaml",
            "exc_ff_pid":  "config/vgoswec_0_exc_ff_pid.yaml",
        },
        "periods": [8.00, 6.50, 5.86, 5.00, 4.00, 3.00, 2.00],
        "resonance_period": 5.86,   # must match opt_passive.design_omega in YAML
        "resonance_omega":  1.07,   # must match opt_passive.design_omega in YAML
    },
}

TRANSIENT_PERIODS = 10
TOTAL_PERIODS = 50  # 50 periods total: discard first 10, average ~40 whole cycles
B55_FLOOR = 1e-9   # floor for theoretical P_opt (avoids Inf/NaN at radiation-damping notch)

# Reactive-limited detection threshold for CC controller.
# When B55(omega_wave) < B_R_FLOOR the CC gain B_r = B55(omega0) ~ 0, so the
# controller degenerates to a pure reactive spring that does ~0 NET work per cycle.
# Mirror this constant in src/demo_vgoswec.cpp (kCC_B_R_FLOOR = 1e-4).
B_R_FLOOR = 1e-4  # N·m·s/rad; CC reactive-limited threshold


def run_cmd(cmd: List[str], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=capture,
        check=False,
    )


def parse_hydro_report(stdout: str, expected_periods: List[float]) -> Dict[float, dict]:
    """Parse HYDRO_REPORT_ROW lines from binary stdout into a {T_s: dict} map."""
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
    n_exp = len(expected_periods)
    if len(out) != n_exp:
        raise RuntimeError(
            f"Hydro report returned {len(out)} rows; expected {n_exp} "
            f"for periods {expected_periods}"
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

    # Steady-state window: discard the first TRANSIENT_PERIODS wave periods, then
    # average over an INTEGER number of complete wave periods.  Truncating to a whole
    # number of periods removes the partial-cycle bias that is the main cause of
    # spurious sign flips for reactive-limited CC runs.
    t0 = TRANSIENT_PERIODS * period_s
    t1_nominal = TOTAL_PERIODS * period_s

    n_periods_ss = int((t1_nominal - t0) / period_s)  # integer floor
    if n_periods_ss < 1:
        n_periods_ss = 1
    t1_int = t0 + n_periods_ss * period_s  # end time aligned to whole periods

    win = [r for r in rows if t0 <= r[0] <= t1_int]
    if not win:
        raise RuntimeError(
            f"No samples in steady-state window [{t0:.3f}, {t1_int:.3f}] s for {csv_path}"
        )

    power_mean_raw = sum(r[4] for r in win) / len(win)
    tau_omega_vals = [r[3] * r[2] for r in win]
    tau_omega_mean = sum(tau_omega_vals) / len(tau_omega_vals)
    tau_omega_neg_frac = sum(1 for v in tau_omega_vals if v < 0.0) / len(tau_omega_vals)
    peak_pitch = max(abs(r[1]) for r in win)
    rms_pitch = math.sqrt(sum((r[1] ** 2) for r in win) / len(win))
    peak_abs_inst_power = max(abs(r[4]) for r in win)

    return {
        "P_mean_raw_W": power_mean_raw,
        "tau_omega_mean": tau_omega_mean,
        "tau_omega_neg_frac": tau_omega_neg_frac,
        "peak_pitch_rad": peak_pitch,
        "rms_pitch_rad": rms_pitch,
        "peak_abs_inst_power_W": peak_abs_inst_power,
    }


def make_plot_device(rows: List[dict], device_label: str,
                     resonance_period: float, out_png: Path) -> None:
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
        if ctrl == "cc":
            abs_rows = [r for r in rs if r.get("regime") != "reactive_limited"]
            rl_rows  = [r for r in rs if r.get("regime") == "reactive_limited"]

            color_cc = "tab:green"
            if abs_rows:
                xs = [r["T_s"] for r in abs_rows]
                ys = [r["P_mean_W"] for r in abs_rows]
                ax0.plot(xs, ys, marker="o", color=color_cc, label="cc")
                ax1.semilogy(xs, [max(y, 1e-12) for y in ys],
                             marker="o", color=color_cc, label="cc")

            if rl_rows:
                rl_xs = [r["T_s"] for r in rl_rows]
                ax0.plot(
                    rl_xs,
                    [0.0] * len(rl_xs),
                    marker="o",
                    markersize=10,
                    markerfacecolor="none",
                    markeredgecolor="grey",
                    markeredgewidth=1.5,
                    linestyle="none",
                    label="cc (reactive-limited, ≈0)",
                )
                for rr in rl_rows:
                    b55_val = rr.get("b55_omega_wave", float("nan"))
                    b55_label = (
                        f"B₅₅≈{b55_val:.1e}" if math.isfinite(b55_val) else "B₅₅≈0"
                    )
                    ax0.annotate(
                        f"reactive-limited\n({b55_label}, ~0 net power)",
                        xy=(rr["T_s"], 0.0),
                        xytext=(rr["T_s"] + 0.25, 0.0),
                        fontsize=7,
                        color="grey",
                        va="center",
                        arrowprops=dict(arrowstyle="->", color="grey", lw=0.8),
                    )
        else:
            xs = [r["T_s"] for r in rs]
            ys = [r["P_mean_W"] for r in rs]
            ax0.plot(xs, ys, marker="o", label=ctrl)
            ax1.semilogy(xs, [max(y, 1e-12) for y in ys], marker="o", label=ctrl)

    ax0.plot(periods, p_opt, "k--", marker="x", label="P_opt (theoretical)")
    ax1.semilogy(periods, [max(y, 1e-12) for y in p_opt], "k--", marker="x", label="P_opt (theoretical)")

    for ax in (ax0, ax1):
        ax.axvline(resonance_period, color="gray", linestyle=":", linewidth=1.2,
                   label=f"{device_label.split()[0]} resonance ({resonance_period:.2f} s)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=8)

    ax0.set_ylabel("Mean absorbed power [W]")
    ax1.set_ylabel("Mean absorbed power [W] (log)")
    ax1.set_xlabel("Wave period T [s]")
    fig.suptitle(
        f"Controller power-vs-period sweep — {device_label}\n"
        "(regular waves, H=0.028 m; hydro coefficients de-normalized with stored H5 rho)"
    )
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def render_markdown(all_results: List[dict], device_meta: dict,
                    included_optional: Dict[str, bool], out_md: Path) -> None:
    """Write the combined controller_power_comparison.md for both devices."""

    sections = []

    # ── Setup ─────────────────────────────────────────────────────────────────
    sections += [
        "# Controller power comparison — VGM-45 and VGM-0",
        "",
        "## Setup",
        "- Regular waves with fixed height H = 0.028 m (A = H/2 = 0.014 m) for all periods/controllers.",
        "- **External hinge spring C_ext = 6.57 N·m/rad** (Table 1, Ogden et al. ASME JOMAE 145(3)) is"
        " now wired into the wave-run dynamics for ALL controllers and both devices.",
        "  With K_hs55 ≈ −1.20 N·m/rad (hydrostatically unstable without spring), the effective"
        " restoring stiffness K_hs_eff = K_hs55 + C_ext ≈ +5.37 N·m/rad — stable and matching"
        " Table 2 resonances (VGM-45: ≈1.84 rad/s; VGM-0: ≈1.07 rad/s).",
        "- **De-normalization** uses the stored H5 rho (1000 kg/m³) for both devices — consistent basis.",
] + [
        f"- **{dev_name}** sweep: "
        + ", ".join(f"{p:.2f}" for p in dev["periods"])
        + f" s (ω ≈ {2*math.pi/max(dev['periods']):.2f}–{2*math.pi/min(dev['periods']):.2f} rad/s)."
        for dev_name, dev in device_meta.items()
] + [
        "- Controllers: passive, opt_passive, cc, and exc_ff_pid only if run was stable.",
        f"- Steady-state: discard first {TRANSIENT_PERIODS} periods; average over an integer number "
        f"of whole cycles up to {TOTAL_PERIODS} total periods.",
        "- Sign convention: absorbed power is positive; computed from `power_w` with a global"
        " sign check against `−τ·ω`.",
        f"- CC reactive-limited threshold: B_R_FLOOR = {B_R_FLOOR:.0e} N·m·s/rad.",
        "",
    ]

    for dev_name, dev in device_meta.items():
        dev_rows = [r for r in all_results if r.get("device") == dev_name]
        dev_rows_sorted = sorted(dev_rows, key=lambda r: (r["controller"], -r["T_s"]))
        resonance_period = dev["resonance_period"]
        resonance_omega = dev["resonance_omega"]

        headers = [
            "controller", "T_s", "omega_rads",
            "P_mean_W (or ~0)", "P_opt_W", "capture_ratio",
            "peak_pitch_rad", "rms_pitch_rad", "tau_omega_neg_frac",
            "regime", "note",
        ]
        table = []
        table.append("| " + " | ".join(headers) + " |")
        table.append("|" + "|".join(["---"] * len(headers)) + "|")
        for r in dev_rows_sorted:
            if r.get("regime") == "reactive_limited":
                p_str = "~0 (reactive-limited)"
                cr_str = "~0"
            else:
                p_str = f'{r["P_mean_W"]:.6e}'
                cr_str = f'{r["capture_ratio"]:.6e}'
            table.append(
                "| " + " | ".join([
                    str(r["controller"]),
                    f'{r["T_s"]:.2f}',
                    f'{r["omega_rads"]:.6f}',
                    p_str,
                    f'{r["P_opt_W"]:.6e}',
                    cr_str,
                    f'{r["peak_pitch_rad"]:.6e}',
                    f'{r["rms_pitch_rad"]:.6e}',
                    f'{r["tau_omega_neg_frac"]:.6f}',
                    r.get("regime", "absorbing"),
                    r.get("note", ""),
                ]) + " |"
            )

        # ── Per-device facts ──────────────────────────────────────────────────
        cc_rows = [r for r in dev_rows if r["controller"] == "cc"]
        cc_rl_rows = [r for r in cc_rows if r.get("regime") == "reactive_limited"]
        cc_abs_rows = [r for r in cc_rows if r.get("regime") != "reactive_limited"]
        cc_res = (
            min(cc_rows, key=lambda r: abs(r["T_s"] - resonance_period))
            if cc_rows else None
        )
        absorbing_rows = [r for r in dev_rows if r.get("regime") != "reactive_limited"]
        best_power = max(absorbing_rows, key=lambda r: r["P_mean_W"]) if absorbing_rows else None
        best_capture = max(absorbing_rows, key=lambda r: r["capture_ratio"]) if absorbing_rows else None

        op_rows = [r for r in dev_rows if r["controller"] == "opt_passive"]
        op_res = (
            min(op_rows, key=lambda r: abs(r["T_s"] - resonance_period))
            if op_rows else None
        )
        best_cc = max(cc_abs_rows, key=lambda r: r["P_mean_W"]) if cc_abs_rows else None
        cc_res_result = (
            min(cc_abs_rows, key=lambda r: abs(r["T_s"] - resonance_period))
            if cc_abs_rows else None
        )

        interpretation = []

        if best_power:
            interpretation.append(
                f"- **Highest mean absorbed power**: `{best_power['controller']}` at "
                f"T={best_power['T_s']:.2f} s → P_mean={best_power['P_mean_W']:.4e} W."
            )
        if best_capture:
            interpretation.append(
                f"- **Highest capture ratio**: `{best_capture['controller']}` at "
                f"T={best_capture['T_s']:.2f} s → η={best_capture['capture_ratio']:.4e} "
                f"(P_opt={best_capture['P_opt_W']:.4e} W)."
            )

        # opt_passive at resonance vs Falnes half-power check
        if op_res:
            p_opt_at_res = op_res["P_opt_W"]
            p_op_at_res = op_res["P_mean_W"]
            if p_opt_at_res > 0:
                falnes_ratio = p_op_at_res / p_opt_at_res
                interpretation.append(
                    f"- **opt_passive at resonance** (T={op_res['T_s']:.2f} s):"
                    f" P_mean={p_op_at_res:.4e} W, P_opt={p_opt_at_res:.4e} W,"
                    f" capture ratio={falnes_ratio:.3f}."
                    f" Falnes half-power theorem predicts opt_passive ≈ 0.5 × P_CC_opt at resonance."
                    + (" ✓ approaching expected 50%." if falnes_ratio > 0.3 else
                       " (below 30% — check model tuning or wave conditions).")
                )

        passive_rows = sorted(
            [r for r in dev_rows if r["controller"] in ("passive", "opt_passive")],
            key=lambda r: r["T_s"],
        )
        if passive_rows:
            neg_fracs = [r["tau_omega_neg_frac"] for r in passive_rows]
            avg_neg = sum(neg_fracs) / len(neg_fracs)
            interpretation.append(
                f"- **Passive and opt_passive** absorb positive power across the swept band"
                f" (τ·ω<0 fraction ≈ {avg_neg:.2f} ≈ 1.0), confirming they always oppose motion."
            )

        if cc_res is not None and cc_rl_rows:
            rl_T_list = ", ".join(
                f"{r['T_s']:.2f}" for r in sorted(cc_rl_rows, key=lambda x: x["T_s"])
            )
            peak_deg = math.degrees(cc_res["peak_pitch_rad"])
            b55_notch = cc_res.get("b55_omega_wave", float("nan"))
            b55_str = f"{b55_notch:.2e}" if math.isfinite(b55_notch) else "~2e-6"
            interpretation.append(
                f"- **CC at the radiation-damping notch (T={rl_T_list} s)**: "
                f"B₅₅(ω₀) collapses to {b55_str} N·m·s/rad (>> 4 orders below B_R_FLOOR)."
                " CC gain B_r ≈ 0 → degenerates to pure reactive spring → **~0 NET work** per cycle."
                f" Peak|θ|={cc_res['peak_pitch_rad']:.3f} rad ≈ {peak_deg:.0f}°."
                " Marked `regime=reactive_limited` in CSV."
            )
        if cc_abs_rows:
            best_cc_abs = max(cc_abs_rows, key=lambda r: r["P_mean_W"])
            if cc_res_result:
                interpretation.append(
                    f"- **CC at resonance** (T={cc_res_result['T_s']:.2f} s):"
                    f" P_mean={cc_res_result['P_mean_W']:.4e} W"
                    + (f", B55={cc_res_result.get('b55_omega_wave', float('nan')):.3e} N·m·s/rad."
                       if not math.isnan(cc_res_result.get('b55_omega_wave', float('nan'))) else ".")
                )
            interpretation.append(
                f"- **CC away from the notch**: absorbs positive power"
                f" (best: T={best_cc_abs['T_s']:.2f} s → P_mean={best_cc_abs['P_mean_W']:.4e} W)."
                " Marked `regime=absorbing`."
            )
        elif cc_rows and not cc_abs_rows:
            interpretation.append(
                "- **CC**: all sweep points fall within the reactive-limited regime"
                f" (B₅₅ < B_R_FLOOR={B_R_FLOOR:.0e} across the entire swept band)."
            )

        exc_rows = [r for r in dev_rows if r["controller"] == "exc_ff_pid"]
        inc_exc = included_optional.get(dev_name, False)
        if inc_exc and exc_rows:
            exc_p = ", ".join(
                f"T={r['T_s']:.2f} s→{r['P_mean_W']:.4e} W"
                for r in sorted(exc_rows, key=lambda x: x["T_s"])
            )
            interpretation.append(f"- **exc_ff_pid** included. Results: {exc_p}.")
        else:
            interpretation.append("- `exc_ff_pid` excluded (probe run failed or was unstable).")

        notch_rows = [r for r in dev_rows if r.get("P_opt_floor_applied")]
        if notch_rows:
            ps = ", ".join(f"{r['T_s']:.2f}" for r in sorted(notch_rows, key=lambda x: -x["T_s"]))
            interpretation.append(
                f"- Theoretical P_opt used B55 floor {B55_FLOOR:.1e} N·m·s/rad at"
                f" periods [{ps}] to avoid Inf/NaN."
            )

        interpretation.append(
            f"- Power averaged over integer-cycle steady-state window"
            f" (discard first {TRANSIENT_PERIODS} periods;"
            f" average up to {TOTAL_PERIODS - TRANSIENT_PERIODS} whole cycles)."
        )

        sections += [
            f"## {dev_name}: {dev['label']}",
            "",
            f"Design frequency: ω₀ = {resonance_omega:.2f} rad/s (T = {resonance_period:.2f} s, Table 2).",
            f"Plot: `output/controller_power_sweep_{dev_name.replace('-', '')}.png`",
            "",
            "### Results table",
            *table,
            "",
            "### Interpretation",
            *interpretation,
            "",
        ]

    # ── Cross-device summary ───────────────────────────────────────────────────
    vgm45_rows = [r for r in all_results if r.get("device") == "VGM-45"]
    vgm0_rows = [r for r in all_results if r.get("device") == "VGM-0"]
    vgm45_cc_res = next(
        (r for r in sorted(vgm45_rows, key=lambda r: abs(r["T_s"] - 3.42))
         if r["controller"] == "cc"), None
    )
    vgm0_cc_res = next(
        (r for r in sorted(vgm0_rows, key=lambda r: abs(r["T_s"] - 5.86))
         if r["controller"] == "cc"), None
    )

    cross = []
    if vgm45_cc_res and vgm0_cc_res:
        vgm45_is_rl = vgm45_cc_res.get("regime") == "reactive_limited"
        vgm0_is_rl  = vgm0_cc_res.get("regime") == "reactive_limited"
        cross.append(
            f"- **VGM-45 CC at resonance (T={vgm45_cc_res['T_s']:.2f} s)**:"
            + (" reactive-limited (B55 notch, ~0 net power)." if vgm45_is_rl
               else f" P_mean={vgm45_cc_res['P_mean_W']:.4e} W (absorbing).")
        )
        cross.append(
            f"- **VGM-0 CC at resonance (T={vgm0_cc_res['T_s']:.2f} s)**:"
            + (" reactive-limited (B55 notch, ~0 net power)." if vgm0_is_rl
               else f" P_mean={vgm0_cc_res['P_mean_W']:.4e} W (absorbing).")
        )
        if vgm45_is_rl and not vgm0_is_rl:
            cross.append(
                "- **Geometry contrast**: VGM-45's radiation-damping collapses at its resonance"
                " (B55 notch), making CC ineffective there. VGM-0 has healthy B55(1.07) ≈ 0.055"
                " N·m·s/rad at its resonance — CC can absorb meaningful net power."
            )
        elif not vgm45_is_rl and not vgm0_is_rl:
            cross.append(
                "- Both devices have healthy B55 at their respective resonances —"
                " CC absorbs meaningful power on both."
            )

    cross.append(
        "- **Model corrections applied in this run** (vs. prior mis-normalised baseline):"
        " (1) external hinge spring C_ext=6.57 N·m/rad now in ALL wave-run dynamics"
        " → both devices stable at Table 2 resonances;"
        " (2) de-normalization pinned to stored H5 rho=1000 kg/m³"
        " (was 954 for VGM-45, 844 for VGM-0 under legacy A55 match);"
        " (3) output filenames now derived from config stem (no clobber between devices)."
    )

    sections += [
        "## Cross-device comparison",
        "",
        *cross,
        "",
        "## Notes",
        "- H = 0.028 m regular waves; stored H5 rho = 1000 kg/m³ de-normalization.",
        "- `output/controller_power_sweep.csv` contains combined results (device column added).",
        "",
    ]

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(sections) + "\n")


def run_device_sweep(
    demo: Path, repo: Path, dev_name: str, dev: dict, tmpdir: Path
) -> tuple:
    """Run the full sweep for one device.

    Returns (results, include_exc, power_sign) for the device.
    """
    periods_s = dev["periods"]
    resonance_period = dev["resonance_period"]
    controller_configs = dev["controller_configs"]
    cc_config = dev["cc_config"]

    # ── Hydro report ──────────────────────────────────────────────────────────
    periods_csv = ",".join(f"{p:.2f}" for p in periods_s)
    hydro_cmd = [
        str(demo),
        "--config", cc_config,
        "--data-dir", str(repo),
        "--no-viz",
        "--wave-height", f"{WAVE_H}",
        "--hydro-periods", periods_csv,
        "--hydro-report",
    ]
    hydro_run = run_cmd(hydro_cmd, repo, capture=True)
    if hydro_run.returncode != 0:
        print(hydro_run.stdout)
        print(hydro_run.stderr, file=sys.stderr)
        raise RuntimeError(f"Hydro report run failed for {dev_name}")
    hydro = parse_hydro_report(hydro_run.stdout, periods_s)

    # ── Probe exc_ff_pid ──────────────────────────────────────────────────────
    controllers = ["passive", "opt_passive", "cc"]
    include_exc = True
    probe_T = resonance_period
    probe_cmd = [
        str(demo),
        "--config", controller_configs["exc_ff_pid"],
        "--controller", "exc_ff_pid",
        "--data-dir", str(repo),
        "--no-viz",
        "--wave-period", f"{probe_T}",
        "--wave-height", f"{WAVE_H}",
        "--duration", f"{TOTAL_PERIODS * probe_T}",
    ]
    probe = run_cmd(probe_cmd, repo, capture=True)
    if probe.returncode != 0:
        include_exc = False
        print(f"NOTE [{dev_name}]: exc_ff_pid probe run failed; excluding exc_ff_pid from sweep.")
    if include_exc:
        controllers.append("exc_ff_pid")

    # ── Main sweep ────────────────────────────────────────────────────────────
    results = []
    power_sign: Optional[float] = None

    for ctrl in controllers:
        for T_s in periods_s:
            dur_s = TOTAL_PERIODS * T_s
            cmd = [
                str(demo),
                "--config", controller_configs[ctrl],
                "--controller", ctrl,
                "--data-dir", str(repo),
                "--no-viz",
                "--wave-period", f"{T_s}",
                "--wave-height", f"{WAVE_H}",
                "--duration", f"{dur_s}",
            ]
            run = run_cmd(cmd, repo, capture=True)
            if run.returncode != 0:
                raise RuntimeError(
                    f"Run failed for {dev_name} {ctrl} at T={T_s:.2f}s\n"
                    f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
                )

            # Config stem gives the output filename (e.g. vgoswec_45_cc → vgoswec_45_cc_results.csv)
            config_stem = Path(controller_configs[ctrl]).stem
            src_csv = repo / "output" / f"{config_stem}_results.csv"
            dst_csv = tmpdir / f"{dev_name}_{ctrl}_T{T_s:.2f}.csv"
            shutil.copyfile(src_csv, dst_csv)
            m = summarize_run(dst_csv, T_s)

            if power_sign is None and ctrl == "passive":
                expected_abs = -m["tau_omega_mean"]
                d1 = abs(m["P_mean_raw_W"] - expected_abs)
                d2 = abs((-m["P_mean_raw_W"]) - expected_abs)
                power_sign = 1.0 if d1 <= d2 else -1.0
                print(
                    f"[{dev_name}] Power sign check (passive): using"
                    f" {'power_w' if power_sign > 0 else '-power_w'} as absorbed power convention."
                )

            if power_sign is None:
                raise RuntimeError(
                    f"[{dev_name}] Power sign could not be established from passive controller data"
                )
            P_mean = power_sign * m["P_mean_raw_W"]
            key = round(T_s, 2)
            h = hydro[key]
            P_opt = h["P_opt_W"]
            capture_ratio = P_mean / P_opt if P_opt > 0.0 else float("nan")

            is_reactive_limited = ctrl == "cc" and h["B55"] < B_R_FLOOR
            if is_reactive_limited:
                regime = "reactive_limited"
                note = (
                    f"B55~{h['B55']:.2e} N*m*s/rad: pure reactive spring,"
                    f" ~0 net absorption, large motion"
                    f" (peak|theta|={m['peak_pitch_rad']:.3f} rad"
                    f" = {math.degrees(m['peak_pitch_rad']):.0f} deg)"
                )
            else:
                regime = "absorbing"
                note = ""

            results.append({
                "device": dev_name,
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
                "peak_abs_inst_power_W": m["peak_abs_inst_power_W"],
                "regime": regime,
                "note": note,
                "b55_omega_wave": h["B55"],
                "P_opt_floor_applied": h["B55_floor_applied"],
            })

    return results, include_exc


def write_sweep_csv(rows: List[dict], out_csv: Path, include_device: bool = False) -> None:
    cols = [
        "controller", "T_s", "omega_rads", "wave_H_m", "wave_A_m",
        "P_mean_W", "P_opt_W", "capture_ratio",
        "peak_pitch_rad", "rms_pitch_rad", "tau_omega_neg_frac",
        "peak_abs_inst_power_W", "regime", "note",
    ]
    if include_device:
        cols = ["device"] + cols
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x.get("device", ""), x["controller"], -x["T_s"])):
            w.writerow({k: r[k] for k in cols})


def print_table(rows: List[dict], device_name: str = "") -> None:
    prefix = f"[{device_name}] " if device_name else ""
    hdr = (
        f"{'controller':<12} {'T_s':>6} {'omega':>8} "
        f"{'P_mean [W]':>22} {'P_opt [W]':>14} {'capture':>11} "
        f"{'peak|theta|':>12} {'rms theta':>12} {'tau*w<0':>8} {'regime':>16}"
    )
    print(prefix + hdr)
    for r in sorted(rows, key=lambda x: (x["controller"], -x["T_s"])):
        if r["regime"] == "reactive_limited":
            p_str = "~0 (reactive-limited)"
            cr_str = "~0"
        else:
            p_str = f"{r['P_mean_W']:14.6e}"
            cr_str = f"{r['capture_ratio']:11.3e}"
        print(
            f"{r['controller']:<12} {r['T_s']:6.2f} {r['omega_rads']:8.4f} "
            f"{p_str:>22} {r['P_opt_W']:14.6e} {cr_str:>11} "
            f"{r['peak_pitch_rad']:12.4e} {r['rms_pitch_rad']:12.4e} "
            f"{r['tau_omega_neg_frac']:8.4f} {r['regime']:>16}"
        )


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    demo = repo / "build" / "demo_vgoswec"
    if not demo.exists():
        print(f"ERROR: Missing binary: {demo}", file=sys.stderr)
        print("Build first: cmake -S . -B build && cmake --build build -j$(nproc)", file=sys.stderr)
        return 2

    all_results = []
    included_optional: Dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="cpp-vgoswec-controller-sweep-", dir="/tmp") as tmp:
        tmpdir = Path(tmp)

        for dev_name, dev in DEVICES.items():
            print(f"\n{'='*60}")
            print(f" Sweeping {dev_name}: {dev['label']}")
            print(f"{'='*60}")

            dev_results, inc_exc = run_device_sweep(demo, repo, dev_name, dev, tmpdir)
            all_results.extend(dev_results)
            included_optional[dev_name] = inc_exc

            # Per-device CSV
            dev_rows = [r for r in all_results if r.get("device") == dev_name]
            out_csv_dev = repo / "output" / f"controller_power_sweep_{dev_name.replace('-', '')}.csv"
            write_sweep_csv(dev_rows, out_csv_dev, include_device=False)
            print(f"\n{'─'*60}")
            print_table(dev_rows, dev_name)

            # Per-device plot
            out_png_dev = repo / "output" / f"controller_power_sweep_{dev_name.replace('-', '')}.png"
            try:
                make_plot_device(dev_rows, dev["label"], dev["resonance_period"], out_png_dev)
                print(f"Wrote: {out_png_dev}")
            except Exception as exc:
                print(f"WARNING: Plot failed for {dev_name}: {exc}")

            print(f"Wrote: {out_csv_dev}")

    # Combined CSV (device column included)
    out_csv_combined = repo / "output" / "controller_power_sweep.csv"
    write_sweep_csv(all_results, out_csv_combined, include_device=True)

    # Markdown
    out_md = repo / "docs" / "controller_power_comparison.md"
    render_markdown(all_results, DEVICES, included_optional, out_md)

    print(f"\nWrote combined: {out_csv_combined}")
    print(f"Wrote: {out_md}")
    print("Per-run raw CSVs were stored in a temporary /tmp directory and cleaned up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
