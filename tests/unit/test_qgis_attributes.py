"""Literal attribute semantics; these tests do not import QGIS or imply native qualification."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.adaptors.qgis import attributes as contract
from schemaxis.core.declarations import validate_arguments

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT/'examples/schemaxis/fixtures/qgis/assets.geojson'


class AttributeContractTests(unittest.TestCase):
    def setUp(self):
        self.rows = [f['properties'] for f in json.loads(FIXTURE.read_text())['features']]
        self.fields = list(self.rows[0])
        self.document = json.loads((ROOT/'examples/schemaxis/qgis-attributes.json').read_text())
        self.select = validate_arguments(contract.OPTIONS['selectAttributes'], self.document['nodes'][1]['options'])
        self.summary = self.document['nodes'][2]['options']

    def test_literal_threshold_group_null_and_units(self):
        selected = contract.select(self.rows, self.fields, self.select, 'eligible.options')
        self.assertEqual(selected, ['b','c','e','g','h','i'])
        table = contract.summarise([r for r in self.rows if r['asset_id'] in selected], self.fields, self.summary, 'regional_load.options')
        self.assertEqual(table['rows'], [
            {'group':None,'groupIsNull':True,'memberIds':['e'],'assets':1,'valid_loads':1,'total_kw':2,'mean_kw':2},
            {'group':'','groupIsNull':False,'memberIds':['i'],'assets':1,'valid_loads':1,'total_kw':3,'mean_kw':3},
            {'group':'empty','groupIsNull':False,'memberIds':['h'],'assets':1,'valid_loads':0,'total_kw':None,'mean_kw':None},
            {'group':'north','groupIsNull':False,'memberIds':['b','g'],'assets':2,'valid_loads':1,'total_kw':6,'mean_kw':6},
            {'group':'south','groupIsNull':False,'memberIds':['c'],'assets':1,'valid_loads':1,'total_kw':4,'mean_kw':4}])
        self.assertEqual([c['units'] for c in table['columns']], ['unitless','unitless','unitless','features','features','kW','kW'])
        self.assertIn(',true,', contract.csv_text(table)); self.assertIn(',false,', contract.csv_text(table))
        self.assertEqual(contract.summarise(list(reversed(self.rows)), self.fields, self.summary, 'summary'),
                         contract.summarise(self.rows, self.fields, self.summary, 'summary'))

    def test_changed_strict_boundary(self):
        self.select.update(minFeatures=1,maxFeatures=1)
        self.select['predicates'][0]['comparison']='gt'
        self.assertEqual(contract.select(self.rows,self.fields,self.select,'test'), ['e'])

    def test_null_comparisons_and_conjunction(self):
        self.select.update(minFeatures=1,maxFeatures=9)
        for comparison, value, expected in [('isNull',None,['d']),('isNotNull',None,['a','b','c','e','f','g','h','i']),('ne',20,['a','e','f'])]:
            self.select['predicates']=[{'field':'score','type':'number','comparison':comparison}]
            if value is not None:self.select['predicates'][0]['value']=value
            self.assertEqual(contract.select(self.rows,self.fields,self.select,'test'),expected)
        self.select['predicates']=[{'field':'score','type':'number','comparison':'ge','value':20}, {'field':'region','type':'string','comparison':'eq','value':'north'}]
        self.assertEqual(contract.select(self.rows,self.fields,self.select,'test'),['b','g'])

    def test_semantic_and_native_field_failures(self):
        for mutate in [lambda o:o.update(minFeatures=7),lambda o:o['predicates'][0].update(value='20'),lambda o:o['predicates'][0].update(type='string')]:
            options=copy.deepcopy(self.select);mutate(options)
            with self.assertRaises(contract.ContractError):contract.validate_options('selectAttributes',options,'eligible.options')
        for change in ['missing','type','duplicate-id','null-id','bool-number']:
            rows=copy.deepcopy(self.rows);options=copy.deepcopy(self.select)
            if change=='missing':options['predicates'][0]['field']='absent'
            elif change=='type':rows[0]['score']='10'
            elif change=='duplicate-id':rows[1]['asset_id']='a'
            elif change=='null-id':rows[1]['asset_id']=None
            else:rows[0]['score']=True
            with self.assertRaises(contract.ContractError):contract.select(rows,self.fields,options,'eligible.options')
        options=copy.deepcopy(self.select);options['minFeatures']=7
        with self.assertRaises(contract.ContractError) as caught:contract.select(self.rows,self.fields,options,'eligible.options')
        self.assertEqual(caught.exception.code,'FEATURE_REQUIREMENT_FAILED')
        self.assertEqual(caught.exception.location,'eligible.options.minFeatures')

    def test_overflow_and_boolean_aggregate_rejection(self):
        rows=copy.deepcopy(self.rows)
        for row in rows:row['load_kw']=1e308
        with self.assertRaises(contract.ContractError):contract.summarise(rows,self.fields,self.summary,'summary')
        rows[0]['load_kw']=True
        with self.assertRaises(contract.ContractError):contract.summarise(rows,self.fields,self.summary,'summary')


class AttributePlanningTests(unittest.TestCase):
    def setUp(self):
        from schemaxis.adaptors.qgis import adaptor
        self.adaptor = adaptor
        self.document = json.loads((ROOT/'examples/schemaxis/qgis-attributes.json').read_text())

    def test_plan_defaults_immutable_and_closed(self):
        original=copy.deepcopy(self.document)
        self.adaptor.plan(self.document)
        self.assertEqual(self.document,original)
        del self.document['nodes'][1]['options']['minFeatures']
        del self.document['nodes'][1]['options']['maxFeatures']
        prepared=self.adaptor.plan(self.document)
        self.assertEqual(prepared['nodes'][1]['options']['minFeatures'],1)
        self.assertEqual(prepared['nodes'][1]['options']['maxFeatures'],10000)
        self.document['nodes'][1]['options']['expression']='score >=20'
        from schemaxis.core.faults import SchemaxisError
        with self.assertRaises(SchemaxisError) as caught:self.adaptor.plan(self.document)
        self.assertEqual(caught.exception.fault.code,'UNKNOWN_ARGUMENT')

    def test_schema_nested_types(self):
        import jsonschema
        validator=jsonschema.Draft202012Validator(self.adaptor.schema())
        self.assertTrue(validator.is_valid(self.document))
        self.document['nodes'][1]['options']['predicates'][0]['comparison']='eval'
        self.assertFalse(validator.is_valid(self.document))
        self.document['nodes'][1]['options']['predicates'][0]['comparison']='ge'
        self.document['nodes'][2]['options']['aggregates'][0]['surprise']='native'
        self.assertFalse(validator.is_valid(self.document))

    def test_aggregate_name_count_and_units_rejection(self):
        from schemaxis.core.faults import SchemaxisError
        for update in [{'name':'group'},{'name':'SELECT ALL'},{'field':'load_kw'},{'units':'kW'}]:
            document=copy.deepcopy(self.document);document['nodes'][2]['options']['aggregates'][0].update(update)
            with self.assertRaises(SchemaxisError):self.adaptor.plan(document)
        document=copy.deepcopy(self.document);document['nodes'][2]['options']['aggregates'][1]['name']='ASSETS'
        with self.assertRaises(SchemaxisError):self.adaptor.plan(document)

    def test_fingerprint_changed_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'assets.geojson';source.write_bytes(FIXTURE.read_bytes());self.document['nodes'][0]['options']['file']=str(source)
            before=self.adaptor.reusableInputs(self.document)
            source.write_text(source.read_text()+'\n')
            self.assertNotEqual(before,self.adaptor.reusableInputs(self.document))

    def test_source_preflight_rejects_nonregular_and_oversized(self):
        import os
        import tempfile
        from schemaxis.core.faults import SchemaxisError
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'assets.geojson';self.document['nodes'][0]['options']['file']=str(source)
            os.mkfifo(source)
            with self.assertRaises(SchemaxisError) as caught:self.adaptor.reusableInputs(self.document)
            self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE');source.unlink()
            with source.open('wb') as stream:stream.truncate(64*1024*1024+1)
            with self.assertRaises(SchemaxisError) as caught:self.adaptor.reusableInputs(self.document)
            self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')

    def test_authored_threshold_resolves_before_typed_validation(self):
        self.document['settings']={'threshold':20}
        self.document['nodes'][1]['options']['predicates'][0]['value']={'$document':'/settings/threshold'}
        before=copy.deepcopy(self.document)
        self.assertEqual(self.adaptor.plan(self.document)['nodes'][1]['options']['predicates'][0]['value'],20)
        self.assertEqual(self.document,before)

    def test_studio_starter_can_be_filled_and_planned(self):
        from schemaxis.studio_library import load_library, instantiate_item
        library=load_library('qgis');item=next(i for i in library['templates'] if i['id']=='attribute-summary')
        before=copy.deepcopy(item)
        document=instantiate_item(library,item,provider='qgis')
        prepared=self.adaptor.plan(document)
        self.assertEqual(prepared['output'],'regional_load')
        self.assertEqual(prepared['nodes'][1]['options']['predicates'][0]['value'],20)
        draft=instantiate_item(library,item,provider='qgis',filled=False)
        self.assertIsInstance(draft['nodes'][0]['options']['file'],dict)
        self.assertEqual(item,before)
