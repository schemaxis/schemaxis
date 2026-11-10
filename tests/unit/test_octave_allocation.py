"""Planning-time enforcement of data-dependent numerical constraints for Octave."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.octave import adaptor as octave

ROOT=Path(__file__).resolve().parents[2]


def chain(operation,options=None,x=None,y=None):
    return {'version':'schemaxis.octave/1','nodes':[
        {'id':'data','filter':'samples','options':{'x':x if x is not None else [0,1,2,3,4],'y':y if y is not None else [1,3,5,7,9]}},
        {'id':'out','filter':operation,'inputs':{'input':'data'},'options':options or {}}],'outputs':['out']}


def fault(callable_,*args,**kwargs):
    with unittest.TestCase().assertRaises(SchemaxisError) as caught:callable_(*args,**kwargs)
    return caught.exception.fault


class LiteralArraysArePlannedAgainstTheNumericalContract(unittest.TestCase):
    CASES=[('fft',{},[0,1,2,4],[1,2,3,4],'INVALID_SAMPLING'),
           ('fft',{},[0,1,2],[1,2,3],'INVALID_SAMPLING'),
           ('derivative',{},[0,0,1],[1,2,3],'INVALID_SAMPLING'),
           ('integral',{},[1,0],[1,2],'INVALID_SAMPLING'),
           ('resample',{'count':5},[2,1,0],[1,2,3],'INVALID_SAMPLING'),
           ('movingMean',{'window':7},None,None,'INVALID_SAMPLING'),
           ('linearFit',{},[1,1],[1,2],'SINGULAR_FIT')]

    def test_planning_rejects_each_violation_with_node_location_and_recovery(self):
        for operation,options,x,y,code in self.CASES:
            with self.subTest(operation=operation,x=x):
                found=fault(octave.plan,chain(operation,options,x,y))
                self.assertEqual(found.code,code);self.assertEqual(found.location,'out')
                self.assertTrue(found.recovery)

    def test_budget_is_enforced_at_planning_for_literal_chains(self):
        nodes=[{'id':'n'+str(i),'filter':'sequence','options':{'count':10000}} for i in range(11)]
        found=fault(octave.plan,{'version':'schemaxis.octave/1','nodes':nodes,'outputs':['n10']})
        self.assertEqual(found.code,'RESOURCE_LIMIT');self.assertTrue(found.recovery)

    def test_run_refuses_before_creating_an_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            fake=Path(temp)/'octave';fake.write_text('#!/bin/sh\nexit 99\n');fake.chmod(0o755)
            target=Path(temp)/'out'
            found=fault(octave.run,chain('fft',{},[0,1,2,4],[1,2,3,4]),target,executable=str(fake))
            self.assertEqual(found.code,'INVALID_SAMPLING');self.assertFalse(target.exists())

    def test_valid_documents_and_published_examples_still_plan(self):
        self.assertEqual(octave.plan(chain('derivative'))['expectedPublications'],2)
        for name in ('octave-signal','octave-regression','octave-calibration'):
            document=json.loads((ROOT/'examples/schemaxis/analysis'/(name+'.json')).read_text())
            self.assertEqual(octave.plan(document)['outputs'],document['outputs'])


class CSVDependentNodesStayRuntimeChecked(unittest.TestCase):
    def document(self,literal_operation='derivative',literal_x=None):
        return {'version':'schemaxis.octave/1','nodes':[
            {'id':'file','filter':'readCSV','options':{'file':'/absent/never-read.csv'}},
            {'id':'fromFile','filter':'fft','inputs':{'input':'file'}},
            {'id':'data','filter':'samples','options':{'x':literal_x or [0,1,2],'y':[1,2,3]}},
            {'id':'literal','filter':literal_operation,'inputs':{'input':'data'}}],'outputs':['fromFile','literal']}

    def test_planning_never_reads_a_csv_and_defers_file_dependent_checks(self):
        with patch('pathlib.Path.open',side_effect=AssertionError('planning reads files')),\
                patch('builtins.open',side_effect=AssertionError('planning reads files')):
            self.assertEqual(octave.plan(self.document())['expectedPublications'],3)

    def test_literal_branch_is_still_checked_beside_a_csv_branch(self):
        found=fault(octave.plan,self.document(literal_x=[0,0,1]))
        self.assertEqual((found.code,found.location),('INVALID_SAMPLING','literal'))

    def test_csv_dependent_violation_keeps_a_structured_runtime_fault(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'in.csv';source.write_text('x,y\n0,1\n1,2\n2,3\n4,5\n')
            document=self.document();document['nodes'][0]['options']['file']=str(source)
            fake=Path(temp)/'octave';fake.write_text('#!/bin/sh\nexit 99\n');fake.chmod(0o755)
            found=fault(octave.run,document,Path(temp)/'out',executable=str(fake))
            self.assertEqual((found.code,found.location),('INVALID_SAMPLING','fromFile'))
            self.assertTrue(found.recovery)


if __name__=='__main__':unittest.main()
