"""Wire encoding and semantic stop mapping without HA or hardware."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

DIR = Path(__file__).resolve().parents[1] / 'custom_components/pv_energiemanager'
pkg = types.ModuleType('_pv_write_test')
pkg.__path__ = [str(DIR)]
sys.modules.setdefault('_pv_write_test', pkg)
for name in ('modbus_codec', 'modbus_writer'):
    spec = importlib.util.spec_from_file_location(f'_pv_write_test.{name}', DIR / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
w = sys.modules['_pv_write_test.modbus_writer']
codec = sys.modules['_pv_write_test.modbus_codec']


def wallbox(**overrides):
    d = dict(connection_id='generic', name='Ladestrom', address=770, function_code='16',
             data_type='float32', byte_order='ABCD', unit='A', active_min=6,
             active_max=16, step=1, off_value=1, scale=1, offset=0)
    d.update(overrides)
    return d


class EncodeTests(unittest.TestCase):
    def test_active_float32(self):
        point, error = w.validate_write_point(wallbox(), {'generic'})
        self.assertIsNone(error)
        self.assertEqual(w.command_for_setpoint(6, point)[1], [0x40C0, 0x0000])
        self.assertEqual(w.command_for_setpoint(16, point)[1], [0x4180, 0x0000])

    def test_off_is_custom_not_zero(self):
        point, _ = w.validate_write_point(wallbox(), {'generic'})
        physical, words = w.command_for_setpoint(0, point)
        self.assertEqual(physical, 1)
        self.assertEqual(words, [0x3F80, 0])
        point2, _ = w.validate_write_point(wallbox(off_value=0), {'generic'})
        self.assertEqual(w.command_for_setpoint(0, point2)[1], [0,0])
        with self.assertRaises(w.CommandValueError):
            w.command_for_setpoint(0, wallbox(off_value=None))

    def test_off_is_required(self):
        point = wallbox(); del point['off_value']
        self.assertIsNotNone(w.validate_write_point(point, {'generic'})[1])

    def test_fc06_rejects_float(self):
        self.assertEqual(w.validate_write_point(wallbox(function_code=6), {'generic'})[1], 'invalid_register')
        point, err = w.validate_write_point(wallbox(data_type='uint16', function_code=6, off_value=1), {'generic'})
        self.assertIsNone(err)
        self.assertEqual(w.command_for_setpoint(6, point)[1], [6])

    def test_arbitrary_units_not_wallbox_specific(self):
        point, err = w.validate_write_point(wallbox(unit='W', active_min=500, active_max=3000,
                                                    step=100, off_value=0, data_type='uint16',
                                                    function_code=6), {'generic'})
        self.assertIsNone(err)
        self.assertEqual(w.command_for_setpoint(1500,point)[1], [1500])
        self.assertEqual(w.command_for_setpoint(0,point)[1], [0])

    def test_range_and_steps(self):
        point,_ = w.validate_write_point(wallbox(), {'generic'})
        for v in (1, 5.9, 16.1, 6.5, -1):
            with self.subTest(v=v), self.assertRaises(w.CommandValueError):
                w.command_for_setpoint(v,point)

    def test_scaled_unsigned_signed(self):
        d = w.register_words(-1234, data_type='int16')
        self.assertEqual(codec.decode_registers(d,'int16'),-1234)
        for order in ('ABCD','BADC','CDAB','DCBA'):
            with self.subTest(order=order):
                d = w.register_words(123.5, data_type='float32', byte_order=order,
                                     scale=0.1, offset=1.5)
                self.assertAlmostEqual(codec.decode_registers(d,'float32',order,0.1,1.5),123.5,places=4)
        self.assertEqual(w.register_words(1234, data_type='uint32', byte_order='CDAB'),[1234,0])

    def test_overflow_and_unsupported_fraction(self):
        with self.assertRaises(w.CommandValueError):
            w.register_words(-1,data_type='uint16')
        with self.assertRaises(w.CommandValueError):
            w.register_words(4.4,data_type='uint16')
        with self.assertRaises(w.CommandValueError):
            w.register_words(1e40,data_type='float32')

    def test_invalid_ends(self):
        self.assertEqual(w.validate_write_point(wallbox(connection_id='wrong'), {'generic'})[1], 'invalid_endpoint')
        self.assertIsNotNone(w.validate_write_point(wallbox(active_min=0), {'generic'})[1])
        self.assertIsNotNone(w.validate_write_point(wallbox(step=0), {'generic'})[1])
        self.assertIsNotNone(w.validate_write_point(wallbox(address=65535), {'generic'})[1])


if __name__ == '__main__':
    unittest.main()
