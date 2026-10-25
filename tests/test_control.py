"""One-cycle power accounting, priorities and step hysteresis (pure unit tests)."""
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components/pv_energiemanager"
PKG = "pv_control_tests"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package
for name in ("engine", "control"):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
Consumer = sys.modules[f"{PKG}.engine"].Consumer
plan_cycle = sys.modules[f"{PKG}.control"].plan_cycle


class SingleCycleTests(unittest.TestCase):
    def wallbox(self, name="wb", priority=1, subpriority=1, old_target=4830):
        return Consumer(name, priority, subpriority, "continuous", 4140, 11040,
                        step_w=690, old_target=old_target)

    def test_power_budget_is_continuous_on_threshold(self):
        wb = self.wallbox()
        prev = {"wb": 4830}
        a = plan_cycle(-999, 6000, 4830, 0, [wb], prev)
        b = plan_cycle(-1001, 6000, 4830, 0, [wb], prev)
        self.assertEqual(a.physical_budget - b.physical_budget, 2)
        self.assertLessEqual(sum(a.targets.values()), 4830)
        self.assertLessEqual(sum(b.targets.values()), 4830)

    def test_one_watt_grid_import_wont_start_an_ampere_change(self):
        wb = self.wallbox()
        plan = plan_cycle(-1, 2000, 4830, 0, [wb], {"wb":4830})
        self.assertEqual(plan.targets["wb"],4830)

    def test_grid_import_reduces_in_same_cycle(self):
        wb = self.wallbox(old_target=10350)
        plan=plan_cycle(-2000, 4000, 10350, 0, [wb], {"wb":10350})
        self.assertEqual(plan.physical_budget,12350)
        self.assertLessEqual(plan.targets["wb"],8350)

    def test_exact_step_used_immediately_without_ramp_timer(self):
        wb = self.wallbox(old_target=5520)
        plan=plan_cycle(0, 13080, 5520, 0, [wb], {"wb":5520})
        self.assertEqual(plan.targets["wb"],11040)

    def test_hysteresis_150w_holds_old_step(self):
        wb=self.wallbox(old_target=5520)
        plan=plan_cycle(0,0,5390,0,[wb],{"wb":5520})
        self.assertEqual(plan.targets["wb"],5520)

    def test_hysteresis_cannot_block_priority_change(self):
        high=Consumer("heat",1,1,"continuous",1000,5000)
        low=Consumer("ev",2,1,"continuous",1000,5000,old_target=4000)
        plan=plan_cycle(0,0,3999,0,[high,low],{"heat":0,"ev":4000})
        self.assertEqual(plan.targets["ev"],0)
        self.assertGreater(plan.targets["heat"],0)

    def test_hysteresis_cannot_keep_removed_demand(self):
        wb=self.wallbox(old_target=4830)
        wb=Consumer("wb",1,1,"continuous",4140,11040,requested=False,
                    old_target=4830,step_w=690)
        plan=plan_cycle(0,0,4829,0,[wb],{"wb":4830})
        self.assertEqual(plan.targets["wb"],0)

    def test_two_wallboxes_split_native_steps(self):
        a=self.wallbox("a",subpriority=1,old_target=0)
        b=self.wallbox("b",subpriority=2,old_target=0)
        plan=plan_cycle(0,0,11000,0,[a,b],{"a":0,"b":0})
        self.assertEqual(sorted(plan.targets.values()),[4830,5520])

    def test_without_battery_budget_is_grid_plus_controlled_load(self):
        wb=self.wallbox(old_target=5520)
        plan=plan_cycle(690,0,5520,0,[wb],{"wb":5520})
        self.assertEqual(plan.physical_budget,6210)
        self.assertEqual(plan.targets["wb"],6210)

    def test_negative_battery_contributes_as_deficit(self):
        wb=self.wallbox(old_target=5520)
        plan=plan_cycle(0,-690,5520,0,[wb],{"wb":5520})
        self.assertEqual(plan.physical_budget,4830)
        self.assertEqual(plan.targets["wb"],4830)


if __name__ == "__main__":
    unittest.main()
