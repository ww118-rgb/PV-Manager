"""Regression checks with minimal HA stubs; no live Home Assistant required."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/pv_energiemanager'
PKG = 'pv_ems_monitoring_tests'


def module(name, **fields):
    mod = types.ModuleType(name)
    for key, value in fields.items():
        setattr(mod, key, value)
    return mod


def fake_modules():
    def passthrough(f):
        f.__ha_callback__ = True
        return f

    class FakeEntity:
        def __init__(self): self.written = 0
        async def async_added_to_hass(self): pass
        async def async_will_remove_from_hass(self): pass
        def async_on_remove(self, callback): pass
        def async_write_ha_state(self): self.written += 1

    class FakeDeviceInfo(dict): pass
    class FakeTcpParams:
        def __init__(self, *a, **k): pass

    return {
        'homeassistant': module('homeassistant'),
        'homeassistant.core': module('homeassistant.core', HomeAssistant=object, callback=passthrough),
        'homeassistant.helpers': module('homeassistant.helpers'),
        'homeassistant.helpers.event': module('homeassistant.helpers.event', async_track_time_interval=lambda *a: lambda: None),
        'homeassistant.helpers.entity': module('homeassistant.helpers.entity', DeviceInfo=FakeDeviceInfo),
        'homeassistant.helpers.entity_registry': module('homeassistant.helpers.entity_registry', async_get=lambda hass: hass.entity_registry),
        'homeassistant.components': module('homeassistant.components'),
        'homeassistant.components.modbus': module('homeassistant.components.modbus', async_get_unit=lambda *a: None),
        'homeassistant.components.sensor': module('homeassistant.components.sensor', SensorEntity=FakeEntity),
        'modbus_connection': module('modbus_connection', ModbusTcpParams=FakeTcpParams),
    }


def load(rel, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


class RuntimeMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.extra_modules = fake_modules()
        self.extra_modules[PKG] = module(PKG)
        self.extra_modules[PKG].__path__ = [str(ROOT)]
        self.patch = patch.dict(sys.modules, self.extra_modules)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.const = load('const.py', f'{PKG}.const')
        self.engine = load('engine.py', f'{PKG}.engine')
        self.codec = load('modbus_codec.py', f'{PKG}.modbus_codec')
        self.manager_module = load('manager.py', f'{PKG}.manager')
        self.modbus_module = load('modbus_sensors.py', f'{PKG}.modbus_sensors')

    def test_paused_manager_refreshes_inputs_without_writes(self):
        class FakeState:
            def __init__(self, value):
                self.state = str(value)
                self.attributes = {'unit_of_measurement': 'kW'}

        class FakeStates:
            def __init__(self):
                self.data = {'sensor.grid': FakeState(2.5), 'sensor.pv': FakeState(6), 'number.evse': FakeState(0)}
            def get(self, key): return self.data.get(key)

        class FakeServices:
            def __init__(self): self.calls = 0
            async def async_call(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError('Paused EMS must not send actuator commands')

        hass = types.SimpleNamespace(states=FakeStates(), services=FakeServices())
        entry = types.SimpleNamespace(data={
            'grid_entity': 'sensor.grid', 'pv_entity': 'sensor.pv',
            'grid_export_positive': True, 'interval_s': 15,
        }, options={'devices': [{
            'id': 'evse', 'name': 'EVSE', 'kind': 'continuous',
            'priority': 1, 'subpriority': 1, 'min_w': 1400,
            'max_w': 11000, 'power_output': 'number.evse',
            'output_unit': 'W',
        }]}, entry_id='test-entry')
        ems = self.manager_module.PowerManager(hass, entry)
        self.assertFalse(ems.enabled)
        asyncio.run(ems.async_cycle())
        self.assertEqual(ems.values['grid'], 2500)
        self.assertEqual(ems.values['pv'], 6000)
        self.assertEqual(ems.values['budget'], 2500)
        self.assertEqual(ems.status, 'Pausiert')
        self.assertEqual(ems.cycle_count, 0)
        hass.states.data['sensor.grid'].state = '1.25'
        asyncio.run(ems.async_cycle())
        self.assertEqual(ems.values['grid'], 1250)
        self.assertEqual(ems.values['budget'], 1250)
        self.assertEqual(hass.services.calls, 0)
        self.assertEqual(ems.last_targets['evse'], 0)
        self.assertEqual(ems.request_since, {})

    def test_invalid_grid_clears_old_budget_while_paused(self):
        class States:
            def get(self, key): return None
        hass = types.SimpleNamespace(states=States())
        entry = types.SimpleNamespace(data={'grid_entity': 'sensor.grid'}, options={}, entry_id='test')
        ems = self.manager_module.PowerManager(hass, entry)
        ems.values['budget'] = 1000
        asyncio.run(ems.async_cycle())
        self.assertIsNone(ems.values['grid'])
        self.assertIsNone(ems.values['budget'])
        self.assertEqual(ems.status, 'Pausiert (Messfehler)')
        self.assertEqual(ems.cycle_count, 0)

    def test_modbus_poll_records_every_successful_attempt(self):
        class Unit:
            async def read_holding_registers(self, address, count):
                return [0, 1234]

        hass = types.SimpleNamespace()
        entry = types.SimpleNamespace(entry_id='test')
        cfg = {'id': 'r', 'name': 'Grid', 'function_code': 3, 'address': 39168,
               'data_type': 'int32', 'byte_order': 'ABCD', 'scale': 0.001,
               'offset': 0, 'unit': 'kW', 'poll_seconds': 15}
        s = self.modbus_module.PVModbusReadSensor(hass, entry, {'id': 'c', 'name': 'Connection'}, cfg, Unit())
        s.async_write_ha_state = lambda: None

        async def scenario():
            await s._refresh()
            await s._refresh()

        asyncio.run(scenario())
        attrs = s.extra_state_attributes
        self.assertEqual(s.native_value if hasattr(s, 'native_value') else s._attr_native_value, 1.234)
        self.assertTrue(s.available if hasattr(s, 'available') else s._attr_available)
        self.assertEqual(attrs['read_attempts'], 2)
        self.assertEqual(attrs['successful_reads'], 2)
        self.assertIsNotNone(attrs['last_attempt'])
        self.assertIsNotNone(attrs['last_success'])
        self.assertIsNone(attrs['last_error'])

    def test_modbus_failure_is_visible(self):
        class Unit:
            async def read_holding_registers(self, address, count):
                raise ConnectionError('connection lost')

        s = self.modbus_module.PVModbusReadSensor(types.SimpleNamespace(),
            types.SimpleNamespace(entry_id='test'),
            {'id': 'c', 'name': 'Connection'},
            {'id': 'r', 'name': 'Grid', 'function_code': 3, 'address': 0,
             'data_type': 'uint16', 'byte_order': 'ABCD', 'scale': 1,
             'offset': 0, 'poll_seconds': 15}, Unit())
        s.async_write_ha_state = lambda: None
        asyncio.run(s._refresh())
        self.assertFalse(s._attr_available)
        self.assertEqual(s.extra_state_attributes['read_attempts'], 1)
        self.assertEqual(s.extra_state_attributes['successful_reads'], 0)
        self.assertIn('connection lost', s.extra_state_attributes['last_error'])

    def test_modbus_time_callback_runs_consecutive_intervals(self):
        """Regression: repeated timed reads need an event-loop callback."""
        scheduled = []

        def strict_tracker(hass, action, interval):
            self.assertTrue(getattr(action, "__ha_callback__", False))
            scheduled.append(action)
            return lambda: None

        class Unit:
            def __init__(self):
                self.value = 100

            async def read_holding_registers(self, address, count):
                self.value += 10
                return [self.value]

        async def scenario():
            hass = types.SimpleNamespace(async_create_task=asyncio.create_task)
            config = {"id": "r", "name": "Grid", "function_code": 3,
                      "address": 5, "data_type": "uint16", "byte_order": "ABCD",
                      "scale": 1, "offset": 0, "poll_seconds": 15}
            sensor = self.modbus_module.PVModbusReadSensor(
                hass, types.SimpleNamespace(entry_id="test"),
                {"id": "c", "name": "Connection"}, config, Unit()
            )
            sensor.async_write_ha_state = lambda: None
            with patch.object(self.modbus_module, "async_track_time_interval", strict_tracker):
                await sensor.async_added_to_hass()
            await asyncio.sleep(0.01)
            self.assertEqual(sensor.extra_state_attributes["successful_reads"], 1)
            scheduled[0](None)
            await asyncio.sleep(0.01)
            scheduled[0](None)
            await asyncio.sleep(0.01)
            self.assertEqual(sensor.extra_state_attributes["successful_reads"], 3)
            self.assertEqual(sensor._attr_native_value, 130)

        asyncio.run(scenario())

    def test_manager_time_callback_updates_inputs_when_paused(self):
        """Regression: EMS timer must trigger without enabling actuator writes."""
        scheduled = []

        def strict_tracker(hass, action, interval):
            self.assertTrue(getattr(action, "__ha_callback__", False))
            scheduled.append(action)
            return lambda: None

        class State:
            def __init__(self, value):
                self.state = str(value)
                self.attributes = {"unit_of_measurement": "kW"}

        async def scenario():
            grid = State(1.0)
            hass = types.SimpleNamespace(
                async_create_task=asyncio.create_task,
                states=types.SimpleNamespace(
                    get=lambda entity: grid if entity == "sensor.grid" else None
                ),
            )
            entry = types.SimpleNamespace(
                entry_id="test", options={},
                data={"grid_entity": "sensor.grid", "interval_s": 15},
            )
            manager = self.manager_module.PowerManager(hass, entry)
            with patch.object(self.manager_module, "async_track_time_interval", strict_tracker):
                manager.start()
            scheduled[0](None)
            await asyncio.sleep(0.01)
            self.assertEqual(manager.values["grid"], 1000)
            grid.state = "3.0"
            scheduled[0](None)
            await asyncio.sleep(0.01)
            self.assertEqual(manager.values["grid"], 3000)
            self.assertEqual(manager.status, "Pausiert")
            self.assertEqual(manager.cycle_count, 0)
            manager.stop()

        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
