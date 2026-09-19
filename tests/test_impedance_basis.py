import csv
import math
import unittest
from pathlib import Path

import numpy as np
import yaml

try:
    import h5py
except ImportError:  # pragma: no cover - exercised via skip
    h5py = None


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / 'config'
DOCS_DIR = REPO_ROOT / 'docs'
HYDRO_DIR = REPO_ROOT / 'hydroData'

EXPECTED_ZERO_CROSS_WN = {
    'VGM-0': 1.066,
    'VGM-10': 1.460,
    'VGM-20': 1.557,
    'VGM-45': 1.823,
    'VGM-90': 2.083,
}


@unittest.skipIf(h5py is None, 'h5py not installed')
class ImpedanceBasisTests(unittest.TestCase):
    def load_yaml(self, name: str):
        with (CONFIG_DIR / name).open() as fh:
            return yaml.safe_load(fh)

    def read_zero_cross_targets(self):
        with (DOCS_DIR / 'freedecay_validation.csv').open() as fh:
            reader = csv.DictReader(fh)
            return {row['config']: float(row['cpp_zerocross_wn_rads']) for row in reader}

    def load_pitch_tables(self, h5_name: str):
        with h5py.File(HYDRO_DIR / h5_name, 'r') as h5:
            omega = [float(v) for v in np.asarray(h5['simulation_parameters/w'][()]).reshape(-1)]
            rho = float(np.asarray(h5['simulation_parameters/rho'][()]).reshape(-1)[0])
            g = float(np.asarray(h5['simulation_parameters/g'][()]).reshape(-1)[0])
            added = h5['body1/hydro_coeffs/added_mass/components/5_5'][()]
            damping = h5['body1/hydro_coeffs/radiation_damping/components/5_5'][()]
            lrs = h5['body1/hydro_coeffs/linear_restoring_stiffness'][()]
            k_hs55_raw = float(lrs[4][4]) if lrs.size else 0.0
        return {
            'omega': omega,
            'mu55': [float(row[1]) for row in added],
            'lambda55': [float(row[1]) for row in damping],
            'rho': rho,
            'g': g,
            'k_hs55_raw': k_hs55_raw,
        }

    @staticmethod
    def interp(x_values, y_values, x):
        if x <= x_values[0]:
            return y_values[0]
        if x >= x_values[-1]:
            return y_values[-1]
        for idx in range(1, len(x_values)):
            if x <= x_values[idx]:
                x0, x1 = x_values[idx - 1], x_values[idx]
                y0, y1 = y_values[idx - 1], y_values[idx]
                alpha = (x - x0) / (x1 - x0)
                return y0 + alpha * (y1 - y0)
        return y_values[-1]

    def load_config_derived_params(self, config_name: str):
        cfg = self.load_yaml(config_name)
        flap = cfg['body']['flap']
        hinge = cfg['hinge']
        hydro = cfg['hydro']
        r_g = abs(float(flap['cog'][2]) - float(hinge['position_z']))
        i_hinge = float(flap['inertia_yy']) + float(flap['mass']) * r_g * r_g
        return {
            'controller_type': cfg['controller']['type'],
            'h5_file': hydro['h5_file'],
            'impedance_h5_file': hydro.get('impedance_h5_file', ''),
            'i_hinge': i_hinge,
            'k_ext': float(hinge['external_stiffness']),
            'k_gb': float(hinge['gravity_buoyancy_stiffness']),
        }

    def natural_frequency_from_impedance(self, h5_name: str, i_hinge: float, k_eff: float) -> float:
        tables = self.load_pitch_tables(h5_name)

        def residual(omega: float) -> float:
            a55 = self.interp(tables['omega'], tables['mu55'], omega) * tables['rho']
            k_hs55 = tables['k_hs55_raw'] * tables['rho'] * tables['g']
            return omega * omega * (i_hinge + a55) - (k_hs55 + k_eff)

        lo, hi = 0.5, 3.0
        f_lo = residual(lo)
        bracket = None
        for step in range(1, 251):
            x = lo + (hi - lo) * step / 250.0
            f_x = residual(x)
            if (f_lo <= 0.0 <= f_x) or (f_lo >= 0.0 >= f_x):
                bracket = [lo, x, f_lo, f_x]
                break
            lo, f_lo = x, f_x
        self.assertIsNotNone(bracket, f'Failed to bracket natural frequency root for {h5_name}')
        lo, hi, f_lo, _ = bracket
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            f_mid = residual(mid)
            if (f_lo <= 0.0 <= f_mid) or (f_lo >= 0.0 >= f_mid):
                hi = mid
            else:
                lo = mid
                f_lo = f_mid
        return 0.5 * (lo + hi)

    def test_k_hs55_denormalization(self):
        tables = self.load_pitch_tables('vgoswec_90.h5')
        self.assertAlmostEqual(tables['rho'], 1000.0, places=9)
        self.assertAlmostEqual(tables['g'], 9.80665, places=9)
        self.assertAlmostEqual(
            tables['k_hs55_raw'] * tables['rho'] * tables['g'],
            -1.2076889475,
            places=6,
        )

    def test_k_hs_eff_composition(self):
        params = self.load_config_derived_params('vgoswec_90_opt_passive.yaml')
        tables = self.load_pitch_tables('hinged_vgoswec_90.h5')
        omega = 2.094
        a55 = self.interp(tables['omega'], tables['mu55'], omega) * tables['rho']
        k_hs55 = tables['k_hs55_raw'] * tables['rho'] * tables['g']
        k_eff = k_hs55 + params['k_ext'] + params['k_gb']
        expected_k_r = omega * omega * (params['i_hinge'] + a55) - k_eff
        manual_without_kgb = omega * omega * (params['i_hinge'] + a55) - (k_hs55 + params['k_ext'])
        self.assertAlmostEqual(k_eff, 6.57 + 0.867, places=12)
        self.assertAlmostEqual(manual_without_kgb - expected_k_r, params['k_gb'], places=12)

    def test_hinged_impedance_matches_freedecay_within_three_percent(self):
        targets = self.read_zero_cross_targets()
        self.assertEqual(targets, EXPECTED_ZERO_CROSS_WN)
        for angle in (0, 10, 20, 45, 90):
            config_name = f'vgoswec_{angle}_opt_passive.yaml'
            params = self.load_config_derived_params(config_name)
            predicted = self.natural_frequency_from_impedance(
                Path(params['impedance_h5_file']).name,
                params['i_hinge'],
                params['k_ext'] + params['k_gb'],
            )
            expected = targets[f'VGM-{angle}']
            self.assertAlmostEqual(predicted, expected, delta=expected * 0.03)

    def test_gain_derived_configs_require_impedance_h5_file(self):
        for cfg_path in sorted(CONFIG_DIR.glob('vgoswec_*.yaml')):
            cfg = self.load_yaml(cfg_path.name)
            ctrl_type = cfg['controller']['type']
            if ctrl_type in {'cc', 'opt_passive'}:
                hydro = cfg['hydro']
                self.assertTrue(
                    hydro.get('impedance_h5_file'),
                    msg=f'{cfg_path.name} must set hydro.impedance_h5_file',
                )


if __name__ == '__main__':
    unittest.main()
