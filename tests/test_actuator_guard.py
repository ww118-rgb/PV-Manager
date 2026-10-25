"""Validate the very limited exception for first write-only number command."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

FILE = Path(__file__).resolve().parents[1] / 'custom_components/pv_energiemanager/actuator_guard.py'
spec = importlib.util.spec_from_file_location('actuator_guard_test_pure', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
check = mod.actuator_can_receive_command

EID = 'entry1'
POINTS = [{'id': 'w1', 'off_value': 1.0}]
REG = SimpleNamespace(domain='number', platform='pv_energiemanager',
                      config_entry_id=EID, unique_id='entry1_mb_write_w1')


def state(value, **attrs):
    payload = {'feedback_status':'unknown_after_start',
               'off_value_configured':True, 'last_write_error':None}
    payload.update(attrs)
    return SimpleNamespace(state=value, attributes=payload)


def eligible(val, registry=REG, points=POINTS, entity='number.wallbox'):
    return check(entity, val, registry_entry=registry, entry_id=EID, write_points=points)


class GuardTests(unittest.TestCase):
    def test_new_number_is_writable(self):
        self.assertTrue(eligible(state('unknown')))

    def test_never_write_to_unavailable(self):
        self.assertFalse(eligible(state('unavailable')))
        self.assertFalse(eligible(None))

    def test_unknown_foreign_output_fails(self):
        self.assertFalse(eligible(state('unknown'), registry=None))
        self.assertFalse(eligible(state('unknown'), registry=SimpleNamespace(
            domain='number', platform='other', config_entry_id=EID,
            unique_id='entry1_mb_write_w1')))
        self.assertFalse(eligible(state('unknown'), entity='switch.other'))

    def test_pause_value_must_be_explicit(self):
        self.assertFalse(eligible(state('unknown'), points=[{'id':'w1'}]))
        self.assertFalse(eligible(state('unknown', off_value_configured=False)))

    def test_previous_error_blocks_unknown(self):
        self.assertFalse(eligible(state('unknown', last_write_error='TimeoutError')))

    def test_existing_numeric_value_remains_writable(self):
        self.assertTrue(eligible(state('6')))
        self.assertTrue(eligible(state('0')))


if __name__ == '__main__':
    unittest.main()
