"""Step wizard data preparation and non-destructive reconfiguration."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

FILE = (Path(__file__).resolve().parents[1] / "custom_components" /
        "pv_energiemanager" / "setup_wizard.py")
spec = importlib.util.spec_from_file_location("pv_setup_helper", FILE)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class WizardTests(unittest.TestCase):
    def test_edit_existing_preserves_identity_and_timings(self):
        old = {"id": "abc", "name": "Alt", "priority": 2, "subpriority": 1,
               "power_output": "number.old", "actual_entity": "sensor.old",
               "min_on_s": 120, "start_delay_s": 50, "min_off_s": 90}
        basic = {"name": "Neu", "kind": "continuous", "min_w": 4140,
                 "max_w": 11040, "priority": 1, "subpriority": 1}
        output = {"power_output": "number.wallbox", "output_unit": "A"}
        feedback = {"actual_entity": "sensor.wallbox"}
        value = setup.merge_consumer(old, basic, output, feedback,
                                     {"phases": "3", "voltage": 230})
        self.assertEqual(value["id"], "abc")
        self.assertEqual(value["power_output"], "number.wallbox")
        self.assertEqual(value["actual_entity"], "sensor.wallbox")
        self.assertEqual(value["start_delay_s"], 50)
        self.assertEqual(value["min_off_s"], 90)
        self.assertEqual(value["min_on_s"], 120)

    def test_cleared_optional_fields_do_not_reappear(self):
        old = {"demand_entity": "binary_sensor.ev", "actual_entity": "sensor.ev",
               "switch_output": "switch.old"}
        c = setup.merge_consumer(old, {"kind": "continuous"},
                                 {"power_output": "number.ev", "output_unit": "W"},
                                 {})
        self.assertNotIn("actual_entity", c)
        self.assertNotIn("demand_entity", c)
        self.assertNotIn("switch_output", c)

    def test_unknown_measured_load_is_not_presented_as_zero(self):
        warnings = setup.check_consumer_setup(
            {"kind": "continuous", "power_output": "number.ev", "output_unit": "A",
             "phases": 3, "voltage": 230}, output_state="unknown")
        self.assertTrue(any("Istleistung" in w for w in warnings))
        self.assertTrue(any("immer" in w for w in warnings))
        self.assertTrue(any("bestätigten" in w for w in warnings))

    def test_watts_and_kilowatts_are_previewed(self):
        s = SimpleNamespace(state="-13.59", attributes={"unit_of_measurement": "kW"})
        grid = setup.source_power_w(s)
        self.assertEqual(grid, -13590)
        self.assertEqual(setup.signed_grid_preview(grid, True), "Netzbezug: 13.590 W")
        self.assertEqual(setup.signed_grid_preview(grid, False), "Einspeisung: 13.590 W")

    def test_non_power_units_rejected(self):
        s = SimpleNamespace(state="400", attributes={"unit_of_measurement": "A"})
        self.assertIsNone(setup.source_power_w(s))
        self.assertIsNone(setup.source_power_w(None))
        self.assertIn("kein gültiger", setup.signed_grid_preview(None, True))


if __name__ == "__main__":
    unittest.main()

class CompatibilityTests(unittest.TestCase):
    def config(self, **overrides):
        d = {"kind": "continuous", "min_w": 4140, "max_w": 11040,
             "output_unit": "A", "phases": 3, "voltage": 230}
        d.update(overrides)
        return d

    def state(self, unit='A', lo=0, hi=16, step=1, status='6'):
        return SimpleNamespace(state=status, attributes={
            'unit_of_measurement': unit, 'min': lo, 'max': hi, 'step': step,
        })

    def test_good_wallbox(self):
        self.assertIsNone(setup.actuator_compatibility_error(self.config(),self.state()))

    def test_catches_wrong_units(self):
        self.assertEqual('actuator_unit_mismatch',setup.actuator_compatibility_error(
            self.config(output_unit='W'), self.state()))

    def test_catches_unreachable_minimum_step(self):
        self.assertEqual('actuator_step_mismatch', setup.actuator_compatibility_error(
            self.config(min_w=4414), self.state()))

    def test_catches_max_above_actuator(self):
        self.assertEqual('actuator_limits_mismatch', setup.actuator_compatibility_error(
            self.config(max_w=22000),self.state()))

    def test_does_not_accept_unavailable(self):
        self.assertEqual('unavailable_actuator', setup.actuator_compatibility_error(
            self.config(),self.state(status='unavailable')))

    def test_no_readback_yet_can_be_configured(self):
        s=self.state(status='unknown')
        s.attributes.update(feedback_status='unknown_after_start',
                            off_value_configured=True, last_write_error=None)
        self.assertIsNone(setup.actuator_compatibility_error(self.config(),s))
