import csv
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import capture_efficiency_sweep  # noqa: E402
import cc_capture_efficiency_sweep  # noqa: E402
import cc_vs_ffpid_comparison  # noqa: E402
import three_regime_comparison  # noqa: E402


class UnifiedSweepMethodTests(unittest.TestCase):
    def test_cc_and_ffpid_duration_for_period_use_280_cycles(self) -> None:
        self.assertEqual(cc_capture_efficiency_sweep.duration_for_period(7.0), 1970.0)
        self.assertEqual(capture_efficiency_sweep.duration_for_period(7.0), 1970.0)

    def test_build_period_grid_matches_shared_default_and_rejects_bad_steps(self) -> None:
        grid_cc = cc_capture_efficiency_sweep.build_period_grid(
            cc_capture_efficiency_sweep.DEFAULT_PERIOD_STEP
        )
        grid_fp = capture_efficiency_sweep.build_period_grid(
            capture_efficiency_sweep.DEFAULT_PERIOD_STEP
        )

        np.testing.assert_array_equal(grid_cc, cc_capture_efficiency_sweep.PERIOD_GRID)
        np.testing.assert_array_equal(grid_fp, capture_efficiency_sweep.PERIOD_GRID)
        self.assertEqual(len(grid_cc), 27)
        self.assertEqual(grid_cc[0], 0.5)
        self.assertEqual(grid_cc[-1], 7.0)

        with self.assertRaisesRegex(ValueError, "0.01 s rounded grid"):
            cc_capture_efficiency_sweep.build_period_grid(0.005)
        with self.assertRaisesRegex(ValueError, "inclusive 0.5 s to 7.0 s sweep bounds"):
            capture_efficiency_sweep.build_period_grid(0.2)

    def test_ffpid_steady_state_mean_power_uses_final_whole_cycles(self) -> None:
        period_s = 0.6
        dt_s = 0.1
        t_end = 15.1
        times = np.arange(0.0, t_end + 1e-12, dt_s)
        power = np.full_like(times, 100.0)
        n_tail = int(round(capture_efficiency_sweep.N_AVG * period_s / dt_s))
        power[-n_tail:] = 5.0 + np.sin((2.0 * math.pi * times[-n_tail:]) / period_s)

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "results.csv"
            with csv_path.open("w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["time_s", "power_w"])
                writer.writerows(zip(times, power))

            mean_power = capture_efficiency_sweep.steady_state_mean_power(csv_path, period_s)

        self.assertEqual(n_tail, 120)
        self.assertAlmostEqual(mean_power, 5.0, places=12)

    def test_cc_steady_state_metrics_use_same_final_whole_cycle_window(self) -> None:
        period_s = 0.6
        dt_s = 0.1
        t_end = 15.1
        times = np.arange(0.0, t_end + 1e-12, dt_s)
        n_tail = int(round(cc_capture_efficiency_sweep.N_AVG * period_s / dt_s))

        power = np.full_like(times, 100.0)
        tau = np.full_like(times, -20.0)
        vel = np.ones_like(times)

        tail_power = 1.5 + np.sin((2.0 * math.pi * times[-n_tail:]) / period_s)
        power[-n_tail:] = tail_power
        tau[-n_tail:-n_tail // 2] = -4.0
        tau[-n_tail // 2:] = 1.0

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "results.csv"
            with csv_path.open("w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["time_s", "power_w", "pto_torque_nm", "flap_pitch_vel_rads"])
                writer.writerows(zip(times, power, tau, vel))

            p_net, p_converted, p_injected = cc_capture_efficiency_sweep.steady_state_metrics(
                csv_path, period_s
            )

        self.assertEqual(n_tail, 120)
        self.assertAlmostEqual(p_net, 1.5, places=12)
        self.assertAlmostEqual(p_converted, 2.0, places=12)
        self.assertAlmostEqual(p_injected, 0.5, places=12)

    def test_ffpid_provenance_round_trip_and_legacy_tolerance(self) -> None:
        rows = capture_efficiency_sweep._build_csv_rows(
            period_grid=capture_efficiency_sweep.PERIOD_GRID[:1],
            period_step_s=0.25,
            captures={0.5: 1.0},
            omega=np.array([12.56637061]),
            b55=np.array([3.0]),
            fexc=np.array([4.0]),
            p_opt=np.array([2.0]),
            masked=np.array([False]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "capture.csv"
            capture_efficiency_sweep.write_efficiency_csv(csv_path, rows)
            loaded = capture_efficiency_sweep.load_efficiency_csv(csv_path)
            self.assertAlmostEqual(loaded[0]["duration_s"], 150.0)
            self.assertAlmostEqual(loaded[0]["dt_s"], 0.01)
            self.assertAlmostEqual(loaded[0]["period_step_s"], 0.25)
            self.assertEqual(loaded[0]["n_settle"], 260)
            self.assertEqual(loaded[0]["n_avg"], 20)

            legacy_path = Path(tmpdir) / "legacy.csv"
            legacy_path.write_text(
                "T_s,omega_rads,P_capture_W,P_opt_W,B55_Nmsrad,F_exc_Nm,eta,masked\n"
                "0.50,12.56637061,1.0,2.0,3.0,4.0,0.5,false\n"
            )
            legacy = capture_efficiency_sweep.load_efficiency_csv(legacy_path)

        self.assertTrue(math.isnan(legacy[0]["duration_s"]))
        self.assertTrue(math.isnan(legacy[0]["dt_s"]))
        self.assertTrue(math.isnan(legacy[0]["period_step_s"]))
        self.assertEqual(legacy[0]["n_settle"], 0)
        self.assertEqual(legacy[0]["n_avg"], 0)

    def test_cc_provenance_round_trip_and_legacy_tolerance(self) -> None:
        rows = cc_capture_efficiency_sweep._build_csv_rows(
            period_grid=cc_capture_efficiency_sweep.PERIOD_GRID[:1],
            period_step_s=0.25,
            captures={0.5: (1.0, 2.0, 0.5)},
            omega=np.array([12.56637061]),
            b55=np.array([3.0]),
            fexc=np.array([4.0]),
            p_opt=np.array([2.0]),
            masked=np.array([False]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "capture.csv"
            cc_capture_efficiency_sweep.write_efficiency_csv(csv_path, rows)
            loaded = cc_capture_efficiency_sweep.load_efficiency_csv(csv_path)
            self.assertFalse(loaded[0]["reactive_cancellation_limited"])
            self.assertAlmostEqual(loaded[0]["duration_s"], 150.0)
            self.assertAlmostEqual(loaded[0]["dt_s"], 0.01)
            self.assertAlmostEqual(loaded[0]["period_step_s"], 0.25)
            self.assertEqual(loaded[0]["n_settle"], 260)
            self.assertEqual(loaded[0]["n_avg"], 20)

            legacy_path = Path(tmpdir) / "legacy.csv"
            legacy_path.write_text(
                "T_s,omega_rads,P_capture_W,P_opt_W,B55_Nmsrad,F_exc_Nm,"
                "P_converted_W,P_injected_W,eta,masked,linear_popt_invalid\n"
                "0.50,12.56637061,1.0,2.0,3.0,4.0,2.0,0.5,0.5,false,false\n"
            )
            legacy = cc_capture_efficiency_sweep.load_efficiency_csv(legacy_path)

        self.assertFalse(legacy[0]["reactive_cancellation_limited"])
        self.assertTrue(math.isnan(legacy[0]["duration_s"]))
        self.assertTrue(math.isnan(legacy[0]["dt_s"]))
        self.assertTrue(math.isnan(legacy[0]["period_step_s"]))
        self.assertEqual(legacy[0]["n_settle"], 0)
        self.assertEqual(legacy[0]["n_avg"], 0)

    def test_reactive_cancellation_limited_boundary(self) -> None:
        self.assertTrue(cc_capture_efficiency_sweep._reactive_cancellation_limited(0.0099, 1.0))
        self.assertFalse(cc_capture_efficiency_sweep._reactive_cancellation_limited(0.01, 1.0))
        self.assertFalse(cc_capture_efficiency_sweep._reactive_cancellation_limited(0.1, 0.0))

    def test_power_visibility_ignores_efficiency_reference_flags(self) -> None:
        row = {
            "P_capture_W": 0.48129077,
            "masked": True,
            "linear_popt_invalid": True,
            "reactive_cancellation_limited": True,
        }
        self.assertTrue(cc_capture_efficiency_sweep._power_valid(row))
        self.assertTrue(cc_vs_ffpid_comparison._power_valid(row))
        self.assertTrue(three_regime_comparison._power_valid(row))

        nan_row = {"P_capture_W": float("nan")}
        self.assertFalse(cc_capture_efficiency_sweep._power_valid(nan_row))
        self.assertFalse(cc_vs_ffpid_comparison._power_valid(nan_row))
        self.assertFalse(three_regime_comparison._power_valid(nan_row))

    def test_three_regime_power_envelope_keeps_reactive_limited_cc_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            cc_dir = repo / "analysis" / "cc"
            op_dir = repo / "analysis" / "opt_passive"
            fp_dir = repo / "analysis" / "passive_guarded"
            cc_dir.mkdir(parents=True)
            op_dir.mkdir(parents=True)
            fp_dir.mkdir(parents=True)

            cc_csv = (
                "T_s,P_capture_W,P_opt_W,eta,masked,linear_popt_invalid,reactive_cancellation_limited\n"
                "1.00,5.0,5.0,,false,false,true\n"
                "1.25,1.0,2.0,0.5,false,false,false\n"
            )
            opt_csv = (
                "T_s,P_capture_W,P_opt_W,B55_Nmsrad,eta,masked\n"
                "1.00,2.0,4.0,1.0,0.5,false\n"
                "1.25,0.8,4.0,1.0,0.2,false\n"
            )
            ff_csv = (
                "T_s,P_capture_W,P_opt_W,eta,masked\n"
                "1.00,1.5,3.0,0.5,false\n"
                "1.25,0.7,3.5,0.2,false\n"
            )

            for angle in three_regime_comparison.FLAP_ANGLES:
                (cc_dir / f"capture_efficiency_VGM{angle}.csv").write_text(cc_csv)
                (op_dir / f"capture_efficiency_VGM{angle}.csv").write_text(opt_csv)
                (fp_dir / f"capture_efficiency_VGM{angle}.csv").write_text(ff_csv)

            cc_map = {
                angle: cc_dir / f"capture_efficiency_VGM{angle}.csv"
                for angle in three_regime_comparison.FLAP_ANGLES
            }
            op_map = {
                angle: op_dir / f"capture_efficiency_VGM{angle}.csv"
                for angle in three_regime_comparison.FLAP_ANGLES
            }
            fp_map = {
                angle: fp_dir / f"capture_efficiency_VGM{angle}.csv"
                for angle in three_regime_comparison.FLAP_ANGLES
            }

            hull = three_regime_comparison._build_envelope(cc_map, op_map, fp_map)
            eff_hull = three_regime_comparison._build_efficiency_envelope(
                cc_map, op_map, fp_map
            )

        power_by_t = {row["T_s"]: row for row in hull}
        eff_by_t = {row["T_s"]: row for row in eff_hull}
        self.assertEqual(power_by_t[1.0]["controller"], "CC")
        self.assertEqual(power_by_t[1.0]["P_max_W"], 5.0)
        self.assertEqual(eff_by_t[1.0]["controller"], "opt_passive")
        self.assertAlmostEqual(eff_by_t[1.0]["eta_max"], 0.5)
        self.assertEqual(power_by_t[1.25]["controller"], "CC")

    def test_three_regime_power_envelope_keeps_masked_finite_ffpid_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            cc_dir = repo / "analysis" / "cc"
            op_dir = repo / "analysis" / "opt_passive"
            fp_dir = repo / "analysis" / "passive_guarded"
            cc_dir.mkdir(parents=True)
            op_dir.mkdir(parents=True)
            fp_dir.mkdir(parents=True)

            cc_csv = (
                "T_s,P_capture_W,P_opt_W,eta,masked,linear_popt_invalid,reactive_cancellation_limited\n"
                "4.50,0.30,1.0,0.3,false,false,false\n"
            )
            opt_csv = (
                "T_s,P_capture_W,P_opt_W,B55_Nmsrad,eta,masked\n"
                "4.50,0.35,1.0,1.0,0.35,false\n"
            )
            ff_csv = (
                "T_s,P_capture_W,P_opt_W,eta,masked,linear_popt_invalid,reactive_cancellation_limited\n"
                "4.50,0.48129077,,,true,true,false\n"
            )

            for angle in three_regime_comparison.FLAP_ANGLES:
                (cc_dir / f"capture_efficiency_VGM{angle}.csv").write_text(cc_csv)
                (op_dir / f"capture_efficiency_VGM{angle}.csv").write_text(opt_csv)
                (fp_dir / f"capture_efficiency_VGM{angle}.csv").write_text(ff_csv)

            cc_map = {
                angle: cc_dir / f"capture_efficiency_VGM{angle}.csv"
                for angle in three_regime_comparison.FLAP_ANGLES
            }
            op_map = {
                angle: op_dir / f"capture_efficiency_VGM{angle}.csv"
                for angle in three_regime_comparison.FLAP_ANGLES
            }
            fp_map = {
                angle: fp_dir / f"capture_efficiency_VGM{angle}.csv"
                for angle in three_regime_comparison.FLAP_ANGLES
            }

            hull = three_regime_comparison._build_envelope(cc_map, op_map, fp_map)
            eff_hull = three_regime_comparison._build_efficiency_envelope(
                cc_map, op_map, fp_map
            )

        power_row = {row["T_s"]: row for row in hull}[4.5]
        eff_row = {row["T_s"]: row for row in eff_hull}[4.5]
        self.assertEqual(power_row["controller"], "ff+PID")
        self.assertEqual(power_row["flap_angle"], 0)
        self.assertAlmostEqual(power_row["P_max_W"], 0.48129077)
        self.assertEqual(eff_row["controller"], "opt_passive")


if __name__ == "__main__":
    unittest.main()
