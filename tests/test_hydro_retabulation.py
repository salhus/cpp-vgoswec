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


if __name__ == "__main__":
    unittest.main()
