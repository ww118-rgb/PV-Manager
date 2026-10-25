"""No network/Home Assistant required: Modbus user input must be safe & generic."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

DIR = Path(__file__).resolve().parents[1] / "custom_components/pv_energiemanager"
pkg = types.ModuleType("_pv_mbus_test")
pkg.__path__ = [str(DIR)]
sys.modules.setdefault("_pv_mbus_test", pkg)
for modname in ("modbus_codec", "modbus_validation"):
    spec = importlib.util.spec_from_file_location(f"_pv_mbus_test.{modname}", DIR / (modname + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

v = sys.modules["_pv_mbus_test.modbus_validation"]


def datapoint(**overrides):
    item = dict(name="Leistung", connection_id="conn1", address=39168,
                function_code="3", data_type="int32", byte_order="ABCD",
                scale=-0.001, offset=0, unit="kW", poll_seconds=15)
    item.update(overrides)
    return item


class UserConfigValidation(unittest.TestCase):
    def test_endpoint(self):
        d, err = v.validate_connection(dict(name=" TCP Gerät ", host="device.lan", port=5021, unit_id=1))
        self.assertIsNone(err)
        self.assertEqual(d["name"], "TCP Gerät")
        self.assertEqual(d["port"], 5021)
        for host in ("", "bad host"):
            with self.subTest(host=host):
                self.assertEqual(v.validate_connection(dict(name="A", host=host, port=502, unit_id=1))[1], "invalid_endpoint")

    def test_read_32bit_negative_scale(self):
        d, err = v.validate_read_point(datapoint(), {"conn1"})
        self.assertIsNone(err)
        self.assertEqual(d["function_code"], 3)
        self.assertEqual(d["scale"], -0.001)

    def test_unitless_modbus_status_and_preserve_existing_power_unit(self):
        # The UI does not supply an omitted unit; it must not default to W.
        data = datapoint(address=256, data_type="uint16", scale=1, unit="")
        result, error = v.validate_read_point(data, {"conn1"})
        self.assertIsNone(error)
        self.assertEqual(result["unit"], "")
        data.pop("unit")
        result, error = v.validate_read_point(data, {"conn1"})
        self.assertIsNone(error)
        self.assertEqual(result["unit"], "")
        power, error = v.validate_read_point(datapoint(), {"conn1"})
        self.assertIsNone(error)
        self.assertEqual(power["unit"], "kW")

    def test_byte_order_and_bounds(self):
        self.assertIsNone(v.validate_read_point(datapoint(address=65534), {"conn1"})[1])
        self.assertEqual(v.validate_read_point(datapoint(address=65535), {"conn1"})[1], "invalid_register")
        self.assertEqual(v.validate_read_point(datapoint(data_type="int16", byte_order="CDAB"), {"conn1"})[1], "invalid_register")
        self.assertIsNone(v.validate_read_point(datapoint(data_type="uint16", byte_order="BADC"), {"conn1"})[1])

    def test_reject_invalid(self):
        for patch, expected in (
            ({"connection_id": "missing"}, "invalid_endpoint"),
            ({"scale": 0}, "invalid_scale"),
            ({"scale": float('nan')}, "invalid_scale"),
            ({"offset": float('inf')}, "invalid_scale"),
            ({"function_code": 16}, "invalid_register"),
            ({"poll_seconds": 1}, "invalid_register"),
            ({"data_type": "byte_array"}, "invalid_register"),
            ({"address": -1}, "invalid_register"),
        ):
            with self.subTest(patch=patch):
                self.assertEqual(v.validate_read_point(datapoint(**patch), {"conn1"})[1], expected)


if __name__ == "__main__":
    unittest.main()
