import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import passive_vs_optpassive_sweep  # noqa: E402
import retabulate_hydro_columns  # noqa: E402


class HydroRetabulationTests(unittest.TestCase):
    def test_iter_targets_covers_all_four_analysis_trees(self) -> None:
        labels = {label for label, _, _, _ in retabulate_hydro_columns.iter_targets(REPO_ROOT)}
        self.assertEqual(labels, {"passive", "opt_passive", "cc", "passive_guarded"})

    def test_popt_curve_from_h5_clamps_b55_non_negative_for_all_hinged_flaps(self) -> None:
        for angle, meta in passive_vs_optpassive_sweep.FLAPS.items():
            with self.subTest(angle=angle):
                _, b55, _, _, _ = passive_vs_optpassive_sweep.popt_curve_from_h5(
                    REPO_ROOT / meta["h5"],
                    passive_vs_optpassive_sweep.PERIOD_GRID,
                )
                self.assertGreaterEqual(float(np.min(b55)), 0.0)

    def test_hinge_basis_mask_differs_from_cg_basis_for_vgm45(self) -> None:
        periods_s = np.array([1.75, 3.5], dtype=float)
        _, b55_hinge, _, _, masked_hinge = passive_vs_optpassive_sweep.popt_curve_from_h5(
            REPO_ROOT / passive_vs_optpassive_sweep.FLAPS[45]["h5"],
            periods_s,
        )
        _, b55_cg, _, _, masked_cg = passive_vs_optpassive_sweep.popt_curve_from_h5(
            REPO_ROOT / "hydroData" / "vgoswec_45.h5",
            periods_s,
        )

        self.assertFalse(bool(masked_hinge[0]))
        self.assertTrue(bool(masked_cg[0]))
        self.assertNotEqual(bool(masked_hinge[0]), bool(masked_cg[0]))
        self.assertGreater(float(b55_hinge[0]), passive_vs_optpassive_sweep.MASK_B55_THRESHOLD)
        self.assertLessEqual(float(b55_cg[0]), passive_vs_optpassive_sweep.MASK_B55_THRESHOLD)
        self.assertGreater(float(b55_hinge[1]), float(b55_cg[1]))

    def test_retabulation_preserves_p_capture_column_text(self) -> None:
        source_csv = REPO_ROOT / "analysis" / "passive" / "capture_efficiency_VGM45.csv"
        h5_path = REPO_ROOT / passive_vs_optpassive_sweep.FLAPS[45]["h5"]

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_copy = Path(tmpdir) / source_csv.name
            csv_copy.write_text(source_csv.read_text())

            with csv_copy.open(newline="") as fh:
                before_reader = csv.DictReader(fh)
                before_fieldnames = list(before_reader.fieldnames or [])
                before_rows = list(before_reader)

            retabulate_hydro_columns.retabulate_csv(csv_copy, h5_path, write=True)

            with csv_copy.open(newline="") as fh:
                after_reader = csv.DictReader(fh)
                after_fieldnames = list(after_reader.fieldnames or [])
                after_rows = list(after_reader)

        self.assertEqual(before_fieldnames, after_fieldnames)
        self.assertEqual(
            [row["P_capture_W"] for row in before_rows],
            [row["P_capture_W"] for row in after_rows],
        )

    def test_retabulation_preserves_cc_non_target_columns(self) -> None:
        source_csv = REPO_ROOT / "analysis" / "cc" / "capture_efficiency_VGM0.csv"
        h5_path = REPO_ROOT / passive_vs_optpassive_sweep.FLAPS[0]["h5"]

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_copy = Path(tmpdir) / source_csv.name
            csv_copy.write_text(source_csv.read_text())
            before_fieldnames, before_rows = retabulate_hydro_columns._load_csv_exact(csv_copy)

            retabulate_hydro_columns.retabulate_csv(csv_copy, h5_path, write=True)
            after_fieldnames, after_rows = retabulate_hydro_columns._load_csv_exact(csv_copy)

        self.assertEqual(
            retabulate_hydro_columns._non_target_differences(
                before_fieldnames,
                before_rows,
                after_fieldnames,
                after_rows,
            ),
            [],
        )

    def test_retabulation_recomputes_cc_linear_popt_invalid_from_hinge_basis(self) -> None:
        source_csv = REPO_ROOT / "analysis" / "cc" / "capture_efficiency_VGM0.csv"
        h5_path = REPO_ROOT / passive_vs_optpassive_sweep.FLAPS[0]["h5"]

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_copy = Path(tmpdir) / source_csv.name
            csv_copy.write_text(source_csv.read_text())

            retabulate_hydro_columns.retabulate_csv(csv_copy, h5_path, write=True)
            _, rows = retabulate_hydro_columns._load_csv_exact(csv_copy)

        for row in rows:
            with self.subTest(T_s=row["T_s"]):
                masked = str(row.get("masked", "false")).strip().lower() == "true"
                reactive = (
                    str(row.get("reactive_cancellation_limited", "false")).strip().lower() == "true"
                )
                p_capture = row.get("P_capture_W", "").strip()
                p_opt = row.get("P_opt_W", "").strip()
                expected = False
                if (not masked) and (not reactive) and p_capture and p_opt:
                    expected = (
                        float(p_capture) / float(p_opt)
                    ) > (1.0 + retabulate_hydro_columns.ETA_GT1_TOL)
                self.assertEqual(
                    str(row.get("linear_popt_invalid", "false")).strip().lower() == "true",
                    expected,
                )

    def test_non_target_differences_ignore_target_columns_only(self) -> None:
        fieldnames = [
            "T_s",
            "P_capture_W",
            "P_opt_W",
            "B55_Nmsrad",
            "F_exc_Nm",
            "eta",
            "masked",
            "P_converted_W",
        ]
        before_rows = [
            {
                "T_s": "1.0",
                "P_capture_W": "2.0",
                "P_opt_W": "3.0",
                "B55_Nmsrad": "4.0",
                "F_exc_Nm": "5.0",
                "eta": "0.6",
                "masked": "false",
                "P_converted_W": "7.0",
            }
        ]
        target_only_after = [dict(before_rows[0], eta="0.7", P_opt_W="2.9")]
        changed_nontarget_after = [dict(target_only_after[0], P_converted_W="8.0")]

        self.assertEqual(
            retabulate_hydro_columns._non_target_differences(
                fieldnames, before_rows, fieldnames, target_only_after
            ),
            [],
        )
        self.assertEqual(
            retabulate_hydro_columns._non_target_differences(
                fieldnames, before_rows, fieldnames, changed_nontarget_after
            ),
            ["line 2 column 'P_converted_W' changed: '7.0' -> '8.0'"],
        )

    def test_retabulation_adds_linear_popt_invalid_to_legacy_cc_schema(self) -> None:
        fieldnames = [
            "T_s",
            "P_capture_W",
            "P_opt_W",
            "B55_Nmsrad",
            "F_exc_Nm",
            "P_converted_W",
            "P_injected_W",
            "eta",
            "masked",
            "reactive_cancellation_limited",
        ]
        rows = [
            {
                "T_s": "0.50",
                "P_capture_W": "1.2",
                "P_opt_W": "1.0",
                "B55_Nmsrad": "1.0",
                "F_exc_Nm": "1.0",
                "P_converted_W": "1.5",
                "P_injected_W": "0.3",
                "eta": "1.2",
                "masked": "false",
                "reactive_cancellation_limited": "false",
            }
        ]

        updated_fieldnames, updated_rows = retabulate_hydro_columns._ensure_linear_popt_column(
            fieldnames, rows
        )

        self.assertIn("linear_popt_invalid", updated_fieldnames)
        self.assertEqual(
            updated_fieldnames.index("linear_popt_invalid"),
            updated_fieldnames.index("reactive_cancellation_limited") - 1,
        )
        self.assertEqual(updated_rows[0]["linear_popt_invalid"], "false")

    def test_verify_targets_eta_findings_are_nonfatal_unless_strict(self) -> None:
        targets = [
            {
                "label": "cc",
                "angle": 0,
                "fieldnames": ["T_s", "eta"],
                "before_rows": [{"T_s": "0.50", "eta": "1.20"}],
                "after_rows": [{"T_s": "0.50", "eta": "1.20"}],
            }
        ]

        self.assertEqual(retabulate_hydro_columns.verify_targets(targets), 0)
        self.assertEqual(retabulate_hydro_columns.verify_targets(targets, strict_eta=True), 1)


if __name__ == "__main__":
    unittest.main()
