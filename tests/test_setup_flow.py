"""Exercise HA OptionsFlow transitions using lightweight UI mocks, no HA runtime."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/pv_energiemanager'
PKG = 'pv_ha_options_wizard_tests'


def mod(name, **fields):
    m = types.ModuleType(name)
    for k, v in fields.items():
        setattr(m, k, v)
    return m


class Marker(str):
    def __new__(cls, name, **opts):
        return str.__new__(cls, name)


class Selector:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class DummyFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def async_show_form(self, **kwargs):
        return {'type': 'form', **kwargs}

    def async_show_menu(self, **kwargs):
        return {'type': 'menu', **kwargs}

    def async_create_entry(self, **kwargs):
        return {'type': 'create_entry', **kwargs}

    def async_abort(self, **kwargs):
        return {'type': 'abort', **kwargs}


def import_file(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'{name.split(".")[-1]}.py')
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


class WizardFlowTests(unittest.TestCase):
    def setUp(self):
        mock_modules = {
            'voluptuous': mod('voluptuous', Schema=lambda d: d, Required=Marker,
                               Optional=Marker),
            'homeassistant': mod('homeassistant'),
            'homeassistant.config_entries': mod('homeassistant.config_entries',
                 ConfigFlow=DummyFlow, OptionsFlow=DummyFlow),
            'homeassistant.core': mod('homeassistant.core', callback=lambda f: f),
            'homeassistant.helpers': mod('homeassistant.helpers'),
            'homeassistant.helpers.selector': mod('homeassistant.helpers.selector',
                 EntitySelector=Selector, EntitySelectorConfig=Selector,
                 NumberSelector=Selector, NumberSelectorConfig=Selector,
                 TextSelector=Selector, BooleanSelector=Selector,
                 SelectSelector=Selector, SelectSelectorConfig=Selector,
                 SelectOptionDict=lambda **kw: kw),
            PKG: mod(PKG),
        }
        mock_modules['homeassistant'].config_entries = mock_modules['homeassistant.config_entries']
        mock_modules['homeassistant.helpers'].selector = mock_modules['homeassistant.helpers.selector']
        mock_modules[PKG].__path__ = [str(ROOT)]
        self.patcher = patch.dict(sys.modules, mock_modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        for name in ('const', 'modbus_codec', 'modbus_validation', 'modbus_writer', 'setup_wizard'):
            import_file(f'{PKG}.{name}')
        self.flow_mod = import_file(f'{PKG}.config_flow')

    def flow(self, devices=None):
        class States:
            data = {
                'sensor.grid': types.SimpleNamespace(state='-13.59',
                       attributes={'unit_of_measurement': 'kW'}),
                'sensor.real_power': types.SimpleNamespace(state='9660',
                       attributes={'unit_of_measurement': 'W'}),
                'number.wallbox': types.SimpleNamespace(state='6',
                       attributes={'unit_of_measurement': 'A', 'min': 0, 'max': 16, 'step': 1}),
            }
            def get(self, entity_id):
                return self.data.get(entity_id)
        flow = self.flow_mod.PVOptionsFlow()
        flow.hass = types.SimpleNamespace(states=States())
        flow.config_entry = types.SimpleNamespace(
            data={'grid_entity': 'sensor.grid', 'grid_export_positive': True},
            options={'devices': devices or [], 'modbus_connections': [{'id':'c', 'name':'Wallbox'}]})
        return flow

    def do_step(self, fn, user_input=None):
        return asyncio.run(fn(user_input))

    def test_clean_top_level_menu(self):
        flow = self.flow()
        menu = self.do_step(flow.async_step_init)
        self.assertEqual(menu['menu_options'], [
            'quick_system_sources', 'quick_consumer_choose', 'quick_diagnostics', 'advanced'])

    def test_site_wizard_previews_direction_without_writing(self):
        flow = self.flow()
        self.do_step(flow.async_step_quick_system_sources, {'grid_entity':'sensor.grid'})
        self.do_step(flow.async_step_quick_system_direction, {'grid_sign':'plus_export',
                  'battery_sign':'plus_charge', 'interval_s':15, 'reserve_w':0})
        preview = self.do_step(flow.async_step_quick_system_review)
        self.assertIn('Netzbezug: 13.590 W', preview['description_placeholders']['net'])
        saved = self.do_step(flow.async_step_quick_system_review, {'confirm':True})
        self.assertEqual(saved['type'], 'create_entry')
        self.assertTrue(saved['data']['grid_export_positive'])
        self.assertEqual(saved['data']['devices'], [])

    def test_existing_consumer_can_be_reconfigured_preserving_id(self):
        old = {'id':'old1', 'name':'Wallbox', 'kind':'continuous', 'priority':2,
               'subpriority':1, 'min_w':4140,'max_w':11040,
               'power_output':'number.wallbox', 'output_unit':'A',
               'phases':3, 'voltage':230, 'min_on_s':90}
        flow = self.flow([old])
        self.do_step(flow.async_step_quick_consumer_choose, {'consumer':'old1'})
        self.do_step(flow.async_step_quick_consumer_basics, {'name':'Wallbox 1',
                 'kind':'continuous', 'priority':1,'subpriority':1,
                 'min_w':4140,'max_w':11040})
        self.do_step(flow.async_step_quick_consumer_output, {
            'power_output':'number.wallbox', 'output_unit':'A'})
        self.do_step(flow.async_step_quick_consumer_conversion, {'phases':'3','voltage':230})
        self.do_step(flow.async_step_quick_consumer_feedback, {'actual_entity':'sensor.real_power'})
        summary = self.do_step(flow.async_step_quick_consumer_review)
        self.assertIn('number.wallbox', summary['description_placeholders']['actor'])
        saved = self.do_step(flow.async_step_quick_consumer_review, {'confirm':True})
        self.assertEqual(saved['type'],'create_entry')
        self.assertEqual(len(saved['data']['devices']),1)
        value = saved['data']['devices'][0]
        self.assertEqual(value['id'],'old1')
        self.assertEqual(value['min_on_s'],90)
        self.assertEqual(value['actual_entity'],'sensor.real_power')

    def test_wrong_unit_blocks_save(self):
        flow = self.flow()
        self.do_step(flow.async_step_quick_consumer_choose, {'consumer':'new'})
        self.do_step(flow.async_step_quick_consumer_basics, {'name':'Wallbox',
                 'kind':'continuous','priority':1,'subpriority':1,
                 'min_w':4140,'max_w':11040})
        self.do_step(flow.async_step_quick_consumer_output, {'power_output':'number.wallbox',
                                                        'output_unit':'W'})
        self.do_step(flow.async_step_quick_consumer_feedback, {})
        result = self.do_step(flow.async_step_quick_consumer_review, {'confirm':True})
        self.assertEqual(result['type'],'form')
        self.assertEqual(result['errors']['base'],'actuator_unit_mismatch')


if __name__ == '__main__':
    unittest.main()
