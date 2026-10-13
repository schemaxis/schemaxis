"""Bounded Calc policy, numeric selector distinctions and resource admission."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptors.calc import adaptor, requirements, workbook
from schemaxis.core.faults import SchemaxisError


def document():
    return {'version':'schemaxis.calc/1','nodes':[{'id':'accounts','filter':'fromRows','options':{
        'columns':['income','expense'],'rows':[[100,70],[50,80]]}}],
        'requirements':[{'name':'income-cap','type':'cellBounds','cell':{'sheet':'Summary','cell':'C2'},'maximum':160},
                        {'name':'balance','type':'reconcile','terms':[{'sheet':'Summary','cell':'C2','coefficient':1},
                            {'sheet':'Summary','cell':'C3','coefficient':-1}],'target':0,'absoluteTolerance':1e-9}]}


class CalcRequirementTests(unittest.TestCase):
    def test_named_native_cells_bounds_and_reconciliation_are_pure(self):
        authored=document();before=copy.deepcopy(authored);prepared=adaptor.plan(authored)
        self.assertEqual(authored,before)
        observed=workbook.expected(authored['nodes'][0]['options'])
        report=requirements.report(prepared['requirements'],{'xlsx':observed,'ods':observed})
        self.assertTrue(report['passed']);self.assertEqual(report['formats']['xlsx']['checks'][0]['margin'],10)
        self.assertEqual(report['formats']['ods']['checks'][1]['value'],0)
        self.assertEqual(report['worstFormats'][1]['name'],'balance')
        requirements.enforce(report)

    def test_unmet_has_signed_margin_and_differs_from_invalid_selector(self):
        authored=document();authored['nodes'][0]['options']['rows'][1][1]=85
        prepared=adaptor.plan(authored);observed=workbook.expected(authored['nodes'][0]['options'])
        report=requirements.report(prepared['requirements'],{'xlsx':observed,'ods':observed})
        self.assertFalse(report['passed']);self.assertEqual(report['formats']['xlsx']['checks'][1]['value'],-5)
        self.assertLess(report['formats']['xlsx']['checks'][1]['margin'],0)
        with self.assertRaises(SchemaxisError) as caught:requirements.enforce(report)
        self.assertEqual(caught.exception.fault.code,'REQUIREMENTS_UNMET')
        self.assertEqual(caught.exception.fault.observed['assessment'][0]['value'],-5)
        self.assertIn('recovery',caught.exception.fault.observed)
        for cell,status in [('C65','missing'),('A1','non-numeric')]:
            report=requirements.report(requirements.prepare([{'name':'invalid','type':'cellBounds','cell':{'sheet':'Summary','cell':cell},'minimum':0}]),{'xlsx':observed,'ods':observed})
            self.assertEqual(report['formats']['xlsx']['checks'][0]['conditions'][0]['condition'],status)
            with self.assertRaises(SchemaxisError) as caught:requirements.enforce(report)
            self.assertEqual(caught.exception.fault.code,'REQUIREMENT_SELECTION_FAILED')

    def test_both_recomputed_native_formats_must_meet_boundary(self):
        authored=document();prepared=adaptor.plan(authored)
        expected=workbook.expected(authored['nodes'][0]['options']);ods=copy.deepcopy(expected)
        ods['Summary'][1][2]=150+2e-9
        report=requirements.report(prepared['requirements'],{'xlsx':expected,'ods':ods})
        self.assertTrue(report['formats']['xlsx']['passed']);self.assertFalse(report['formats']['ods']['passed'])
        with self.assertRaises(SchemaxisError):requirements.enforce(report)

    def test_closed_requirement_grammar_and_bounded_a1_addresses(self):
        for mutate in (lambda r:r[0].update(name='balance'),lambda r:r[0].pop('maximum'),
                       lambda r:r[0].update(minimum=200),lambda r:r[0]['cell'].update(cell='$C$2'),
                       lambda r:r[0]['cell'].update(cell='H2'),lambda r:r[1]['terms'][0].update(coefficient=0),
                       lambda r:r[1]['terms'][0].update(coefficient=True),lambda r:r[1]['terms'][1].update(cell='C2'),
                       lambda r:r[1].update(absoluteTolerance=-1),lambda r:r[1].update(formula='SUM(A1)')):
            authored=document();mutate(authored['requirements'])
            with self.assertRaises(SchemaxisError):adaptor.plan(authored)
        self.assertEqual(requirements.address({'sheet':'Data','cell':'BL10001'}),(10000,63))

    def test_header_text_is_not_coerced_and_coefficients_are_explicit(self):
        values={'Data':[['123','expense'],[100,70],[50,80]],'Summary':[]}
        checked=requirements.evaluate(requirements.prepare([{'name':'header','type':'cellBounds','cell':{'sheet':'Data','cell':'A1'},'minimum':100}]),values)
        self.assertEqual(checked['checks'][0]['status'],'invalid-selection')
        constraint=requirements.prepare([{'name':'difference','type':'reconcile','terms':[{'sheet':'Data','cell':'A2','coefficient':2},{'sheet':'Data','cell':'B2','coefficient':-1}], 'target':130,'absoluteTolerance':0}])
        self.assertTrue(requirements.evaluate(constraint,values)['passed'])

    def test_fingerprint_and_capture_reject_nonregular_oversized_and_nul(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.csv';source.write_text('x\n1\n2\n')
            authored={'version':'schemaxis.calc/1','nodes':[{'id':'table','filter':'readCSV','options':{'file':str(source)}}]}
            self.assertTrue(adaptor.reusableInputs(authored))
            with patch.object(adaptor,'MAX_BYTES',3):
                with self.assertRaises(SchemaxisError) as caught:adaptor.reusableInputs(authored)
                self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')
            if hasattr(os,'mkfifo'):
                fifo=root/'fifo';os.mkfifo(fifo);authored['nodes'][0]['options']['file']=str(fifo)
                with self.assertRaises(SchemaxisError) as caught:adaptor.reusableInputs(authored)
                self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE')
                with patch.object(adaptor,'execute',side_effect=AssertionError('must not launch native')):
                    with self.assertRaises(SchemaxisError) as caught:adaptor.run(authored,root/'attempt',executable=__import__('sys').executable)
                    self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE')
            authored['nodes'][0]['options']['file']='/tmp/input\x00.csv'
            with self.assertRaises(SchemaxisError) as caught:adaptor.reusableInputs(authored)
            self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE')

    def test_retained_requirement_evidence_is_bounded_regular_and_recomputed(self):
        from schemaxis.artifacts import atomic_json
        from schemaxis.tabular import write_csv
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);authored=document();prepared=adaptor.plan(authored)
            for name,value in [('authored.json',authored),('plan.json',prepared),('result.json',{'verified':True}),
                               ('source.json',{}),('runtime.json',{'runtime':'LibreOffice 26.8.1.1'})]:atomic_json(root/name,value)
            write_csv(root/'data.csv',authored['nodes'][0]['options'])
            for name in ('analysis.xlsx','analysis.ods'):(root/name).write_bytes(b'host-only placeholder')
            observations=workbook.expected(authored['nodes'][0]['options'])
            with patch.object(adaptor,'verify_workbook',return_value=observations):
                adaptor._native_verify(root,require_result=False)
                path=root/'requirements.json';original=path.read_bytes()
                for payload in (b'null',b'{',b' '* (1024*1024+1)):
                    path.write_bytes(payload)
                    with self.assertRaises(SchemaxisError):adaptor._native_verify(root)
                path.write_bytes(original)
                other=root/'other.json';other.write_bytes(original);path.unlink()
                try:path.symlink_to(other)
                except (OSError,NotImplementedError):path.write_bytes(original)
                else:
                    with self.assertRaises(SchemaxisError) as caught:adaptor._native_verify(root)
                    self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
                    path.unlink();path.write_bytes(original)
                if hasattr(os,'mkfifo'):
                    path.unlink();os.mkfifo(path)
                    with self.assertRaises(SchemaxisError) as caught:adaptor._native_verify(root)
                    self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE')
                    path.unlink();path.write_bytes(original)
                    publication=root/'analysis.xlsx';published=publication.read_bytes();publication.unlink();os.mkfifo(publication)
                    with self.assertRaises(SchemaxisError) as caught:adaptor._native_verify(root)
                    self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
                    publication.unlink();publication.write_bytes(published)
                # Manifest refresh cannot substitute an invented assessment:
                record=json.loads(original);record['formats']['xlsx']['checks'][1]['value']=123
                path.write_text(json.dumps(record))
                with self.assertRaises(SchemaxisError):adaptor._native_verify(root)

    def test_final_cpu_deadline_and_cancellation_block_success(self):
        import sys
        for cancelled in (False,True):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'attempt';clock=[0]
                def native(command,directory,name,*args,**kwargs):
                    if name=='version':(directory/'version.stdout').write_text('LibreOffice 26.8.1.1')
                    else:(directory/name/('analysis.'+name)).write_bytes(b'host-only placeholder')
                def verified(*args,**kwargs):
                    clock[0]=0 if cancelled else 2
                    return {'verified':True}
                with patch.object(adaptor,'execute',side_effect=native),patch.object(adaptor,'verify_workbook'), \
                     patch.object(adaptor,'verify',side_effect=verified),patch.object(adaptor.time,'monotonic',side_effect=lambda:clock[0]), \
                     patch.object(adaptor,'cancellation_requested',return_value=cancelled):
                    with self.assertRaises(SchemaxisError) as caught:adaptor._native_run(document(),root,executable=sys.executable,timeout=1)
                self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED' if cancelled else 'RUNNER_TIMED_OUT')
                self.assertEqual(json.loads((root/'result.json').read_text())['status'],'failed')


if __name__=='__main__':unittest.main()
