"""Upward output ramp tests with no Home Assistant runtime dependency."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/pv_energiemanager"
PKG = "pv_ramp_unit_tests"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg
for name in ("engine", "ramp"):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

Consumer = sys.modules[f"{PKG}.engine"].Consumer
limit_increases = sys.modules[f"{PKG}.ramp"].limit_increases


def wallbox(name, maximum=11040):
    return Consumer(name, 2, 1, "continuous", 4140, maximum, step_w=690)


class RampTests(unittest.TestCase):
    def test_two_wallboxes_do_not_jump_from_eight_to_sixteen(self):
        devices = [wallbox("a"), wallbox("b")]
        self.assertEqual(
            limit_increases({"a":11040, "b":11040}, devices, {"a":5520, "b":5520}),
            {"a":6900, "b":6900},
        )

    def test_sixteen_amps_reached_at_stable_full_surplus(self):
        devices = [wallbox("a"), wallbox("b")]
        old = {"a":5520, "b":5520}
        for target in (6900, 8280, 9660, 11040):
            old = limit_increases({"a":11040, "b":11040}, devices, old)
            self.assertEqual(old, {"a":target, "b":target})

    def test_reductions_and_stops_are_unrestricted(self):
        device = wallbox("wb")
        self.assertEqual(limit_increases({"wb":4830}, [device], {"wb":11040}), {"wb":4830})
        self.assertEqual(limit_increases({"wb":0}, [device], {"wb":11040}), {"wb":0})

    def test_start_from_off_at_valid_minimum(self):
        self.assertEqual(
            limit_increases({"wb":11040}, [wallbox("wb")], {"wb":0}),
            {"wb":4140},
        )

    def test_fine_resolution_not_delayed(self):
        device = Consumer("hp", 1, 1, "continuous", 5000, 20000, step_w=1)
        self.assertEqual(limit_increases({"hp":20000}, [device], {"hp":5000}), {"hp":20000})

    def test_max_11000_does_not_become_11040(self):
        self.assertEqual(
            limit_increases({"wb":10350}, [wallbox("wb", 11000)], {"wb":9660}),
            {"wb":10350},
        )

    def test_priority_eviction_immediate(self):
        self.assertEqual(
            limit_increases({"wb":0}, [wallbox("wb")], {"wb":11040}), {"wb":0},
        )

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            limit_increases({}, [], {}, max_steps=0)


if __name__ == "__main__":
    unittest.main()
