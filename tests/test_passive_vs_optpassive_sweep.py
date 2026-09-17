import csv
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import passive_vs_optpassive_sweep  # noqa: E402


class PassiveOptPassiveSweepTests(unittest.TestCase):
    def test_duration_for_period_uses_150_cycles_plus_ramp(self) -> None:
        self.assertEqual(passive_vs_optpassive_sweep.duration_for_period(0.5), 85.0)
        self.assertEqual(passive_vs_optpassive_sweep.duration_for_period(7.0), 1060.0)

    def test_steady_state_mean_power_uses_final_whole_cycle_window(self) -> None:
        period_s = 0.6
        dt_s = 0.1
        t_end = 15.1
        window_start = t_end - (passive_vs_optpassive_sweep.N_AVG * period_s)
        times = np.arange(0.0, t_end + 1e-12, dt_s)
        power = np.where(
            times >= window_start,
            5.0 + np.sin((2.0 * math.pi * times) / period_s),
            100.0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "results.csv"
            with csv_path.open("w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["time_s", "power_w"])
                writer.writerows(zip(times, power))

            mean_power = passive_vs_optpassive_sweep.steady_state_mean_power(csv_path, period_s)

        self.assertAlmostEqual(mean_power, 5.0, places=12)

    def test_load_efficiency_csv_tolerates_legacy_rows_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "capture.csv"
            with csv_path.open("w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "T_s",
                        "omega_rads",
                        "P_capture_W",
                        "P_opt_W",
                        "B55_Nmsrad",
                        "F_exc_Nm",
                        "eta",
                        "masked",
                    ]
                )
                writer.writerow(["0.50", "12.56637061", "1.0", "2.0", "3.0", "4.0", "0.5", "false"])

            rows = passive_vs_optpassive_sweep.load_efficiency_csv(csv_path)

        self.assertEqual(len(rows), 1)
        self.assertTrue(math.isnan(rows[0]["duration_s"]))
        self.assertTrue(math.isnan(rows[0]["dt_s"]))
        self.assertEqual(rows[0]["n_settle"], 0)
        self.assertEqual(rows[0]["n_avg"], 0)

    def test_plot_only_allows_existing_opt_csvs_without_passive_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            opt_dir = repo / "analysis" / "opt_passive"
            opt_dir.mkdir(parents=True)
            (opt_dir / "capture_efficiency_VGM0.csv").write_text(
                "T_s,omega_rads,P_capture_W,P_opt_W,B55_Nmsrad,F_exc_Nm,eta,masked\n"
                "0.50,12.56637061,1.0,2.0,3.0,4.0,0.5,false\n"
            )
            with mock.patch.object(
                passive_vs_optpassive_sweep, "regenerate_plots_from_csv"
            ) as regen:
                with mock.patch.object(
                    sys,
                    "argv",
                    ["passive_vs_optpassive_sweep.py", "--repo", str(repo), "--plot-only"],
                ):
                    rc = passive_vs_optpassive_sweep.main()

        self.assertEqual(rc, 0)
        regen.assert_called_once()
        _, passive_csv_map, opt_csv_map = regen.call_args.args
        self.assertEqual(passive_csv_map, {})
        self.assertIn(0, opt_csv_map)


if __name__ == "__main__":
    unittest.main()
