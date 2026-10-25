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

    def test_review_can_adopt_suggested_minimum_and_save(self):
        flow = self.flow()
        self.do_step(flow.async_step_quick_consumer_choose, {'consumer':'new'})
        self.do_step(flow.async_step_quick_consumer_basics, {
            'name':'WB1','kind':'continuous','priority':2,'subpriority':1,
            'min_w':4000,'max_w':11000})
        self.do_step(flow.async_step_quick_consumer_output, {
            'power_output':'number.wallbox','output_unit':'A'})
        self.do_step(flow.async_step_quick_consumer_conversion, {'phases':'3','voltage':230})
        self.do_step(flow.async_step_quick_consumer_feedback, {'actual_entity':'sensor.real_power'})
        before = self.do_step(flow.async_step_quick_consumer_review)
        self.assertIn('4140',before['description_placeholders']['range_hint'])
        corrected = self.do_step(flow.async_step_quick_consumer_review, {'review_action':'fix_minimum'})
        self.assertEqual(corrected['type'],'form')
        self.assertEqual(flow._quick_basics['min_w'],4140)
        saved = self.do_step(flow.async_step_quick_consumer_review, {'confirm':True})
        self.assertEqual(saved['type'],'create_entry')
        self.assertEqual(saved['data']['devices'][0]['min_w'],4140)

    def test_summary_back_to_limits_without_losing_output(self):
        flow = self.flow()
        self.do_step(flow.async_step_quick_consumer_choose, {'consumer':'new'})
        self.do_step(flow.async_step_quick_consumer_basics, {
            'name':'WB1','kind':'continuous','priority':2,'subpriority':1,
            'min_w':4000,'max_w':11000})
        self.do_step(flow.async_step_quick_consumer_output, {
            'power_output':'number.wallbox','output_unit':'A'})
        self.do_step(flow.async_step_quick_consumer_conversion, {'phases':'3','voltage':230})
        self.do_step(flow.async_step_quick_consumer_feedback, {'actual_entity':'sensor.real_power'})
        back = self.do_step(flow.async_step_quick_consumer_review, {'review_action':'edit_limits'})
        self.assertEqual(back['step_id'], 'quick_consumer_basics')
        self.assertEqual(flow._quick_basics['min_w'],4000)
        self.assertEqual(flow._quick_output['power_output'],'number.wallbox')
        self.assertEqual(flow._quick_feedback['actual_entity'],'sensor.real_power')

    def read_input(self, **kw):
        result = dict(connection_id='c', name='Netzleistung', address=100,
                      function_code='3', data_type='uint16', byte_order='ABCD',
                      scale=1.0, offset=0, unit='W', poll_seconds=5)
        result.update(kw)
        return result

    @staticmethod
    def modbus_stub(values=None, error=None):
        class Unit:
            async def read_holding_registers(self, addr, count):
                if error:
                    raise ConnectionError(error)
                return list(values if values is not None else [1250])
            async def read_input_registers(self, addr, count):
                return await self.read_holding_registers(addr,count)
        class Context:
            async def __aenter__(self):return Unit()
            async def __aexit__(self,*args):return False
        return {
            'homeassistant.components': mod('homeassistant.components'),
            'homeassistant.components.modbus': mod(
                'homeassistant.components.modbus',
                async_get_temporary_unit=lambda *args, **kwargs: Context()),
            'modbus_connection': mod('modbus_connection',
                ModbusTcpParams=lambda **kwargs: kwargs),
        }

    def test_new_modbus_sensor_test_correct_retest_save(self):
        flow=self.flow()
        selection=self.do_step(flow.async_step_quick_read_point_choose,
                               {'register_id':'new'})
        self.assertEqual(selection['step_id'],'quick_read_point_form')
        self.assertEqual(flow.config_entry.options.get('modbus_registers'),None)
        # Saving before any test is refused and does not create a sensor.
        denied=self.do_step(flow.async_step_quick_read_point_form,
                            self.read_input(wizard_action='save'))
        self.assertEqual(denied['errors']['base'],'read_test_required')
        self.assertFalse(flow.config_entry.options.get('modbus_registers'))
        # Successful live test returns to exactly the same editable form.
        with patch.dict(sys.modules,self.modbus_stub([1250])):
            result=self.do_step(flow.async_step_quick_read_point_form,
                                self.read_input(wizard_action='test'))
        self.assertEqual(result['step_id'],'quick_read_point_form')
        self.assertIn('1250',result['description_placeholders']['result'])
        self.assertIsNone(result['errors'].get('base'))
        self.assertFalse(flow.config_entry.options.get('modbus_registers'))
        # Corrections require retesting; no stale successful test accepted.
        refused=self.do_step(flow.async_step_quick_read_point_form,
                     self.read_input(scale=0.1,wizard_action='save'))
        self.assertEqual(refused['errors']['base'],'read_test_required')
        with patch.dict(sys.modules,self.modbus_stub([1250])):
            retested=self.do_step(flow.async_step_quick_read_point_form,
                         self.read_input(scale=0.1,wizard_action='test'))
        self.assertIn('125',retested['description_placeholders']['result'])
        saved=self.do_step(flow.async_step_quick_read_point_form,
                           self.read_input(scale=0.1,wizard_action='save'))
        self.assertEqual(saved['type'],'create_entry')
        self.assertEqual(len(saved['data']['modbus_registers']),1)
        self.assertEqual(saved['data']['modbus_registers'][0]['scale'],0.1)
        self.assertTrue(saved['data']['modbus_registers'][0]['id'])

    def test_failed_modbus_read_can_be_corrected_without_persisting(self):
        flow=self.flow()
        self.do_step(flow.async_step_quick_read_point_choose,{'register_id':'new'})
        with patch.dict(sys.modules,self.modbus_stub(error='device offline')):
            failed=self.do_step(flow.async_step_quick_read_point_form,
                           self.read_input(address=50,wizard_action='test'))
        self.assertEqual(failed['errors']['base'],'read_test_failed')
        self.assertIn('device offline',failed['description_placeholders']['result'])
        self.assertEqual(flow._quick_read_draft['address'],50)
        self.assertFalse(flow.config_entry.options.get('modbus_registers'))
        with patch.dict(sys.modules,self.modbus_stub([777])):
            corrected=self.do_step(flow.async_step_quick_read_point_form,
                           self.read_input(address=51,wizard_action='test'))
        self.assertIn('777',corrected['description_placeholders']['result'])
        saved=self.do_step(flow.async_step_quick_read_point_form,
                           self.read_input(address=51,wizard_action='save'))
        self.assertEqual(saved['data']['modbus_registers'][0]['address'],51)

    def test_existing_sensor_edit_preserves_id_and_others(self):
        flow=self.flow()
        old=self.read_input()
        old['id']='keep-this-id'
        other=self.read_input(id='untouched',name='Batterie',address=200)
        flow.config_entry.options['modbus_registers']=[old,other]
        selected=self.do_step(flow.async_step_quick_read_point_choose,
                              {'register_id':'keep-this-id'})
        self.assertEqual(selected['step_id'],'quick_read_point_form')
        self.assertEqual(flow._quick_read_draft['address'],100)
        # Existing registry is still untouched after a test.
        with patch.dict(sys.modules,self.modbus_stub([987])):
            test=self.do_step(flow.async_step_quick_read_point_form,
                              self.read_input(address=101,wizard_action='test'))
        self.assertIn('987',test['description_placeholders']['result'])
        self.assertEqual(flow.config_entry.options['modbus_registers'][0]['address'],100)
        saved=self.do_step(flow.async_step_quick_read_point_form,
                              self.read_input(address=101,wizard_action='save'))
        values=saved['data']['modbus_registers']
        self.assertEqual(values[0]['id'],'keep-this-id')
        self.assertEqual(values[0]['address'],101)
        self.assertEqual(values[1],other)

    def test_sensor_wizard_back_does_not_modify_configuration(self):
        flow=self.flow()
        self.do_step(flow.async_step_quick_read_point_choose,{'register_id':'new'})
        result=self.do_step(flow.async_step_quick_read_point_form,
                            self.read_input(wizard_action='back'))
        self.assertEqual(result['step_id'],'quick_read_point_choose')
        self.assertFalse(flow.config_entry.options.get('modbus_registers'))

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
