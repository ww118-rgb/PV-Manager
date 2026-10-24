"""Pure Modbus decoder checks without importing Home Assistant."""
import importlib.util
from pathlib import Path
import struct
import unittest

PATH = Path(__file__).resolve().parents[1] / "custom_components/pv_energiemanager/modbus_codec.py"
spec = importlib.util.spec_from_file_location("pv_modbus_codec", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CodecTests(unittest.TestCase):
    def test_signed(self):
        self.assertEqual(mod.decode_registers([65535], "int16"), -1)
        self.assertEqual(mod.decode_registers([65535], "uint16"), 65535)
        self.assertEqual(mod.decode_registers([65535, 65535], "int32"), -1)

    def test_float_orders(self):
        raw = struct.pack(">f", 12.5)
        for order in mod.WORD_ORDER:
            tagged = dict(zip("ABCD", raw))
            received = bytes(tagged[ch] for ch in order)
            words = [int.from_bytes(received[i:i+2], "big") for i in (0, 2)]
            with self.subTest(order=order):
                self.assertAlmostEqual(
                    mod.decode_registers(words, "float32", order), 12.5
                )

    def test_scale(self):
        self.assertEqual(mod.decode_registers([100], "uint16", scale=0.1, offset=-2), 8)
        self.assertEqual(mod.decode_registers([0x0102], "uint16", "BA"), 0x0201)

    def test_invalid(self):
        cases = [([1], "int32"), ([65536], "uint16"), ([1, 2], "float32", "XXXX")]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                mod.decode_registers(*case)
        with self.assertRaises(ValueError):
            mod.decode_registers([1], "uint16", scale=0)


if __name__ == "__main__":
    unittest.main()
