"""Regression for grid import protection with battery in automatic mode."""
from __future__ import annotations
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components/pv_energiemanager"
PKG = "pv_grid_safety_unit_tests"
pkg=types.ModuleType(PKG)
pkg.__path__=[str(ROOT)]
sys.modules[PKG]=pkg
for name in ("engine","grid_safety"):
    spec=importlib.util.spec_from_file_location(f"{PKG}.{name}",ROOT/f"{name}.py")
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
from pv_grid_safety_unit_tests.engine import Consumer
from pv_grid_safety_unit_tests.grid_safety import safety_targets, budget_with_grid_priority


class SafetyTests(unittest.TestCase):
    def test_import_while_battery_charges_cannot_reclaim_charging(self):
        self.assertEqual(budget_with_grid_priority(-8290,2940,40700,0),32410)
        self.assertEqual(budget_with_grid_priority(0,2940,40700,0),43640)
        self.assertEqual(budget_with_grid_priority(-8290,-2000,40700,0),30410)

    def test_small_grid_deviation_does_not_start_safety(self):
        consumers=[Consumer("wb",1,1,"continuous",4140,11040,step_w=690)]
        old={"wb":10350}
        for grid in (-999,-1,0,2000):
            self.assertEqual(safety_targets(grid,consumers,old),old)

    def test_8290_import_reduces_low_priority_before_high(self):
        devices=[Consumer("hp",1,1,"continuous",5000,20000,step_w=1),
                 Consumer("w1",2,1,"continuous",4140,11040,step_w=690),
                 Consumer("w2",2,2,"continuous",4140,11040,step_w=690)]
        old={"hp":20000,"w1":10350,"w2":10350}
        next_values=safety_targets(-8290,devices,old)
        self.assertEqual(next_values["hp"],20000)
        self.assertLessEqual(sum(next_values.values()),32110)
        for key in old:
            self.assertGreaterEqual(next_values[key],0)
            self.assertLessEqual(next_values[key],old[key])

    def test_no_controllable_consumers(self):
        self.assertEqual(safety_targets(-8000,[],{}),{})

    def test_protection_never_increases_an_output(self):
        devices=[Consumer("hp",1,1,"continuous",5000,20000,step_w=1),
                 Consumer("wb",2,1,"continuous",4140,11040,step_w=690)]
        old={"hp":0,"wb":10350}
        values=safety_targets(-5000,devices,old)
        self.assertEqual(values["hp"],0)
        self.assertLessEqual(values["wb"],old["wb"])


if __name__=="__main__":
    unittest.main()
