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
            'quick_site_form', 'quick_consumer_choose',
            'quick_connections', 'quick_data_points',
            'quick_diagnostics', 'advanced'])
        expert=self.do_step(flow.async_step_advanced)
        self.assertLessEqual(len(expert['menu_options']),6)
        datapoints=self.do_step(flow.async_step_quick_data_points)
        self.assertEqual(datapoints['menu_options'],
                         ['quick_read_point_choose','quick_write_point_choose',
                          'quick_delete_point'])
        connections=self.do_step(flow.async_step_quick_connections)
        self.assertIn('quick_connection_choose',connections['menu_options'])

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
            ['quick_connections','quick_read_point_choose','quick_site_form'])
        selection=self.do_step(flow.async_step_quick_read_point_choose)
        self.assertEqual(selection['type'],'menu')
        self.assertIn('modbus_connection',selection['menu_options'])
        flow.config_entry.options['modbus_connections'] = [
            {'id':'new', 'name':'PV', 'host':'127.0.0.1','port':502,'unit_id':1}]
        selection=self.do_step(flow.async_step_quick_read_point_choose)
        self.assertEqual(selection['type'],'form')

    def test_site_single_form_sections_and_no_intermediate_saves(self):
        flow=self.flow()
        form=self.do_step(flow.async_step_quick_site_form)
        self.assertEqual(list(form['data_schema']),
                         ['sources','directions','regulation','confirm'])
        self.assertFalse(form['data_schema']['sources'].options['collapsed'])
        values={'sources':{'grid_entity':'sensor.grid',
                           'battery_entity':'sensor.real_power'},
                'directions':{'grid_export_positive':True,
                              'battery_charge_positive':False},
                'regulation':{'interval_s':15,'reserve_w':0,
                              'feedback_settle_s':15},'confirm':False}
        pending=self.do_step(flow.async_step_quick_site_form,values)
        self.assertEqual(pending['errors']['base'],'confirm_required')
        self.assertIn('Netzbezug: 13.590 W',
                      pending['description_placeholders']['preview'])
        saved=self.do_step(flow.async_step_quick_site_form,
                           {**values,'confirm':True})
        self.assertEqual(saved['type'],'create_entry')
        self.assertEqual(saved['data']['devices'],[])
        self.assertEqual(saved['data']['grid_entity'],'sensor.grid')
        self.assertFalse(saved['data']['battery_charge_positive'])

    def test_site_can_clear_an_existing_optional_sensor(self):
        flow=self.flow()
        flow.config_entry.data['battery_entity']='sensor.old'
        self.do_step(flow.async_step_quick_site_form)
        saved=self.do_step(flow.async_step_quick_site_form,
            {'sources':{'grid_entity':'sensor.grid'},'confirm':True})
        self.assertIsNone(saved['data']['battery_entity'])

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


    def read_input(self, action='test', **updates):
        r=dict(connection_id='c',name='Leistung',address=100,
               function_code='3',data_type='uint16',byte_order='ABCD',
               scale=1.0,offset=0,unit='W',poll_seconds=5)
        r.update(updates)
        return {'addressing':{k:r[k] for k in (
                    'connection_id','name','address','function_code')},
                'decoding':{k:r[k] for k in (
                    'data_type','byte_order','scale','offset','unit')},
                'sampling':{'poll_seconds':r['poll_seconds']},
                'wizard_action':action}

    @staticmethod
    def modbus_stub(value=1250,fail=False):
        class Unit:
            async def read_holding_registers(self,addr,count):
                if fail: raise ConnectionError('offline')
                return [value]
            async def read_input_registers(self,addr,count):
                return await self.read_holding_registers(addr,count)
        class Context:
            async def __aenter__(self):return Unit()
            async def __aexit__(self,*args):return False
        return {
            'homeassistant.components': mod('homeassistant.components'),
            'homeassistant.components.modbus': mod(
                'homeassistant.components.modbus',
                async_get_temporary_unit=lambda *a,**kw: Context()),
            'modbus_connection': mod('modbus_connection',
                 ModbusTcpParams=lambda **kw:kw),
        }

    def test_read_points_test_correct_retest_save_and_preserve_id(self):
        flow=self.flow()
        old=dict(name='Netz',connection_id='c',address=100,
            function_code=3,data_type='uint16',byte_order='ABCD',
            scale=1.0,offset=0,unit='W',poll_seconds=5,id='keep')
        flow.config_entry.options['modbus_registers']=[old]
        chosen=self.do_step(flow.async_step_quick_read_point_choose,
                            {'register_id':'keep'})
        self.assertEqual(chosen['step_id'],'quick_read_point_form')
        form=self.do_step(flow.async_step_quick_read_point_form)
        self.assertEqual(list(form['data_schema']),
                         ['addressing','decoding','sampling','wizard_action'])
        denied=self.do_step(flow.async_step_quick_read_point_form,
                            self.read_input('save',address=101))
        self.assertEqual(denied['errors']['base'],'read_test_required')
        with patch.dict(sys.modules,self.modbus_stub()):
            tested=self.do_step(flow.async_step_quick_read_point_form,
                                 self.read_input('test',address=101))
        self.assertIn('1250',tested['description_placeholders']['result'])
        stale=self.do_step(flow.async_step_quick_read_point_form,
                            self.read_input('save',address=102))
        self.assertEqual(stale['errors']['base'],'read_test_required')
        with patch.dict(sys.modules,self.modbus_stub(fail=True)):
            failed=self.do_step(flow.async_step_quick_read_point_form,
                                 self.read_input('test',address=102))
        self.assertEqual(failed['errors']['base'],'read_test_failed')
        with patch.dict(sys.modules,self.modbus_stub(value=777)):
            retest=self.do_step(flow.async_step_quick_read_point_form,
                                 self.read_input('test',address=102))
        self.assertIn('777',retest['description_placeholders']['result'])
        self.assertEqual(flow.config_entry.options['modbus_registers'][0]['address'],100)
        saved=self.do_step(flow.async_step_quick_read_point_form,
                            self.read_input('save',address=102))
        self.assertEqual(saved['type'],'create_entry')
        self.assertEqual(saved['data']['modbus_registers'][0]['id'],'keep')
        self.assertEqual(saved['data']['modbus_registers'][0]['address'],102)

    def test_write_points_new_and_edit_sectioned_no_commands(self):
        flow=self.flow()
        new=self.do_step(flow.async_step_quick_write_point_choose,
                         {'write_id':'new'})
        self.assertEqual(new['step_id'],'quick_write_point_form')
        form=self.do_step(flow.async_step_quick_write_point_form)
        self.assertEqual(list(form['data_schema']),
                         ['addressing','limits','encoding','confirm'])
        inp={'addressing':{'connection_id':'c','name':'Wallbox',
                 'address':100,'function_code':'16','data_type':'float32',
                 'byte_order':'ABCD'},
             'limits':{'unit':'A','active_min':6,'active_max':16,
                       'step':1,'off_value':0},
             'encoding':{'scale':1,'offset':0},'confirm':True}
        saved=self.do_step(flow.async_step_quick_write_point_form,inp)
        self.assertEqual(saved['type'],'create_entry')
        added=saved['data']['modbus_write_points'][0]
        self.assertTrue(added['id'])
        flow.config_entry.options['modbus_write_points']=[added]
        edited=self.do_step(flow.async_step_quick_write_point_choose,
                            {'write_id':added['id']})
        self.assertEqual(edited['step_id'],'quick_write_point_form')
        inp['limits']['active_max']=15
        updated=self.do_step(flow.async_step_quick_write_point_form,inp)
        self.assertEqual(updated['data']['modbus_write_points'][0]['id'],added['id'])
        self.assertEqual(updated['data']['modbus_write_points'][0]['active_max'],15)

    def test_connection_new_edit_same_form(self):
        flow=self.flow()
        self.do_step(flow.async_step_quick_connection_choose,
                     {'connection_id':'new'})
        form=self.do_step(flow.async_step_quick_connection_form)
        self.assertIn('device',form['data_schema'])
        saved=self.do_step(flow.async_step_quick_connection_form,
            {'device':{'name':'PV','host':'pv.local','port':502,'unit_id':1},
             'confirm':True})
        connection=saved['data']['modbus_connections'][-1]
        self.assertEqual(connection['host'],'pv.local')
        flow.config_entry.options['modbus_connections']=saved['data']['modbus_connections']
        self.do_step(flow.async_step_quick_connection_choose,
                     {'connection_id':connection['id']})
        updated=self.do_step(flow.async_step_quick_connection_form,
            {'device':{'name':'PV','host':'pv-new.local','port':502,'unit_id':1},
             'confirm':True})
        self.assertEqual(updated['data']['modbus_connections'][-1]['id'],
                         connection['id'])

    def test_deletion_requires_confirmation_for_either_type(self):
        flow=self.flow()
        read={'id':'r1','name':'PV'}
        write={'id':'w1','name':'Wallbox'}
        flow.config_entry.options['modbus_registers']=[read]
        flow.config_entry.options['modbus_write_points']=[write]
        form=self.do_step(flow.async_step_quick_delete_point)
        self.assertEqual(form['type'],'form')
        denied=self.do_step(flow.async_step_quick_delete_point,
            {'point_id':'write:w1','confirm':False})
        self.assertEqual(denied['errors']['base'],'confirm_required')
        removed=self.do_step(flow.async_step_quick_delete_point,
            {'point_id':'write:w1','confirm':True})
        self.assertEqual(removed['data']['modbus_write_points'],[])
        self.assertEqual(removed['data']['modbus_registers'],[read])

    def test_deletion_blocks_data_points_assigned_to_site(self):
        flow=self.flow()
        flow.config_entry.entry_id='test'
        flow.config_entry.options['modbus_registers']=[{
            'id':'r1','name':'Netz'}]
        registry=types.SimpleNamespace(
            async_get_entity_id=lambda domain,platform,unique_id:
                'sensor.grid' if unique_id=='test_mb_r1' else None)
        module=mod('homeassistant.helpers.entity_registry',
                   async_get=lambda hass:registry)
        with patch.dict(sys.modules,{'homeassistant.helpers.entity_registry':module}):
            result=self.do_step(flow.async_step_quick_delete_point,
                {'point_id':'read:r1','confirm':True})
        self.assertEqual(result['errors']['base'],'point_in_use')
        self.assertEqual(flow.config_entry.options['modbus_registers'][0]['id'],'r1')



if __name__ == '__main__':
    unittest.main()
