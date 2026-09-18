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
    def test_default_period_grid_matches_committed_27_point_range(self) -> None:
        grid = passive_vs_optpassive_sweep.build_period_grid(
            passive_vs_optpassive_sweep.DEFAULT_PERIOD_STEP
        )

        self.assertEqual(len(grid), 27)
        self.assertEqual(grid[0], 0.5)
        self.assertEqual(grid[-1], 7.0)
        np.testing.assert_array_equal(grid, passive_vs_optpassive_sweep.PERIOD_GRID)

    def test_period_step_point_one_includes_both_endpoints(self) -> None:
        grid = passive_vs_optpassive_sweep.build_period_grid(0.1)

        self.assertEqual(len(grid), 66)
        self.assertEqual(grid[0], 0.5)
        self.assertEqual(grid[-1], 7.0)

    def test_period_step_point_one_sanity_checks_run_arithmetic(self) -> None:
        grid = passive_vs_optpassive_sweep.build_period_grid(0.1)

        self.assertEqual(len(grid), 66)
        self.assertEqual(len(grid) * len(passive_vs_optpassive_sweep.FLAPS) * 2, 660)
        total_simulated_seconds = sum(
            passive_vs_optpassive_sweep.duration_for_period(float(period_s))
            for period_s in grid
        ) * len(passive_vs_optpassive_sweep.FLAPS) * 2
        self.assertAlmostEqual(total_simulated_seconds, 377850.0, places=6)

    def test_period_step_rejects_duplicate_rounded_grid_points(self) -> None:
        with self.assertRaisesRegex(ValueError, "0.01 s rounded grid"):
            passive_vs_optpassive_sweep.build_period_grid(0.005)

    def test_period_step_rejects_grids_that_miss_the_inclusive_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "inclusive 0.5 s to 7.0 s sweep bounds"):
            passive_vs_optpassive_sweep.build_period_grid(0.2)

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

    def test_period_step_s_round_trips_through_efficiency_csv(self) -> None:
        period_grid = passive_vs_optpassive_sweep.build_period_grid(0.1)
        rows = passive_vs_optpassive_sweep._build_csv_rows(
            period_grid=period_grid[:1],
            period_step_s=0.1,
            captures={0.5: 1.0},
            omega=np.array([12.56637061]),
            b55=np.array([3.0]),
            fexc=np.array([4.0]),
            p_opt=np.array([2.0]),
            masked=np.array([False]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "capture.csv"
            passive_vs_optpassive_sweep.write_efficiency_csv(csv_path, rows)
            loaded = passive_vs_optpassive_sweep.load_efficiency_csv(csv_path)

        self.assertEqual(len(loaded), 1)
        self.assertAlmostEqual(loaded[0]["period_step_s"], 0.1)

    def test_default_period_step_s_round_trips_through_efficiency_csv(self) -> None:
        rows = passive_vs_optpassive_sweep._build_csv_rows(
            period_grid=passive_vs_optpassive_sweep.PERIOD_GRID[:1],
            period_step_s=passive_vs_optpassive_sweep.DEFAULT_PERIOD_STEP,
            captures={0.5: 1.0},
            omega=np.array([12.56637061]),
            b55=np.array([3.0]),
            fexc=np.array([4.0]),
            p_opt=np.array([2.0]),
            masked=np.array([False]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "capture.csv"
            passive_vs_optpassive_sweep.write_efficiency_csv(csv_path, rows)
            loaded = passive_vs_optpassive_sweep.load_efficiency_csv(csv_path)

        self.assertEqual(len(loaded), 1)
        self.assertAlmostEqual(
            loaded[0]["period_step_s"], passive_vs_optpassive_sweep.DEFAULT_PERIOD_STEP
        )

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
        self.assertTrue(math.isnan(rows[0]["period_step_s"]))
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
                    [
                        "passive_vs_optpassive_sweep.py",
                        "--repo", str(repo),
                        "--plot-only",
                        "--period-step", "0.005",
                    ],
                ):
                    rc = passive_vs_optpassive_sweep.main()

        self.assertEqual(rc, 0)
        regen.assert_called_once()
        _, passive_csv_map, opt_csv_map = regen.call_args.args
        self.assertEqual(passive_csv_map, {})
        self.assertIn(0, opt_csv_map)


if __name__ == "__main__":
    unittest.main()
