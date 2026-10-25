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
        class SectionStub:
            def __init__(self, schema, options=None):
                self.schema = schema
                self.options = options or {}

        mock_modules = {
            'voluptuous': mod('voluptuous', Schema=lambda d: d, Required=Marker,
                               Optional=Marker),
            'homeassistant': mod('homeassistant'),
            'homeassistant.config_entries': mod('homeassistant.config_entries',
                 ConfigFlow=DummyFlow, OptionsFlow=DummyFlow),
            'homeassistant.core': mod('homeassistant.core', callback=lambda f: f),
            'homeassistant.data_entry_flow': mod(
                'homeassistant.data_entry_flow', section=SectionStub),
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
            options={'devices': devices or [], 'modbus_connections': [
                {'id':'c', 'name':'Wallbox', 'host':'127.0.0.1', 'port':502, 'unit_id':1}
            ]})
        return flow

    def do_step(self, fn, user_input=None):
        return asyncio.run(fn(user_input))

    def test_clean_top_level_menu(self):
        flow = self.flow()
        menu = self.do_step(flow.async_step_init)
        self.assertEqual(menu['menu_options'], [
            'quick_system_sources', 'quick_consumer_choose',
            'quick_data_points', 'quick_connections',
            'quick_diagnostics', 'advanced'])
        expert=self.do_step(flow.async_step_advanced)
        self.assertLessEqual(len(expert['menu_options']),6)
        datapoints=self.do_step(flow.async_step_quick_data_points)
        self.assertIn('quick_read_point_choose',datapoints['menu_options'])
        connections=self.do_step(flow.async_step_quick_connections)
        self.assertIn('modbus_connection',connections['menu_options'])

    def test_first_installation_without_any_sensor_creates_config_entry(self):
        flow = self.flow_mod.PVConfigFlow()
        flow._async_current_entries = lambda: []
        form = self.do_step(flow.async_step_user)
        self.assertEqual(form['type'], 'form')
        self.assertEqual(list(form['data_schema'].keys()), ['grid_entity'])
        saved = self.do_step(flow.async_step_user, {})
        self.assertEqual(saved['type'], 'create_entry')
        self.assertNotIn('grid_entity', saved['data'])
        self.assertEqual(saved['data']['interval_s'], 15)

    def test_first_installation_accepts_preexisting_grid(self):
        flow = self.flow_mod.PVConfigFlow()
        flow._async_current_entries = lambda: []
        saved = self.do_step(flow.async_step_user, {'grid_entity':'sensor.grid'})
        self.assertEqual(saved['data']['grid_entity'], 'sensor.grid')

    def test_new_modbus_source_menu_before_grid_sensor_exists(self):
        flow = self.flow()
        flow.config_entry.data = {}
        flow.config_entry.options['modbus_connections'] = []
        menu = self.do_step(flow.async_step_quick_modbus_setup)
        self.assertEqual(menu['menu_options'],
            ['quick_connections','quick_read_point_choose','quick_system_sources'])
        selection=self.do_step(flow.async_step_quick_read_point_choose)
        self.assertEqual(selection['type'],'menu')
        self.assertIn('modbus_connection',selection['menu_options'])
        flow.config_entry.options['modbus_connections'] = [
            {'id':'new', 'name':'PV', 'host':'127.0.0.1','port':502,'unit_id':1}]
        selection=self.do_step(flow.async_step_quick_read_point_choose)
        self.assertEqual(selection['type'],'form')

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

    def sections(self, **changes):
        sections = {
            'basics': {'name':'Wallbox 1','kind':'continuous','priority':2,
                       'subpriority':1,'min_w':4140,'max_w':11040,
                       'steps_w':'500,1000,1500,2000'},
            'actuator': {'power_output':'number.wallbox','output_unit':'A',
                         'phases':'3','voltage':230},
            'feedback': {'actual_entity':'sensor.real_power'},
            'timing': {'start_delay_s':0,'min_on_s':0,'min_off_s':0},
            'confirm':True,
        }
        for name, values in changes.items():
            sections[name] = values
        return sections

    def test_consumer_one_form_with_native_sections_not_navigation(self):
        flow=self.flow()
        response=self.do_step(flow.async_step_quick_consumer_choose,
                              {'consumer':'new'})
        self.assertEqual(response['step_id'],'quick_consumer_form')
        schema=response['data_schema']
        self.assertEqual(list(schema),['basics','actuator','feedback',
                                       'timing','confirm'])
        for name in ('basics','actuator','feedback','timing'):
            self.assertTrue(hasattr(schema[name], 'schema'))
            self.assertNotIn('wizard_navigation',schema[name].schema)
        self.assertFalse(schema['basics'].options['collapsed'])
        self.assertTrue(schema['timing'].options['collapsed'])
        self.assertTrue(schema['feedback'].options['collapsed'])

    def test_existing_consumer_can_be_reconfigured_preserving_id(self):
        old = {'id':'old1', 'name':'Wallbox', 'kind':'continuous', 'priority':2,
               'subpriority':1, 'min_w':4140,'max_w':11040,
               'power_output':'number.wallbox', 'output_unit':'A',
               'phases':3, 'voltage':230, 'min_on_s':90}
        flow=self.flow([old])
        self.do_step(flow.async_step_quick_consumer_choose,
                     {'consumer':'old1'})
        form=self.do_step(flow.async_step_quick_consumer_form)
        self.assertEqual(form['step_id'],'quick_consumer_form')
        changed=self.sections(
            basics={**self.sections()['basics'],'name':'Wallbox 1',
                    'priority':1},
            timing={'start_delay_s':0,'min_on_s':90,'min_off_s':0},
        )
        saved=self.do_step(flow.async_step_quick_consumer_form,changed)
        self.assertEqual(saved['type'],'create_entry')
        self.assertEqual(len(saved['data']['devices']),1)
        value=saved['data']['devices'][0]
        self.assertEqual(value['id'],'old1')
        self.assertEqual(value['min_on_s'],90)
        self.assertEqual(value['actual_entity'],'sensor.real_power')
        self.assertEqual(value['name'],'Wallbox 1')
        self.assertEqual(value['priority'],1)

    def test_validation_error_retains_every_section_and_is_correctable(self):
        flow=self.flow()
        self.do_step(flow.async_step_quick_consumer_choose,{'consumer':'new'})
        invalid=self.sections(
            basics={**self.sections()['basics'],'max_w':4000})
        response=self.do_step(flow.async_step_quick_consumer_form,invalid)
        self.assertEqual(response['step_id'],'quick_consumer_form')
        self.assertEqual(response['errors']['base'],'limits')
        self.assertEqual(flow._quick_consumer_draft['max_w'],4000)
        corrected=self.sections()
        saved=self.do_step(flow.async_step_quick_consumer_form,corrected)
        self.assertEqual(saved['type'],'create_entry')
        self.assertEqual(saved['data']['devices'][0]['max_w'],11040)

    def test_unconfirmed_and_incompatible_actuator_cannot_be_saved(self):
        flow=self.flow()
        self.do_step(flow.async_step_quick_consumer_choose,{'consumer':'new'})
        values=self.sections(confirm=False)
        denied=self.do_step(flow.async_step_quick_consumer_form,values)
        self.assertEqual(denied['errors']['base'],'confirm_required')
        wrong=self.sections(
            actuator={**self.sections()['actuator'],'output_unit':'W'})
        response=self.do_step(flow.async_step_quick_consumer_form,wrong)
        self.assertEqual(response['type'],'form')
        self.assertEqual(response['errors']['base'],'actuator_unit_mismatch')

    def test_bad_ampere_minimum_suggests_fix_in_same_form(self):
        flow=self.flow()
        self.do_step(flow.async_step_quick_consumer_choose,{'consumer':'new'})
        invalid=self.sections(
            basics={**self.sections()['basics'],'min_w':4000})
        response=self.do_step(flow.async_step_quick_consumer_form,invalid)
        self.assertEqual(response['errors']['base'],'actuator_step_mismatch')
        self.assertIn('4140 W',response['description_placeholders']['hint'])
        corrected=self.do_step(flow.async_step_quick_consumer_form,
                              self.sections())
        self.assertEqual(corrected['type'],'create_entry')

    def test_optional_source_cleared_on_edit_without_restoring_old(self):
        old={'id':'wb','name':'Wallbox','kind':'continuous','priority':2,
             'subpriority':1,'min_w':4140,'max_w':11040,
             'power_output':'number.wallbox','output_unit':'A',
             'phases':3,'voltage':230,
             'actual_entity':'sensor.real_power',
             'demand_entity':'input_boolean.old'}
        flow=self.flow([old])
        self.do_step(flow.async_step_quick_consumer_choose,{'consumer':'wb'})
        edited=self.sections(feedback={})
        result=self.do_step(flow.async_step_quick_consumer_form,edited)
        self.assertEqual(result['type'],'create_entry')
        self.assertNotIn('actual_entity',result['data']['devices'][0])
        self.assertNotIn('demand_entity',result['data']['devices'][0])
        self.assertEqual(result['data']['devices'][0]['id'],'wb')

    def test_existing_output_cannot_be_shared_by_two_consumers(self):
        old={'id':'existing','name':'Other','kind':'continuous','priority':1,
             'subpriority':1,'min_w':4140,'max_w':11040,
             'power_output':'number.wallbox','output_unit':'A',
             'phases':3,'voltage':230}
        flow=self.flow([old])
        self.do_step(flow.async_step_quick_consumer_choose,{'consumer':'new'})
        result=self.do_step(flow.async_step_quick_consumer_form,self.sections())
        self.assertEqual(result['errors']['base'],'duplicate_output')

    def test_onoff_switch_does_not_require_number_output(self):
        flow=self.flow()
        flow.hass.states.data['switch.heater']=types.SimpleNamespace(
            state='off',attributes={})
        self.do_step(flow.async_step_quick_consumer_choose,{'consumer':'new'})
        inp=self.sections(
            basics={**self.sections()['basics'],'name':'Heater',
                    'kind':'onoff','min_w':2000,'max_w':2000},
            actuator={'switch_output':'switch.heater','output_unit':'W',
                      'phases':'1','voltage':230},
            feedback={},
        )
        result=self.do_step(flow.async_step_quick_consumer_form,inp)
        self.assertEqual(result['type'],'create_entry')
        self.assertEqual(result['data']['devices'][0]['kind'],'onoff')
        self.assertNotIn('power_output',result['data']['devices'][0])



if __name__ == '__main__':
    unittest.main()
