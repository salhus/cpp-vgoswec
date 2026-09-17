import csv
import io
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import freedecay_analysis  # noqa: E402
import freedecay_validation  # noqa: E402
import plot_freedecay_validation  # noqa: E402


ANGLES = [0, 10, 20, 45, 90]


def _write_decay_csv(path: Path, wn: float, zeta_1e4: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    zeta = zeta_1e4 * 1e-4
    t = np.arange(0.0, 200.0 + 0.05, 0.05)
    wd = wn * math.sqrt(max(1.0 - zeta ** 2, 1e-12))
    x = 0.15 * np.exp(-zeta * wn * t) * np.cos(wd * t)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time_s", "flap_pitch_rad"])
        writer.writerows(zip(t, x))


def _sample_rows() -> list[dict]:
    rows = []
    for deg in ANGLES:
        paper = freedecay_analysis.PAPER_TABLE2[deg]
        fig4 = freedecay_analysis.PAPER_FIG4_ZETA_1E4[deg]
        cpp = freedecay_analysis.FALLBACK_CPP_WN[deg]
        zeta = freedecay_analysis.FALLBACK_CPP_ZETA_1E4[deg]
        wec = freedecay_analysis.WECSIM_RAWDATA[deg]
        rows.append(
            {
                "config": f"VGM-{deg}",
                "angle_deg": deg,
                "paper_wn_rads": paper["paper_wn_rads"],
                "paper_Ts_s": paper["paper_Ts_s"],
                "paper_zeta_1e4": paper["paper_zeta_1e4"],
                "paper_fig4_zeta_1e4": fig4,
                "cpp_zerocross_wn_rads": cpp["cpp_zc"],
                "cpp_fft_wn_rads": cpp["cpp_fft"],
                "zerocross_err_pct": (cpp["cpp_zc"] - paper["paper_wn_rads"]) / paper["paper_wn_rads"] * 100.0,
                "cpp_zeta_1e4": zeta,
                "zeta_ratio_cpp_over_table2": zeta / paper["paper_zeta_1e4"],
                "wecsim_fft_interp_wn_rads": wec["wecsim_fft_interp"],
                "wecsim_zerocross_wn_rads": wec["wecsim_zc"],
                "wecsim_fitted_zeta_1e4": wec["wecsim_fit_zeta_1e4"],
                "cpp_vs_wecsim_fft_err_pct": (cpp["cpp_zc"] - wec["wecsim_fft_interp"]) / wec["wecsim_fft_interp"] * 100.0,
                "cpp_vs_wecsim_zc_err_pct": (cpp["cpp_zc"] - wec["wecsim_zc"]) / wec["wecsim_zc"] * 100.0,
                "cpp_vs_wecsim_zeta_err_pct": (zeta - wec["wecsim_fit_zeta_1e4"]) / wec["wecsim_fit_zeta_1e4"] * 100.0,
                "source": "csv",
                "_source": "csv",
            }
        )
    rows[2]["source"] = "fallback"
    rows[2]["_source"] = "fallback"
    return rows


class FreeDecayValidationTests(unittest.TestCase):
    def test_printed_summaries_are_computed_from_rows(self) -> None:
        rows = _sample_rows()
        stream = io.StringIO()
        with redirect_stdout(stream):
            freedecay_validation.print_table(rows)
            freedecay_validation.print_wecsim_table(rows)
        output = stream.getvalue()
        self.assertIn("±0.9%", output)
        self.assertIn("±0.17%", output)
        self.assertIn("~5–13%", output)
        self.assertIn("VGM-20 (fallback)", output)

    def test_write_csv_includes_source_and_wecsim_columns(self) -> None:
        rows = _sample_rows()
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "docs").mkdir()
            freedecay_validation.write_csv(rows, repo)
            out = repo / "docs" / "freedecay_validation.csv"
            with out.open(newline="") as fh:
                reader = csv.DictReader(fh)
                fieldnames = reader.fieldnames or []
                first = next(reader)
        self.assertIn("source", fieldnames)
        self.assertIn("wecsim_fft_interp_wn_rads", fieldnames)
        self.assertIn("wecsim_fitted_zeta_1e4", fieldnames)
        self.assertEqual(first["source"], "csv")

    def test_strict_exits_nonzero_when_any_angle_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "output").mkdir()
            for deg in ANGLES:
                if deg == 20:
                    continue
                cpp = freedecay_analysis.FALLBACK_CPP_WN[deg]
                zeta = freedecay_analysis.FALLBACK_CPP_ZETA_1E4[deg]
                _write_decay_csv(repo / "output" / f"vgoswec_{deg}_freedecay_results.csv", cpp["cpp_zc"], zeta)
            with mock.patch.object(freedecay_validation, "REPO_ROOT", repo):
                with mock.patch.object(sys, "argv", ["freedecay_validation.py", "--strict"]):
                    rc = freedecay_validation.main()
        self.assertEqual(rc, 1)

    def test_strict_is_zero_when_all_angles_read_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "output").mkdir()
            for deg in ANGLES:
                cpp = freedecay_analysis.FALLBACK_CPP_WN[deg]
                zeta = freedecay_analysis.FALLBACK_CPP_ZETA_1E4[deg]
                _write_decay_csv(repo / "output" / f"vgoswec_{deg}_freedecay_results.csv", cpp["cpp_zc"], zeta)
            with mock.patch.object(freedecay_validation, "REPO_ROOT", repo):
                with mock.patch.object(sys, "argv", ["freedecay_validation.py", "--strict"]):
                    rc = freedecay_validation.main()
        self.assertEqual(rc, 0)

    def test_failed_run_provenance_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            with mock.patch.object(freedecay_validation, "_run_simulation", return_value=(False, "boom")):
                rows = freedecay_validation.analyse(repo, run_sims=True)
        self.assertTrue(all(r["source"] == "fallback-after-failed-run" for r in rows))

    def test_plotter_strict_uses_same_provenance_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "docs" / "img").mkdir(parents=True)
            with mock.patch.object(plot_freedecay_validation, "REPO_ROOT", repo):
                with mock.patch.object(sys, "argv", ["plot_freedecay_validation.py", "--strict"]):
                    rc = plot_freedecay_validation.main()
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
