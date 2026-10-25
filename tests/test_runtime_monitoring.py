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

    def test_own_unknown_modbus_number_allows_first_automatic_command(self):
        class WriteState:
            state = 'unknown'
            attributes = {
                'feedback_status': 'unknown_after_start',
                'off_value_configured': True,
                'last_write_error': None,
                'step': 1, 'min': 0, 'max': 16,
            }

        class States:
            def get(self, key):
                return WriteState() if key == 'number.wallbox' else None

        class Services:
            def __init__(self):
                self.commands = []
            async def async_call(self, domain, action, data, blocking=False):
                self.commands.append((domain, action, data))

        registry_record = types.SimpleNamespace(
            domain='number', platform='pv_energiemanager',
            config_entry_id='entry1', unique_id='entry1_mb_write_w1',
        )
        registry = types.SimpleNamespace(async_get=lambda _: registry_record)
        hass = types.SimpleNamespace(states=States(), services=Services(), entity_registry=registry)
        device = {
            'id': 'wallbox', 'name': 'Wallbox 1', 'kind': 'continuous',
            'priority': 1, 'subpriority': 1, 'min_w': 4140, 'max_w': 11040,
            'power_output': 'number.wallbox', 'output_unit': 'A',
            'phases': 3, 'voltage': 230,
        }
        entry = types.SimpleNamespace(entry_id='entry1', data={}, options={
            'devices': [device], 'modbus_write_points': [{'id': 'w1', 'off_value': 1}],
        })
        manager = self.manager_module.PowerManager(hass, entry)
        self.assertEqual(asyncio.run(manager._write(device, 4140)), 4140)
        self.assertEqual(hass.services.commands, [(
            'number', 'set_value', {'entity_id': 'number.wallbox', 'value': 6.0}
        )])

    def test_other_unknown_actuator_still_blocked(self):
        class States:
            def get(self, key):
                return types.SimpleNamespace(state='unknown', attributes={
                    'feedback_status': 'unknown_after_start',
                    'off_value_configured': True, 'last_write_error': None,
                    'step': 1, 'min': 0, 'max': 16,
                })
        class Services:
            calls = 0
            async def async_call(self, *args, **kwargs):
                self.calls += 1

        reg = types.SimpleNamespace(
            domain='number', platform='other_integration',
            config_entry_id='other', unique_id='elsewhere',
        )
        hass = types.SimpleNamespace(states=States(), services=Services(),
                                     entity_registry=types.SimpleNamespace(async_get=lambda _: reg))
        device = {'id':'w', 'name':'Wallbox', 'kind':'continuous',
                  'power_output':'number.wallbox', 'output_unit':'A',
                  'phases':3, 'voltage':230, 'min_w':4140, 'max_w':11040}
        entry = types.SimpleNamespace(entry_id='entry1', data={}, options={
            'devices':[device], 'modbus_write_points':[{'id':'w1','off_value':1}]})
        manager = self.manager_module.PowerManager(hass, entry)
        with self.assertRaisesRegex(ValueError, 'HA-Zustand: unknown'):
            asyncio.run(manager._write(device, 4140))
        self.assertEqual(hass.services.calls, 0)

    def test_arm_blocked_when_grid_missing(self):
        class States:
            def get(self, name): return None
        hass = types.SimpleNamespace(states=States())
        entry = types.SimpleNamespace(entry_id='no_grid', data={}, options={})
        ems = self.manager_module.PowerManager(hass, entry)
        ems.enable(True)
        self.assertFalse(ems.enabled)
        self.assertEqual(ems.status, 'Einrichtung unvollständig')
        self.assertIn('Netzleistung', ems.error)

    def test_arm_allowed_after_grid_sensor_is_valid(self):
        class States:
            def get(self, name):
                return types.SimpleNamespace(state='2.5', attributes={'unit_of_measurement':'kW'})
        hass = types.SimpleNamespace(states=States())
        entry = types.SimpleNamespace(entry_id='with_grid', data={'grid_entity':'sensor.grid'}, options={})
        ems = self.manager_module.PowerManager(hass, entry)
        ems.enable(True)
        self.assertTrue(ems.enabled)
        self.assertEqual(ems.status, 'Bereit')

    def test_zero_wallboxes_are_actively_paused_and_not_credited_as_surplus(self):
        """11k + 7.6k real WB draw while EMS targets both zero: send pause."""
        from datetime import datetime, timezone
        class State:
            def __init__(self, value, unit="W"):
                self.state = str(value)
                self.attributes = {"unit_of_measurement": unit, "step": 1,
                                   "min": 0, "max": 16}
                self.last_updated = datetime.now(timezone.utc)
        class States:
            def __init__(self):
                self.data = {"sensor.grid": State(-18547),
                             "sensor.wb1": State(11040),
                             "sensor.wb2": State(7590),
                             "number.wb1": State(0, "A"),
                             "number.wb2": State(0, "A")}
            def get(self, key):
                return self.data.get(key)
        class Services:
            def __init__(self, states):
                self.calls = []
                self.states = states
            async def async_call(self, domain, service, data, blocking=False):
                self.calls.append((domain, service, data))
                self.states.data[data["entity_id"]].state = str(data["value"])
        states = States()
        services = Services(states)
        devices = [{
            "id": f"wb{i}", "name": f"Wallbox {i}",
            "kind": "continuous", "priority": 1, "subpriority": i,
            "min_w": 4140, "max_w": 11040,
            "power_output": f"number.wb{i}",
            "actual_entity": f"sensor.wb{i}",
            "output_unit": "A", "phases": 3, "voltage": 230,
        } for i in (1, 2)]
        hass = types.SimpleNamespace(states=states, services=services)
        entry = types.SimpleNamespace(entry_id="test", data={
            "grid_entity": "sensor.grid", "grid_export_positive": True,
            "interval_s": 15}, options={"devices": devices})
        manager = self.manager_module.PowerManager(hass, entry)
        manager.enable(True)
        asyncio.run(manager.async_cycle())
        self.assertEqual(manager.values["budget"], -18547)
        self.assertEqual(manager.last_targets, {"wb1": 0, "wb2": 0})
        self.assertEqual([c[2]["value"] for c in services.calls], [0.0, 0.0])
        self.assertEqual(manager.per_device["wb1"]["accounted"], 0)
        self.assertEqual(manager.per_device["wb2"]["accounted"], 0)
        asyncio.run(manager.async_cycle())
        self.assertEqual(len(services.calls), 2)
        for key in ("wb1", "wb2"):
            manager._last_zero_write[key] -= 60
        asyncio.run(manager.async_cycle())
        self.assertEqual(len(services.calls), 4)
        self.assertEqual(manager.status, "Aktorabweichung")

    def test_quantized_ampere_command_is_not_repeated(self):
        class State:
            def __init__(self, value, unit):
                self.state=str(value)
                self.attributes={"unit_of_measurement":unit,"min":0,"max":16,"step":1}
        class States:
            def __init__(self):
                self.data={"sensor.grid":State(10000,"W"),"number.wb":State(0,"A")}
            def get(self,key):return self.data.get(key)
        class Services:
            def __init__(self,states):self.states=states;self.calls=[]
            async def async_call(self,domain,service,data,blocking=False):
                self.calls.append(data["value"])
                self.states.data[data["entity_id"]].state=str(data["value"])
        states=States();services=Services(states)
        device={"id":"wb","name":"WB","kind":"continuous","priority":1,
                "subpriority":1,"min_w":4140,"max_w":11040,
                "power_output":"number.wb","output_unit":"A","phases":3,"voltage":230}
        entry=types.SimpleNamespace(entry_id="test",
             data={"grid_entity":"sensor.grid","interval_s":15},
             options={"devices":[device]})
        manager=self.manager_module.PowerManager(
             types.SimpleNamespace(states=states,services=services),entry)
        manager.enable(True)
        asyncio.run(manager.async_cycle())
        # No artificial multiple-cycle ramp: a complete plan is written once.
        self.assertEqual(manager.last_targets["wb"],9660)
        self.assertEqual(services.calls,[14.0])
        states.data["sensor.grid"].state="340"
        asyncio.run(manager.async_cycle())
        self.assertEqual(services.calls,[14.0])
        self.assertEqual(manager.values["assigned"],9660)
        self.assertEqual(manager.values["unallocated"],340)


    def test_manual_ampere_override_is_corrected(self):
        class State:
            def __init__(self,value,unit):
                self.state=str(value)
                self.attributes={"unit_of_measurement":unit,"min":0,"max":16,"step":1}
        class States:
            def __init__(self):
                self.data={"sensor.grid":State(5000,"W"),"number.wb":State(0,"A")}
            def get(self,key):return self.data.get(key)
        class Services:
            def __init__(self,states):self.states=states;self.calls=[]
            async def async_call(self,domain,service,data,blocking=False):
                self.calls.append(data["value"])
                self.states.data[data["entity_id"]].state=str(data["value"])
        states=States();services=Services(states)
        device={"id":"wb","name":"WB","kind":"continuous","priority":1,
            "subpriority":1,"min_w":4140,"max_w":11040,
            "power_output":"number.wb","output_unit":"A","phases":3,"voltage":230}
        entry=types.SimpleNamespace(entry_id="test",
            data={"grid_entity":"sensor.grid","interval_s":15},
            options={"devices":[device]})
        mgr=self.manager_module.PowerManager(
            types.SimpleNamespace(states=states,services=services),entry)
        mgr.enable(True)
        asyncio.run(mgr.async_cycle())
        self.assertEqual(services.calls,[7.0])
        states.data["sensor.grid"].state="170"
        states.data["number.wb"].state="16"
        mgr.last_change["wb"]-=60
        asyncio.run(mgr.async_cycle())
        self.assertEqual(services.calls,[7.0,7.0])


    def test_battery_charging_surplus_does_not_toggle_two_wallboxes(self):
        """With correct negative-on-charge sensor sign, 7 A -> 8 A settles."""
        from datetime import datetime, timezone
        class State:
            def __init__(self, value, unit='W', step=1):
                self.state = str(value)
                self.attributes = {'unit_of_measurement': unit,
                                   'min': 0, 'max': 20000, 'step': step}
                self.last_updated = datetime.now(timezone.utc)
        class States:
            def __init__(self):
                self.data = {
                    'sensor.grid': State(0), 'sensor.batt': State(-1530),
                    'sensor.wb1': State(4830), 'sensor.wb2': State(4830),
                    'number.wp': State(20000), 'number.wb1': State(7, 'A'),
                    'number.wb2': State(7, 'A'),
                }
            def get(self, key):
                return self.data.get(key)
        class Services:
            def __init__(self, states):
                self.states = states
                self.calls = []
            async def async_call(self, domain, service, data, blocking=False):
                self.calls.append((data['entity_id'], data['value']))
                self.states.data[data['entity_id']].state = str(data['value'])
        states = States()
        services = Services(states)
        devices = [{
            'id': 'hp', 'name': 'WP', 'kind': 'continuous',
            'priority': 1, 'subpriority': 1, 'min_w': 5000,
            'max_w': 20000, 'power_output': 'number.wp', 'output_unit': 'W',
        }]
        devices += [{
            'id': f'wb{i}', 'name': f'WB{i}', 'kind': 'continuous',
            'priority': 2, 'subpriority': i, 'min_w': 4140, 'max_w': 11040,
            'power_output': f'number.wb{i}', 'actual_entity': f'sensor.wb{i}',
            'output_unit': 'A', 'phases': 3, 'voltage': 230,
        } for i in (1, 2)]
        entry = types.SimpleNamespace(entry_id='test', data={
            'grid_entity': 'sensor.grid', 'battery_entity': 'sensor.batt',
            'battery_charge_positive': False, 'grid_export_positive': True,
            'interval_s': 15}, options={'devices': devices})
        mgr = self.manager_module.PowerManager(
            types.SimpleNamespace(states=states, services=services), entry)
        mgr.enable(True)
        asyncio.run(mgr.async_cycle())
        self.assertEqual(mgr.values['battery'], 1530)
        self.assertEqual(mgr.values['budget'], 31190)
        self.assertEqual([x for x in services.calls if x[0].startswith('number.wb')],
                         [('number.wb1', 8.0), ('number.wb2', 8.0)])
        for i in (1, 2):
            states.data[f'sensor.wb{i}'].state = '5520'
        states.data['sensor.batt'].state = '-170'
        asyncio.run(mgr.async_cycle())
        self.assertEqual(mgr.values['budget'], 31210)
        self.assertEqual(len(services.calls), 2)

    def test_single_cycle_tolerates_one_watt_deficit(self):
        c=self.engine.Consumer
        devices=[c('hp',1,1,'continuous',5000,20000,old_target=20000,step_w=1),
                 c('wb1',2,1,'continuous',4140,11040,old_target=5520,step_w=690),
                 c('wb2',2,2,'continuous',4140,11040,old_target=5520,step_w=690)]
        old={'hp':20000,'wb1':5520,'wb2':5520}
        from pv_ems_monitoring_tests.control import plan_cycle
        for budget in (31039,30950,31040):
            plan=plan_cycle(0,0,budget,0,devices,old)
            self.assertEqual(plan.targets,old)


    def test_medium_shortage_reduces_in_one_cycle(self):
        from pv_ems_monitoring_tests.control import plan_cycle
        d=self.engine.Consumer('wb',1,1,'continuous',4140,11040,
                               old_target=5520,step_w=690)
        planned=plan_cycle(0,0,5220,0,[d],{'wb':5520})
        self.assertEqual(planned.targets['wb'],4830)


    def test_increase_uses_available_native_step_immediately(self):
        from pv_ems_monitoring_tests.control import plan_cycle
        d=self.engine.Consumer('wb',1,1,'continuous',4140,11040,
                               old_target=4830,step_w=690)
        self.assertEqual(plan_cycle(0,0,5520,0,[d],{'wb':4830}).targets['wb'],5520)


    def test_large_shortage_reduces_immediately(self):
        from pv_ems_monitoring_tests.control import plan_cycle
        d=self.engine.Consumer('wb',1,1,'continuous',4140,11040,
                               old_target=6900,step_w=690)
        self.assertEqual(plan_cycle(0,0,4800,0,[d],{'wb':6900}).targets['wb'],4140)


    def test_priority_and_demand_change_never_held(self):
        from pv_ems_monitoring_tests.control import plan_cycle
        c=self.engine.Consumer
        high=c('high',1,1,'continuous',1000,5000)
        low=c('low',2,1,'continuous',1000,5000,old_target=4000)
        old={'high':0,'low':4000}
        plan=plan_cycle(0,0,3999,0,[high,low],old)
        self.assertEqual(plan.targets['low'],0)
        self.assertGreater(plan.targets['high'],0)
        stopped=c('low',2,1,'continuous',1000,5000,requested=False,old_target=4000)
        plan=plan_cycle(0,0,3999,0,[stopped],{'low':4000})
        self.assertEqual(plan.targets['low'],0)


    def test_large_surplus_reaches_maximum_in_one_cycle_then_reduces(self):
        from datetime import datetime,timezone
        class State:
            def __init__(self,value,unit='W',step=1):
                self.state=str(value);self.attributes={'unit_of_measurement':unit,
                             'min':0,'max':20000,'step':step}
                self.last_updated=datetime.now(timezone.utc)
        class States:
            def __init__(self):
                self.data={'sensor.grid':State(0),'sensor.batt':State(-13080),
                  'sensor.wb1':State(5520),'sensor.wb2':State(5520),
                  'number.hp':State(20000),
                  'number.wb1':State(8,'A'),'number.wb2':State(8,'A')}
            def get(self,key):return self.data.get(key)
        class Services:
            def __init__(self,states):self.states=states;self.calls=[]
            async def async_call(self,domain,service,data,blocking=False):
                self.calls.append((data['entity_id'],data['value']))
                self.states.data[data['entity_id']].state=str(data['value'])
        states=States();services=Services(states)
        devices=[{'id':'hp','name':'WP','kind':'continuous','priority':1,
                  'subpriority':1,'min_w':5000,'max_w':20000,
                  'power_output':'number.hp','output_unit':'W'}]
        devices += [{'id':f'wb{i}','name':f'WB{i}','kind':'continuous',
                     'priority':2,'subpriority':i,'min_w':4140,'max_w':11040,
                     'power_output':f'number.wb{i}',
                     'actual_entity':f'sensor.wb{i}','output_unit':'A',
                     'phases':3,'voltage':230} for i in (1,2)]
        entry=types.SimpleNamespace(entry_id='test',data={
              'grid_entity':'sensor.grid','battery_entity':'sensor.batt',
              'battery_charge_positive':False,'interval_s':15
              },options={'devices':devices})
        mgr=self.manager_module.PowerManager(
             types.SimpleNamespace(states=states,services=services),entry)
        mgr.enable(True)
        asyncio.run(mgr.async_cycle())
        self.assertEqual([x for x in services.calls if x[0].startswith('number.wb')],
                         [('number.wb1',16.0),('number.wb2',16.0)])
        self.assertEqual(mgr.last_targets['wb1'],11040)
        self.assertEqual(mgr.last_targets['wb2'],11040)
        for i in (1,2):states.data[f'sensor.wb{i}'].state='6900'
        states.data['sensor.batt'].state='-2000'
        asyncio.run(mgr.async_cycle())
        self.assertEqual(mgr.values['budget'],35800)
        self.assertEqual(mgr.last_targets['wb1'],7590)
        self.assertEqual(mgr.last_targets['wb2'],7590)


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

    def test_single_cycle_curtails_grid_import_without_second_writer(self):
        from datetime import datetime, timezone
        class State:
            def __init__(self,value,unit='W',step=1):
                self.state=str(value)
                self.attributes={'unit_of_measurement':unit,'min':0,
                                 'max':20000,'step':step}
                self.last_updated=datetime.now(timezone.utc)
        class States:
            def __init__(self):
                self.data={'sensor.grid':State(-8290),'sensor.batt':State(-2940),
                           'sensor.wb1':State(10350),'sensor.wb2':State(10350),
                           'number.hp':State(20000),'number.wb1':State(15,'A'),
                           'number.wb2':State(15,'A')}
            def get(self,entity):return self.data.get(entity)
        class Services:
            def __init__(self,states):self.states=states;self.calls=[]
            async def async_call(self,domain,service,data,blocking=False):
                self.calls.append((data['entity_id'],data['value']))
                self.states.data[data['entity_id']].state=str(data['value'])
        states=States();services=Services(states)
        devices=[{'id':'hp','name':'WP','priority':1,'subpriority':1,
                  'kind':'continuous','min_w':5000,'max_w':20000,
                  'power_output':'number.hp','output_unit':'W'}]
        devices += [{'id':f'wb{i}','name':f'WB{i}','priority':2,
                     'subpriority':i,'kind':'continuous','min_w':4140,
                     'max_w':11040,'power_output':f'number.wb{i}',
                     'actual_entity':f'sensor.wb{i}','output_unit':'A',
                     'phases':3,'voltage':230} for i in (1,2)]
        entry=types.SimpleNamespace(entry_id='test',options={'devices':devices},
            data={'grid_entity':'sensor.grid','battery_entity':'sensor.batt',
                  'grid_export_positive':True,'battery_charge_positive':False,
                  'interval_s':15})
        mgr=self.manager_module.PowerManager(
            types.SimpleNamespace(states=states,services=services),entry)
        mgr.enable(True)
        asyncio.run(mgr.async_cycle())
        self.assertEqual(mgr.values['budget'],35350)
        self.assertEqual(mgr.values['allocation_budget'],32410)
        self.assertEqual(mgr.last_targets['hp'],20000)
        self.assertLessEqual(sum(mgr.last_targets.values()),32410)
        self.assertEqual(len(services.calls),2)
        self.assertTrue(all(name.startswith('number.wb') for name,_ in services.calls))
        self.assertTrue(all(value < 15 for _,value in services.calls))
        self.assertFalse(hasattr(mgr,'async_safety_cycle'))


    def test_one_watt_grid_import_with_battery_charging_does_not_toggle(self):
        from datetime import datetime,timezone
        class State:
            def __init__(self,value,unit='W',step=1):
                self.state=str(value)
                self.attributes={'unit_of_measurement':unit,
                                 'min':0,'max':20000,'step':step}
                self.last_updated=datetime.now(timezone.utc)
        class States:
            def __init__(self):
                self.data={'sensor.grid':State(-1),'sensor.batt':State(-6000),
                           'sensor.wb':State(4830),'number.wb':State(7,'A')}
            def get(self,key):return self.data.get(key)
        class Services:
            def __init__(self,states):self.states=states;self.calls=[]
            async def async_call(self,domain,service,data,blocking=False):
                self.calls.append((data['entity_id'],data['value']))
                self.states.data[data['entity_id']].state=str(data['value'])
        states=States();services=Services(states)
        devices=[{'id':'wb','name':'WB','kind':'continuous','priority':2,
                  'subpriority':1,'min_w':4140,'max_w':11040,
                  'power_output':'number.wb','actual_entity':'sensor.wb',
                  'output_unit':'A','phases':3,'voltage':230}]
        entry=types.SimpleNamespace(entry_id='test',
            data={'grid_entity':'sensor.grid','battery_entity':'sensor.batt',
                  'battery_charge_positive':False,'interval_s':15},
            options={'devices':devices})
        mgr=self.manager_module.PowerManager(
            types.SimpleNamespace(states=states,services=services),entry)
        mgr.enable(True)
        asyncio.run(mgr.async_cycle())
        self.assertEqual(mgr.values['budget'],10829)
        self.assertEqual(mgr.values['allocation_budget'],4830)
        self.assertEqual(mgr.last_targets['wb'],4830)
        self.assertFalse(services.calls)
        states.data['sensor.grid'].state='-2'
        asyncio.run(mgr.async_cycle())
        self.assertEqual(mgr.values['budget'],10828)
        self.assertEqual(mgr.values['allocation_budget'],4830)
        self.assertFalse(services.calls)


    def test_main_controller_can_reallocate_priority_while_importing(self):
        """Import cap must not freeze out a newly requesting higher group."""
        from datetime import datetime, timezone
        class State:
            def __init__(self, value, unit='W'):
                self.state=str(value); self.attributes={'unit_of_measurement':unit,
                  'step':1,'min':0,'max':20000}
                self.last_updated=datetime.now(timezone.utc)
        class States:
            def __init__(self):
                self.data={
                  'sensor.grid':State(-500), 'sensor.batt':State(-3000),
                  'number.high':State(0), 'number.low':State(5000)}
            def get(self,key):return self.data.get(key)
        class Services:
            def __init__(self,states):self.states=states;self.calls=[]
            async def async_call(self,domain,service,data,blocking=False):
                self.calls.append((data['entity_id'],data['value']))
                self.states.data[data['entity_id']].state=str(data['value'])
        states=States();services=Services(states)
        devices=[
          {'id':'high','name':'High','priority':1,'subpriority':1,
           'kind':'continuous','min_w':1000,'max_w':10000,
           'power_output':'number.high','output_unit':'W'},
          {'id':'low','name':'Low','priority':2,'subpriority':1,
           'kind':'continuous','min_w':1000,'max_w':10000,
           'power_output':'number.low','output_unit':'W'}]
        entry=types.SimpleNamespace(entry_id='x',
          data={'grid_entity':'sensor.grid','battery_entity':'sensor.batt',
                'battery_charge_positive':False,'interval_s':15},
          options={'devices':devices})
        manager=self.manager_module.PowerManager(
          types.SimpleNamespace(states=states,services=services),entry)
        manager.enable(True)
        asyncio.run(manager.async_cycle())
        self.assertLessEqual(sum(manager.last_targets.values()),5000)
        self.assertEqual(manager.last_targets['low'],0)
        self.assertGreater(manager.last_targets['high'],0)

    def test_no_parallel_safety_controller_exists(self):
        self.assertFalse(hasattr(self.manager_module.PowerManager,
                                 'async_safety_cycle'))


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

    def test_manager_waits_after_completed_cycle_not_before(self):
        """The single task must not immediately run a second regulation."""
        class State:
            def __init__(self,value):
                self.state=str(value)
                self.attributes={'unit_of_measurement':'kW'}
        async def scenario():
            grid=State(1.0)
            hass=types.SimpleNamespace(
                async_create_task=asyncio.create_task,
                states=types.SimpleNamespace(
                    get=lambda entity: grid if entity=='sensor.grid' else None
                ),
            )
            entry=types.SimpleNamespace(entry_id='test',options={},
                 data={'grid_entity':'sensor.grid','interval_s':15})
            mgr=self.manager_module.PowerManager(hass,entry)
            mgr.start()
            try:
                # The first cycle runs now; subsequent cycles wait after it.
                for _ in range(50):
                    if mgr.values['grid']==1000:
                        break
                    await asyncio.sleep(0.001)
                self.assertEqual(mgr.values['grid'],1000)
                grid.state='3.0'
                await asyncio.sleep(0.02)
                self.assertEqual(mgr.values['grid'],1000)
                self.assertEqual(mgr.status,'Pausiert')
                self.assertEqual(mgr.cycle_count,0)
                self.assertTrue(mgr._loop_running)
                self.assertFalse(hasattr(mgr,'_safety_unsubscribe'))
            finally:
                mgr.stop()
                await asyncio.sleep(0)
            self.assertFalse(mgr._loop_running)

        asyncio.run(scenario())




if __name__ == '__main__':
    unittest.main()
