"""Numerical contracts, analytic oracles, closed workbook grammar and native checks."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_DEFLATED
from schemaxis.core.faults import SchemaxisError
from schemaxis import tabular
from schemaxis.adaptors.octave import adaptor as octave
from schemaxis.adaptors.octave.reference import evaluate,fft
from schemaxis.adaptors.calc import adaptor as calc
from schemaxis.adaptors.calc import workbook

ROOT=Path(__file__).resolve().parents[2]


def sample(operation=None,options=None,x=None,y=None):
    nodes=[{'id':'data','filter':'samples','options':{'x':x if x is not None else [0,1,2,3,4],
                                                    'y':y if y is not None else [1,3,5,7,9]}}]
    if operation:nodes.append({'id':'out','filter':operation,'inputs':{'input':'data'},'options':options or {}})
    return {'version':'schemaxis.octave/1','nodes':nodes,'outputs':[nodes[-1]['id']]}


def table_document(columns=None,rows=None):
    return {'version':'schemaxis.calc/1','nodes':[{'id':'data','filter':'fromRows','options':{
        'columns':columns if columns is not None else ['x','y'], 'rows':rows if rows is not None else [[0,1],[1,3],[2,5]]}}]}


class NumericTables(unittest.TestCase):
    def test_roundtrip_numeric_csv_unicode_quoted_headers(self):
        table={'columns':['Time, seconds','Déplacement'],'rows':[[0,-1.25],[1,2e-20]]}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.csv';tabular.write_csv(path,table)
            self.assertEqual(tabular.read_csv(path),table)

    def test_malformed_and_nonfinite_tables(self):
        for columns,rows in [(['x','x'],[[1,2]]),([''],[[1]]),(['a\n'],[[1]]),(['x'],[]),
                             (['x'],[[True]]),(['x'],[[float('nan')]]),(['x'],[[float('inf')]]),
                             (['x'],[[1e101]]),(['x'],[[1,2]]),(['x'],[['2']]),(['x'],[[None]])]:
            with self.subTest(columns=columns,rows=rows),self.assertRaises(SchemaxisError):tabular.validate(columns,rows)

    def test_csv_errors_are_structured(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data.csv'
            for contents in (b'',b'x\nNaN\n',b'x,x\n1,2\n',b'x\n=SUM(A1)\n',b'x\n1,2\n',b'\xff',b'x\n"unterminated'):
                path.write_bytes(contents)
                with self.subTest(contents=contents),self.assertRaises(SchemaxisError):tabular.read_csv(path)
            path.write_bytes(b' '*(tabular.MAX_BYTES+1))
            with self.assertRaises(SchemaxisError) as caught:tabular.read_csv(path)
            self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')

    def test_csv_publication_limit_is_checked_before_native_work(self):
        with tempfile.TemporaryDirectory() as temp,patch('schemaxis.tabular.MAX_BYTES',10):
            with self.assertRaises(SchemaxisError) as caught:
                tabular.write_csv(Path(temp)/'out.csv',{'columns':['value'],'rows':[[12345],[67890]]})
            self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')

    def test_close_rejects_type_coercion_extra_keys_and_nonfinite(self):
        for actual,expected in [(True,1),('1',1),([1,2],[1]),({'x':1,'y':2},{'x':1}),(float('nan'),0),(float('inf'),0)]:
            self.assertFalse(tabular.close(actual,expected))
        self.assertTrue(tabular.close([1+1e-10],[1]))


class OctaveContracts(unittest.TestCase):
    def test_planning_is_pure_and_deterministic(self):
        document=sample('linearFit');original=copy.deepcopy(document)
        self.assertEqual(octave.plan(document),octave.plan(original));self.assertEqual(document,original)
        self.assertEqual(len(octave.schema()['properties']['nodes']['items']['oneOf']),11)
        source={'version':'schemaxis.octave/1','nodes':[{'id':'data','filter':'readCSV','options':{'file':'/absent.csv'}}],'outputs':['data']}
        with patch('pathlib.Path.open',side_effect=AssertionError('planning reads files')):octave.plan(source)

    def test_input_grammar_rejects_unknown_code_and_bad_dependencies(self):
        mutations=[lambda d:d.update(script='system("bad")'),lambda d:d['nodes'][0].update(filter='eval'),
                   lambda d:d['nodes'][0].update(id='../bad'),lambda d:d.update(outputs=['missing']),
                   lambda d:d.update(outputs=['data','data']),lambda d:d['nodes'][0]['options'].update(x=[1,2]),
                   lambda d:d['nodes'][0]['options'].update(y=[True,2,3,4,5]),lambda d:d['nodes'].append(d['nodes'][0])]
        for mutate in mutations:
            d=sample();mutate(d)
            with self.assertRaises(SchemaxisError):octave.plan(d)
        for value in ('later',[],None,True):
            d=sample('derivative');d['nodes'][1]['inputs']['input']=value
            with self.assertRaises(SchemaxisError):octave.plan(d)

    def test_derivative_integral_and_fit_have_independent_known_answers(self):
        for op,expected in [('derivative',[2]*5),('integral',[0,2,6,12,20]),('linearFit',[1,3,5,7,9])]:
            result=evaluate(octave.plan(sample(op)),{})['out']
            self.assertTrue(tabular.close(result['y'],expected))
        self.assertEqual(evaluate(octave.plan(sample('linearFit')),{})['out']['metadata'],{'slope':2,'intercept':1,'residualSumSquares':0})
        self.assertEqual(evaluate(octave.plan(sample('integral',{'initial':3})),{})['out']['y'],[3,5,9,15,23])

    def test_resample_preserves_a_line_on_an_irregular_grid(self):
        result=evaluate(octave.plan(sample('resample',{'count':6},x=[0,1,3,5],y=[1,3,7,11])),{})['out']
        self.assertEqual(result['x'],[0,1,2,3,4,5]);self.assertEqual(result['y'],[1,3,5,7,9,11])

    def test_nonuniform_derivative_and_moving_mean_edges(self):
        result=evaluate(octave.plan(sample('derivative',x=[0,1,3],y=[0,1,9])),{})['out']
        self.assertEqual(result['y'],[1,3,4])
        result=evaluate(octave.plan(sample('movingMean',{'window':3})),{})['out']
        self.assertEqual(result['y'],[2,3,5,7,8])

    def test_fft_amplitude_frequency_and_dc(self):
        doc={'version':'schemaxis.octave/1','nodes':[{'id':'data','filter':'wave','options':{'count':128,'step':1/128,'frequency':8,'amplitude':2,'offset':3}},
             {'id':'out','filter':'fft','inputs':{'input':'data'}}],'outputs':['out']}
        result=evaluate(octave.plan(doc),{})['out'];self.assertEqual(result['x'][8],8)
        self.assertAlmostEqual(result['y'][8],2);self.assertAlmostEqual(result['y'][0],3)
        self.assertLess(max(v for i,v in enumerate(result['y']) if i not in (0,8)),1e-13)
        self.assertTrue(all(abs(a-b)<1e-12 for a,b in zip(fft([1,0,0,0]),[1,1,1,1])))

    def test_degenerate_and_nonuniform_sampling_rejected_before_native(self):
        cases=[sample('resample',x=[1,0],y=[1,2]),sample('derivative',x=[0,0,1],y=[1,2,3]),sample('integral',x=[1,0],y=[1,2]),
               sample('linearFit',x=[1,1],y=[1,2]),sample('fft'),sample('fft',x=[0,1,2,4],y=[1,2,3,4]),
               sample('movingMean',{'window':7})]
        for doc in cases:
            with self.subTest(doc=doc),self.assertRaises(SchemaxisError):evaluate(octave.plan(doc),{})
        with self.assertRaises(SchemaxisError):octave.plan(sample('movingMean',{'window':2}))

    def test_intermediate_budget(self):
        nodes=[{'id':'n'+str(i),'filter':'sequence','options':{'count':10000}} for i in range(11)]
        with self.assertRaises(SchemaxisError) as caught:evaluate(octave.plan({'version':'schemaxis.octave/1','nodes':nodes,'outputs':['n10']}),{})
        self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')

    def test_timeout_and_missing_runtime_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            for timeout in (0,-1,True,float('nan'),3601):
                with self.assertRaises(SchemaxisError):octave.run(sample(),Path(temp)/'out',timeout=timeout)
            with self.assertRaises(SchemaxisError) as caught:octave.run(sample(),Path(temp)/'out',executable='/no/octave')
            self.assertEqual(caught.exception.fault.code,'INTERPRETER_NOT_FOUND')
            with self.assertRaises(SchemaxisError):octave.verify(temp)


class CalcContracts(unittest.TestCase):
    def test_plan_and_schema(self):
        doc=table_document();original=copy.deepcopy(doc)
        self.assertEqual(calc.plan(doc)['expectedPublications'],3);self.assertEqual(doc,original)
        self.assertEqual(calc.schema()['properties']['nodes']['maxItems'],1)
        self.assertEqual(workbook.column(0),'A');self.assertEqual(workbook.column(26),'AA');self.assertEqual(workbook.column(63),'BL')

    def test_no_arbitrary_formulas_macros_or_native_documents(self):
        for columns,rows in [(['x'],[['=1+1'],[2]]),(['x'],[[1]]),(['x','x'],[[1,2],[3,4]])]:
            with self.assertRaises(SchemaxisError):calc.plan(table_document(columns,rows))
        for extra in ({'macro':'bad'},{'script':'bad'},{'file':'input.xlsx'}):
            with self.assertRaises(SchemaxisError):calc.plan({**table_document(),**extra})
        doc=table_document();doc['nodes'][0]={'id':'data','filter':'readCSV','options':{'file':'relative.csv'}}
        with self.assertRaises(SchemaxisError):calc.plan(doc)

    def test_authored_headers_are_literal_and_formulas_have_no_cached_answers(self):
        table={'columns':['=1+1','Déplacement & x'],'rows':[[0,1],[2,3]]}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'input.ods';workbook.write_ods(path,table)
            values,formulas=workbook.read_ods(path)
            self.assertEqual(values['Data'][0],table['columns'])
            self.assertTrue(all(value is None for value in values['Summary'][1][1:]))
            self.assertTrue(all(value is None for value in formulas['Data'][0]))
            with self.assertRaises(SchemaxisError):workbook.verify_workbook(path,table)

    def test_ods_reader_preserves_interior_empty_cell_and_row_positions(self):
        from xml.etree import ElementTree as ET
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'input.ods';workbook.write_ods(path,{'columns':['x'],'rows':[[1],[2]]})
            with ZipFile(path) as z:members={n:z.read(n) for n in z.namelist()}
            root=ET.fromstring(members['content.xml']);sheet=root.find('.//table:table',workbook.NS)
            row=sheet.find('table:table-row',workbook.NS)
            row.insert(0,ET.Element(workbook.tag('table','table-cell')))
            sheet.insert(1,ET.Element(workbook.tag('table','table-row')))
            members['content.xml']=ET.tostring(root)
            with ZipFile(path,'w',ZIP_DEFLATED) as z:
                for n,data in members.items():z.writestr(n,data)
            values,_=workbook.read_ods(path)
            self.assertEqual(values['Data'],[[None,'x'],[],[1],[2]])

    def test_independent_summary(self):
        summary=workbook.expected({'columns':['x'],'rows':[[1],[2],[3]]})['Summary'][1]
        self.assertEqual(summary,['x',3,6,2,1,3,1])

    def test_xml_expansion_limit_precedes_decompression(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        archive=Mock();archive.getinfo.return_value=SimpleNamespace(file_size=128*1024*1024+1)
        with self.assertRaises(SchemaxisError):workbook.xml(archive,'content.xml')
        archive.read.assert_not_called()

    def test_missing_receipts_and_malformed_workbooks(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SchemaxisError):calc.verify(temp)
            for timeout in (0,True,float('nan'),3601):
                with self.assertRaises(SchemaxisError):calc.run(table_document(),Path(temp)/'out',timeout=timeout)
            with self.assertRaises(SchemaxisError):calc.run(table_document(),Path(temp)/'out',executable='/no/calc')


class NativeAnalysis(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_OCTAVE'),'set SCHEMAXIS_TEST_OCTAVE for native numerical tests')
    def test_octave_results_and_tampered_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);runtime=os.environ['SCHEMAXIS_TEST_OCTAVE']
            for name in ('octave-signal','octave-regression','octave-calibration'):
                doc=json.loads((ROOT/'examples/schemaxis/analysis'/(name+'.json')).read_text())
                target=root/name;self.assertTrue(octave.run(doc,target,executable=runtime)['verified'])
                self.assertTrue(octave.verify(target)['verified'])
            target=root/'octave-regression'
            for name,mutate in [('native.json',lambda d:d['nodes']['fit']['metadata'].update(slope=900)),
                                ('request.json',lambda d:d['plan']['outputs'].append('forged')),
                                ('statistics.json',lambda d:d['fit'].update(mean=12345))]:
                path=target/name;old=path.read_bytes();record=json.loads(old);mutate(record);path.write_text(json.dumps(record))
                with self.assertRaises(SchemaxisError):octave.verify(target)
                path.write_bytes(old)
            csv=target/'fit.csv';old=csv.read_bytes();csv.write_text('x,y\n0,999\n1,888\n')
            with self.assertRaises(SchemaxisError):octave.verify(target)
            csv.write_bytes(old);self.assertTrue(octave.verify(target)['verified'])
            worker=target/'worker.m';old=worker.read_bytes();worker.write_text('disp(1);')
            with self.assertRaises(SchemaxisError):octave.verify(target)
            worker.write_bytes(old);self.assertTrue(octave.verify(target)['verified'])

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_CALC'),'set SCHEMAXIS_TEST_CALC for native spreadsheet tests')
    def test_calc_recalculation_roundtrip_and_tampering(self):
        doc=table_document(['=1+1','Déplacement & x'],[[0,1],[1,3],[2,5]])
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'workbook'
            self.assertTrue(calc.run(doc,target,executable=os.environ['SCHEMAXIS_TEST_CALC'])['verified'])
            self.assertTrue(calc.verify(target)['verified'])
            path=target/'analysis.xlsx';old=path.read_bytes()
            with ZipFile(path) as z:members={n:z.read(n) for n in z.namelist()}
            name='xl/worksheets/sheet2.xml';self.assertIn(b'SUM(',members[name])
            members[name]=members[name].replace(b'SUM(',b'MAX(',1)
            with ZipFile(path,'w',ZIP_DEFLATED) as z:
                for n,data in members.items():z.writestr(n,data)
            # Formula verification must fail even when cached values still agree.
            with self.assertRaises(SchemaxisError):workbook.verify_workbook(path,doc['nodes'][0]['options'])
            with self.assertRaises(SchemaxisError):calc.verify(target)
            path.write_bytes(old);self.assertTrue(calc.verify(target)['verified'])

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_TEST_OCTAVE') and os.environ.get('SCHEMAXIS_TEST_CALC'),'set both native analysis executables for CSV handoff tests')
    def test_roundtrip_workflow_and_source_hashes(self):
        from schemaxis.workflow import execute,verify
        doc=json.loads((ROOT/'examples/schemaxis/analysis/octave-to-calc.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'workflow'
            execute(doc,target,locations={'octave':os.environ['SCHEMAXIS_TEST_OCTAVE'],'calc':os.environ['SCHEMAXIS_TEST_CALC']})
            self.assertTrue(verify(target)['verified'])
            source=Path(temp)/'source.csv';source.write_text('x,y\n0,1\n1,2\n')
            authored={'version':'schemaxis.octave/1','nodes':[{'id':'data','filter':'readCSV','options':{'file':str(source)}}],'outputs':['data']}
            before=octave.reusableInputs(authored);source.write_text('x,y\n0,9\n1,8\n')
            self.assertNotEqual(before,octave.reusableInputs(authored))


if __name__=='__main__':unittest.main()
