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
from pv_grid_safety_unit_tests.grid_safety import (
    safety_targets, budget_with_grid_priority, cap_budget_on_import,
)


class SafetyTests(unittest.TestCase):
    def test_physical_budget_continuous_when_battery_charges(self):
        self.assertEqual(budget_with_grid_priority(-8290,2940,40700,0),35350)
        self.assertEqual(budget_with_grid_priority(0,2940,40700,0),43640)
        self.assertEqual(budget_with_grid_priority(-8290,-2000,40700,0),30410)

    def test_no_6kw_budget_jump_at_1000_w_safety_threshold(self):
        before = budget_with_grid_priority(-999, 6000, 42000, 0)
        after = budget_with_grid_priority(-1001, 6000, 42000, 0)
        self.assertEqual(before, 47001)
        self.assertEqual(after, 46999)
        self.assertEqual(before - after, 2)

    def test_when_importing_do_not_expand_existing_load(self):
        self.assertEqual(cap_budget_on_import(-999, 47001, 42000), 42000)
        self.assertEqual(cap_budget_on_import(-1001, 46999, 42000), 42000)
        self.assertEqual(cap_budget_on_import(-100, 47000, 42000), 47000)
        self.assertEqual(cap_budget_on_import(0, 48000, 42000), 48000)
        self.assertEqual(cap_budget_on_import(-900, 37000, 42000), 37000)

    def test_import_cap_allows_priority_reallocation_without_more_load(self):
        hp = Consumer("hp",1,1,"continuous",1000,10000)
        wb = Consumer("wb",2,1,"continuous",1000,10000)
        from pv_grid_safety_unit_tests.engine import distribute
        old = {"hp":0,"wb":8000}
        budget = cap_budget_on_import(-500, 10000, sum(old.values()))
        plan = distribute(budget,[hp,wb]).targets
        self.assertEqual(plan["hp"],8000)
        self.assertEqual(plan["wb"],0)
        self.assertEqual(sum(plan.values()),8000)

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
