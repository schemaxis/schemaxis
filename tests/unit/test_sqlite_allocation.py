"""Locatable source/data faults and honest retained-run states for SQLite summaries."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from schemaxis.adaptors.sqlite import adaptor as a
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]
FIXTURES=ROOT/'examples/schemaxis/fixtures/sqlite'


class SQLiteBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.dir=Path(self.temp.name)
    def document(self,name='sales'):
        d=json.loads((ROOT/('examples/schemaxis/sqlite-'+name+'.json')).read_text())
        for t in d['tables']:t['source']=str(FIXTURES/(t['name']+'.json'))
        return d
    def with_sales(self,content):
        path=self.dir/'sales.json'
        if isinstance(content,str):content=content.encode()
        path.write_bytes(content);d=self.document();d['tables'][1]['source']=str(path);return d
    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict());return caught.exception.fault
    def stub(self,body):
        path=self.dir/'sqlite3';path.write_text('#!/bin/sh\n'+body);path.chmod(path.stat().st_mode|stat.S_IXUSR);return str(path)

    def test_run_time_data_faults_locate_the_declared_table_and_reason(self):
        cases=[('[{"id":1,"department":1,"amount":2.5}]','invalid-cell',{'row':0,'column':'amount'}),
            ('not json','malformed-json',{}),
            ('{"id":1}','invalid-shape',{}),
            ('[{"id":1,"department":1}]','invalid-shape',{'row':0}),
            ('[{"id":1,"id":2,"department":1,"amount":2}]','malformed-json',{}),
            ('[{"id":1,"department":1,"amount":2},{"id":1,"department":1,"amount":3}]','duplicate-key',{'row':1,'column':'id'})]
        for n,(content,reason,extra) in enumerate(cases):
            fault=self.fault(lambda:a.run(self.with_sales(content),self.dir/f'run{n}',executable='/bin/true'),'INVALID_TABLE_DATA')
            self.assertEqual(fault.location,'$.tables[1].source',(content,fault.to_dict()))
            self.assertEqual(fault.observed.get('table'),'sales');self.assertEqual(fault.observed.get('reason'),reason,(content,fault.to_dict()))
            for k,v in extra.items():self.assertEqual(fault.observed.get(k),v,(content,fault.to_dict()))
            self.assertNotIn(str(self.dir),json.dumps(fault.to_dict()['location']))
    def test_source_file_faults_are_structurally_distinct_and_not_path_located(self):
        d=self.with_sales('[]');path=Path(d['tables'][1]['source'])
        expected={}
        path.write_bytes(b'0'*(1024*1024+1));expected['too-large']=d
        missing=self.document();missing['tables'][1]['source']=str(self.dir/'absent.json');expected['missing']=missing
        link=self.dir/'link.json';link.symlink_to(FIXTURES/'sales.json');linked=self.document();linked['tables'][1]['source']=str(link);expected['symlink']=linked
        folder=self.dir/'folder.json';folder.mkdir();directory=self.document();directory['tables'][1]['source']=str(folder);expected['not-regular']=directory
        for n,(reason,document) in enumerate(expected.items()):
            fault=self.fault(lambda:a.run(document,self.dir/f'run{n}',executable='/bin/true'),'INVALID_TABLE_SOURCE')
            self.assertEqual(fault.location,'$.tables[1].source',fault.to_dict());self.assertEqual(fault.observed['reason'],reason,fault.to_dict())
            self.assertEqual(fault.observed['table'],'sales')
            self.assertNotIn(str(self.dir),fault.location)
            reuse=self.fault(lambda:a.reusableInputs(document),'INVALID_TABLE_SOURCE')
            self.assertEqual((reuse.location,reuse.observed['reason']),('$.tables[1].source',reason))
    def test_orphan_foreign_key_names_the_offending_row(self):
        d=self.with_sales('[{"id":1,"department":1,"amount":2},{"id":2,"department":99,"amount":3}]')
        fault=self.fault(lambda:a.run(d,self.dir/'run',executable='/bin/true'),'INVALID_TABLE_DATA')
        self.assertEqual(fault.location,'$.tables[1].foreignKeys[0]')
        self.assertEqual({k:fault.observed.get(k) for k in ('table','column','row','value','reason')},{'table':'sales','column':'department','row':1,'value':99,'reason':'orphan-foreign-key'})
    def test_failed_and_incomplete_runs_verify_as_incomplete_not_tampered(self):
        d=self.with_sales('[{"id":1,"department":1,"amount":"x"}]')
        self.fault(lambda:a.run(d,self.dir/'early',executable='/bin/true'),'INVALID_TABLE_DATA')
        fault=self.fault(lambda:a.verify(self.dir/'early'),'INCOMPLETE_EXECUTION')
        self.assertEqual((fault.observed['status'],fault.observed['faultCode']),('failed','INVALID_TABLE_DATA'))
        # A native stage that fails after capture keeps its recorded fault code.
        good=self.document()
        self.fault(lambda:a.run(good,self.dir/'native',executable=self.stub('exit 3\n')),'RUNNER_FAILED')
        fault=self.fault(lambda:a.verify(self.dir/'native'),'INCOMPLETE_EXECUTION')
        self.assertEqual(fault.observed['faultCode'],'RUNNER_FAILED')
        # A different native release is unsupported, retained and not verifiable.
        self.fault(lambda:a.run(good,self.dir/'other',executable=self.stub('echo "3.1.0 2020-01-01 00:00:00 '+'0'*64+' (64-bit)"\n')),'UNSUPPORTED_NATIVE_VERSION')
        fault=self.fault(lambda:a.verify(self.dir/'other'),'INCOMPLETE_EXECUTION')
        self.assertEqual(fault.observed['faultCode'],'UNSUPPORTED_NATIVE_VERSION')
        self.assertFalse(json.loads((self.dir/'other/result.json').read_text())['verified'])
    def test_claimed_success_without_receipt_remains_a_verification_failure(self):
        d=self.with_sales('[{"id":1,"department":1,"amount":"x"}]')
        self.fault(lambda:a.run(d,self.dir/'run',executable='/bin/true'),'INVALID_TABLE_DATA')
        (self.dir/'run/result.json').write_text(json.dumps({'status':'succeeded','verified':True}))
        self.fault(lambda:a.verify(self.dir/'run'),'VERIFICATION_FAILED')
        (self.dir/'run/result.json').unlink()
        self.fault(lambda:a.verify(self.dir/'run'),'VERIFICATION_FAILED')


if __name__=='__main__':unittest.main()
