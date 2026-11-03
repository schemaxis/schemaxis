# Copyright (C) 2026 David L F Gaden
"""Exact relational semantics and hostile typed-table inputs."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.sqlite import adaptor as a
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


class SQLiteContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pending=ROOT/'src/schemaxis/adaptors/sqlite/adaptor.json.pending'
        cls.registration=patch.dict(registry.ADAPTORS,{'sqlite':json.loads(pending.read_text())}) if pending.exists() else patch.dict(registry.ADAPTORS,{})
        cls.registration.start()
    @classmethod
    def tearDownClass(cls):cls.registration.stop()
    def document(self,name='sales'):
        d=json.loads((ROOT/('examples/schemaxis/sqlite-'+name+'.json')).read_text())
        for t in d['tables']:t['source']=str(ROOT/'examples/schemaxis/fixtures/sqlite'/(t['name']+'.json'))
        return d
    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict());return caught.exception.fault
    def data(self,p):return {t['name']:a.rows(Path(t['source']).read_bytes(),t,'$.tables') for t in p['tables']}
    def test_immutable_defaults_and_declaration_schema_parity(self):
        d=self.document();original=copy.deepcopy(d);p=a.plan(d)
        self.assertEqual(d,original);self.assertEqual(a.plan(d),p)
        self.assertFalse(p['tables'][0]['columns'][0]['nullable']);self.assertEqual(p['tables'][0]['foreignKeys'],[])
        from schemaxis.core.declarations import validate_specification
        for key,spec in a.OPTIONS.items():validate_specification(spec,key)
        self.assertEqual(set(a.schema()['properties']),{'version','operation',*a.OPTIONS})
        self.assertIn('INNER JOIN "departments"',a.select(p));self.assertIn('STRICT;',a.ddl(p))
    def test_exact_null_join_filter_and_aggregate_oracle(self):
        expected={'sales':[[None,1,None],['',1,0],['North',3,300],['South',1,-30]],'sales-variant':[[None,1,None],['',1,0],['North',1,200],['South',1,-30]],'empty':[],'single-table':[[None,1,50],[1,3,300],[2,1,-30],[3,1,0],[4,1,None]]}
        for name,rows in expected.items():
            p=a.plan(self.document(name));self.assertEqual(a.oracle(p,self.data(p))['rows'],rows)
        p=a.plan(self.document());r=a.oracle(p,self.data(p));self.assertIn(b'\\N,1,\\N\n',a.csv_bytes(r));self.assertIn(b',1,0\n',a.csv_bytes(r))
    def test_nullable_numeric_group_keys_and_maximum_exact_integer_sum(self):
        d=self.document('single-table');d['groupBy']=['sales.amount'];p=a.plan(d)
        self.assertEqual(a.oracle(p,self.data(p))['rows'],[[None,2,None],[-30,1,-30],[0,1,0],[50,1,50],[100,1,100],[200,1,200]])
        d=self.document();p=a.plan(d);data=self.data(p)
        data['sales']=[{'id':i,'department':1,'amount':1000000000} for i in range(1,2049)]
        self.assertEqual(a.oracle(p,data)['rows'],[['North',2048,2048000000000]])

    def test_identifier_cross_field_and_native_escape_rejections(self):
        for name in ['SQL','sqlite_test','rowid','a; DROP TABLE x','x\n.load evil']:
            d=self.document();d['tables'][0]['name']=name;self.fault(lambda:a.plan(d),'INVALID_TABLE_IDENTIFIER')
        d=self.document('key-invalid');self.assertEqual(self.fault(lambda:a.plan(d),'INVALID_TABLE_QUERY').location,'$.join')
        d=self.document();d['tables'][1]['columns'][1]['type']='TEXT';self.fault(lambda:a.plan(d),'INVALID_TABLE_KEY')
        d=self.document();d['tables'][0]['columns'][0]['nullable']=True;self.fault(lambda:a.plan(d),'INVALID_TABLE_KEY')
        d=self.document();d['where']['column']='departments.region';self.fault(lambda:a.plan(d),'INVALID_TABLE_QUERY')
        d=self.document();d['sum']='unknown.amount';self.fault(lambda:a.plan(d),'INVALID_TABLE_QUERY')
        for key in ['sql','script','database','extension']:
            d=self.document();d[key]='.shell touch bad';self.fault(lambda:a.plan(d),'UNKNOWN_ARGUMENT')
        d=self.document();d['tables'][0]['source']='https://example.org/data.json';self.fault(lambda:a.plan(d),'INVALID_TABLE_SOURCE')
    def test_typed_rows_duplicate_json_keys_and_exact_primary_keys(self):
        t=a.plan(self.document())['tables'][1]
        for data in [b'[{"id":1,"id":2,"department":1,"amount":2}]',b'[{"id":true,"department":1,"amount":2}]',b'[{"id":1,"department":1,"amount":2.0}]',b'[{"id":1,"department":1,"amount":1000000001}]',b'[{"id":1,"department":1}]',b'[{"id":1,"department":1,"amount":NaN}]',b'[{"id":1,"department":1,"amount":2},{"id":1,"department":2,"amount":3}]']:
            self.fault(lambda:a.rows(data,t,'$.tables[1].source'),'INVALID_TABLE_DATA')
        t=a.plan(self.document())['tables'][0]
        for value in ['\\N','hello\nworld','café','x'*257]:
            self.fault(lambda:a.rows(json.dumps([{'id':1,'region':value}]).encode(),t,'$.source'),'INVALID_TABLE_DATA')
        value="x'); DROP TABLE departments;--"
        self.assertEqual(a.rows(json.dumps([{'id':1,'region':value}]).encode(),t,'$.source')[0]['region'],value)
        self.assertEqual(a.literal(value),"'x''); DROP TABLE departments;--'")
    def test_foreign_integrity_and_source_identity(self):
        d=self.document();p=a.plan(d)
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            for t in p['tables']:(directory/('table-'+t['name']+'.json')).write_bytes(Path(t['source']).read_bytes())
            a.captured(directory,p)
            path=directory/'table-sales.json';data=json.loads(path.read_text());data[0]['department']=99;path.write_text(json.dumps(data))
            self.fault(lambda:a.captured(directory,p),'INVALID_TABLE_DATA')
            source=directory/'sales.json';source.write_bytes(Path(d['tables'][1]['source']).read_bytes());d['tables'][1]['source']=str(source);old=a.reusableInputs(d)
            source.write_bytes(source.read_bytes()+b'\n');self.assertNotEqual(old,a.reusableInputs(d))
            link=directory/'link.json';link.symlink_to(source);self.fault(lambda:a.bounded(link,'INVALID_TABLE_SOURCE'),'INVALID_TABLE_SOURCE')
            if hasattr(os,'mkfifo'):
                fifo=directory/'fifo.json';os.mkfifo(fifo);self.fault(lambda:a.bounded(fifo,'INVALID_TABLE_SOURCE'),'INVALID_TABLE_SOURCE')
            source.write_bytes(b'0'*(1024*1024+1));self.fault(lambda:a.reusableInputs(d),'INVALID_TABLE_SOURCE')
    def test_studio_starters_plan_and_report_nested_placeholders(self):
        from schemaxis.studio_library import load_library, instantiate_item, plan_item
        from schemaxis.unfilled import find_unfilled
        library=load_library('sqlite')
        for item in library['templates']:
            plan_item(instantiate_item(library,item,provider='sqlite'))
            draft=instantiate_item(library,item,provider='sqlite',filled=False);expected=find_unfilled(draft)
            if expected:
                fault=self.fault(lambda:plan_item(draft),'UNFILLED_VALUES')
                self.assertEqual(fault.observed['pointers'],[v['pointer'] for v in expected])

    def test_guidance_and_actual_capability_matching(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['sqlite']),'sqlite')['complete'])
        self.assertTrue(audit('sqlite')['complete'])


if __name__=='__main__':unittest.main()
