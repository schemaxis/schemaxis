# Copyright (C) 2026 David L F Gaden
"""Independent regression identities, finite intent gates and native-evidence attacks."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.r import adaptor,reference
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise
from schemaxis.tabular import write_csv

ROOT=Path(__file__).resolve().parents[2]


def document(name='regression'):
    return json.loads((ROOT/f'examples/schemaxis/r-{name}.json').read_text())


class RAdmissionTests(unittest.TestCase):
    def test_host_safe_deterministic_immutable_planning_and_schema(self):
        import jsonschema
        doc=document();saved=copy.deepcopy(doc)
        with patch.object(adaptor,'execute') as execute:
            prepared=adaptor.plan(doc);self.assertEqual(prepared,adaptor.plan(doc))
        execute.assert_not_called();self.assertEqual(doc,saved)
        jsonschema.Draft202012Validator(adaptor.schema()).validate(doc)
        self.assertEqual(prepared['rank'],2);self.assertEqual(prepared['residualDF'],2)
        self.assertLess(prepared['scaledInfinityCondition'],3)
        from schemaxis.adaptor_conformance import host
        self.assertTrue(host(adaptor.VERSION)['verified'])

    def test_independent_known_slope_orthogonal_residuals_and_no_intercept(self):
        for variant,slope in [('regression',2),('regression-variant',3)]:
            prepared=adaptor.plan(document(variant));fit=reference.decompose(prepared['training'],True)
            self.assertAlmostEqual(fit['coefficients'][0],10);self.assertAlmostEqual(fit['coefficients'][1],slope)
            predictions=[reference.predicted(prepared,row,fit['coefficients']) for row in prepared['training']]
            residuals=[row[-1]-value for row,value in zip(prepared['training'],predictions)]
            self.assertAlmostEqual(math.fsum(residuals),0)
            self.assertAlmostEqual(math.fsum(row[0]*r for row,r in zip(prepared['training'],residuals)),0)
        doc=document();doc['intercept']=False;doc['training']=[[-2,-4],[-1,-2],[1,2],[2,4]]
        fit=reference.decompose(adaptor.plan(doc)['training'],False);self.assertAlmostEqual(fit['coefficients'][0],2)

    def test_multiple_predictors_known_plane_and_scaled_condition(self):
        # Symmetric factorial design makes 7+2*x-3*z independently known.
        rows=[[x,z,7+2*x-3*z] for x,z in [(-1,-1),(-1,1),(1,-1),(1,1),(0,0)]]
        fit=reference.decompose(rows,True)
        for actual,expected in zip(fit['coefficients'],[7,2,-3]):self.assertAlmostEqual(actual,expected)
        scaled=[[row[0]*1e6,row[1]*1e-6,row[2]] for row in rows]
        second=reference.decompose(scaled,True)
        self.assertAlmostEqual(fit['scaledInfinityCondition'],second['scaledInfinityCondition'])
        self.assertAlmostEqual(second['coefficients'][1],2e-6);self.assertAlmostEqual(second['coefficients'][2],-3e6)

    def test_invalid_or_unsupported_model_intent_rejected_before_native_launch(self):
        variants=[]
        for key,value in [('operation','lm'),('formula','y~system("bad")'),('training',[[1,2],[2,3]]),
            ('training',[[0,1],[0,2],[0,3],[0,4]]),('training',[[0,1],[1,2],[2,float('nan')],[3,4]]),
            ('heldout',[]),('predictors',[{'name':'bad name','unit':'V'}])]:
            doc=document();doc[key]=value;variants.append(doc)
        doc=document();doc['predictors'][0]['name']='reading';variants.append(doc)
        doc=document();doc['response']['unit']='V\n';variants.append(doc)
        doc=document();doc['training'][0].append(2);variants.append(doc)
        doc=document();doc['predictors'][0]['name']='intercept';variants.append(doc)
        for doc in variants:
            with self.subTest(doc=doc),patch.object(adaptor,'execute') as execute,self.assertRaises(SchemaxisError):
                adaptor.run(doc,'/never-created',executable='/bin/true')
            execute.assert_not_called()
        near=[[x,x+delta,10+x] for x,delta in [(1,0),(2,1e-8),(3,-1e-8),(4,2e-8),(5,0)]]
        with self.assertRaises(SchemaxisError) as caught:reference.decompose(near,True)
        self.assertIn(caught.exception.fault.code,('RANK_DEFICIENT_DATA','ILL_CONDITIONED_DATA'))

    def test_invalid_requirement_scopes_names_bounds_and_sample_indices(self):
        values=[{'name':'a','scope':'heldout','metric':'prediction','sampleIndex':2,'maximum':20},
            {'name':'a','scope':'training','metric':'rmse','minimum':0,'maximum':1},
            {'name':'a','scope':'training','metric':'maxAbsoluteError','maximum':-1},
            {'name':'a','scope':'training','metric':'prediction','sampleIndex':0,'minimum':10,'maximum':0},
            {'name':'a','scope':'training','metric':'prediction','sampleIndex':0},
            {'name':'Bad Name','scope':'training','metric':'rmse','maximum':1}]
        for requirement in values:
            doc=document();doc['requirements']=[requirement]
            with self.subTest(requirement=requirement),self.assertRaises(SchemaxisError):adaptor.plan(doc)
        doc=document();del doc['heldout']
        with self.assertRaises(SchemaxisError):adaptor.plan(doc)
        doc=document();doc['requirements'].append(copy.deepcopy(doc['requirements'][0]))
        with self.assertRaises(SchemaxisError):adaptor.plan(doc)

    def test_projected_scaled_input_and_prediction_overflow_rejected_in_plan(self):
        doc=document();doc.pop('requirements');doc['training']=[[x*1e-99,y] for x,y in doc['training']]
        doc['heldout']=[[1e9,0]]
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        self.assertEqual(caught.exception.fault.code,'INVALID_PREDICTION')
        prepared={'intercept':False}
        with self.assertRaises(SchemaxisError) as caught:reference.predicted(prepared,[1e200,0],[1e200])
        self.assertEqual(caught.exception.fault.code,'INVALID_PREDICTION')

    def test_error_metrics_do_not_underflow_or_overflow_when_squaring(self):
        for value in (1e-200,1e100):
            metrics=reference.metrics([[0,0,0,value],[1,0,0,-value]])
            self.assertTrue(math.isclose(metrics['rmse'],value,rel_tol=1e-15));self.assertEqual(metrics['maxAbsoluteError'],value)

    @unittest.skipUnless(hasattr(os,'mkfifo'),'requires FIFO support')
    def test_retained_reads_reject_fifos_and_descriptor_race_without_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fifo=root/'pipe';os.mkfifo(fifo);regular=root/'model.rds';regular.write_bytes(b'model')
            with self.assertRaises(SchemaxisError) as caught:adaptor.payload(root,'pipe')
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            descriptor=os.open(fifo,os.O_RDONLY|os.O_NONBLOCK)
            with patch.object(adaptor.os,'open',return_value=descriptor):
                with self.assertRaises(SchemaxisError) as caught:adaptor.payload(root,'model.rds')
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            with self.assertRaises(OSError):os.fstat(descriptor)  # rejected descriptor was closed
            with regular.open('wb') as stream:stream.truncate(adaptor.MAX_BYTES+1)
            with patch.object(adaptor.os,'open',side_effect=AssertionError('size rejected before open')):
                with self.assertRaises(SchemaxisError):adaptor.payload(root,'model.rds')

    def test_unwritable_or_non_directory_output_fails_with_structured_fault(self):
        with tempfile.TemporaryDirectory() as temp:
            parent=Path(temp)/'file';parent.write_text('not a directory')
            with patch.object(adaptor.os,'access',return_value=True),self.assertRaises(SchemaxisError) as caught:
                adaptor.run(document(),parent/'run',executable=str(Path(sys.executable).resolve()))
            self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE')

    def test_public_analytic_study_query_and_deterministic_plan(self):
        from schemaxis.adaptors import registry
        doc=document();doc['requirements'][0]['maximum']={'$analytic':{'type':'values','values':[.17,.2]}}
        prepared=adaptor.plan(doc);self.assertEqual(len(prepared['visits']),2)
        self.assertEqual([v['plan']['requirements'][0]['maximum'] for v in prepared['visits']],[.17,.2])
        self.assertEqual(registry.query(doc)['adaptors'][0]['operations'],['linearRegression'])

    def fake_run(self,root,doc=None):
        doc=doc or document();prepared=adaptor.plan(doc);output=root/'run'
        def execute(command,directory,stage,timeout,environment=None):
            atomic_json(directory/(stage+'-submission.json'),{'exitCode':0,'nativeCommand':command,'interpreter':{'executable':sys.executable}})
            atomic_json(directory/(stage+'-inputs.json'),{str(path):file_digest(path) for path in adaptor.stage_inputs(directory,prepared,stage)})
            for suffix in ('.stdout','.stderr'):(directory/(stage+suffix)).write_text('')
            if stage=='fit':(directory/'model.rds').write_bytes(b'synthetic RDS fixture: native-only decode')
            (directory/(stage+'-runtime.txt')).write_text('R version 4.6.1 (2026-06-24)\n')
            # Literal independently known fit is intercept10/slope2.
            write_csv(directory/(stage+'-coefficients.csv'),{'columns':['coefficientIndex','scaledCoefficient'],
                'rows':[[0,10],[1,2*prepared['scales'][1]]]})
            write_csv(directory/(stage+'-metadata.csv'),{'columns':['rank','residualDF'],'rows':[[2,2]]})
            for scope in ('training','heldout'):
                if scope not in prepared:continue
                rows=[]
                for i,(x,y) in enumerate(prepared[scope]):
                    predicted=10+2*x;residual=y-predicted
                    rows.append([i,y,predicted,residual]+([predicted,residual] if scope=='training' else []))
                write_csv(directory/(stage+'-'+scope+'.csv'),{'columns':['sample','observed','prediction','residual']+
                    (['fitted','fitResidual'] if scope=='training' else []),'rows':rows})
        with patch.object(adaptor,'execute',side_effect=execute),patch.object(adaptor.os,'access',return_value=True):
            adaptor.run(doc,output,executable=str(Path(sys.executable).resolve()))
        return output

    def refresh(self,output):
        prepared=adaptor.plan(json.loads((output/'authored.json').read_text()))
        receipt=json.loads((output/'verification.json').read_text());receipt['artifacts']=adaptor.manifest(output,prepared)
        receipt['evidence']={name:file_digest(output/name) for name in adaptor.evidence_names(prepared)}
        atomic_json(output/'verification.json',receipt);finalise(output)

    def test_native_reopen_fixture_and_signed_prediction_margin(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));result=adaptor.verify(output)
            self.assertTrue(result['acceptance']['accepted']);self.assertAlmostEqual(result['metrics']['training']['rmse'],math.sqrt(.025))
        prepared=adaptor.plan(document());prepared['requirements']=[{'name':'low','scope':'heldout','metric':'prediction','sampleIndex':0,'minimum':-5}]
        tables={'heldout':{'rows':[[0,-6,-6,0],[1,2,2,0]]}}
        report=reference.assess(prepared,tables);self.assertEqual(report['requirements'][0]['checks'][0]['margin'],-1)
        self.assertFalse(report['accepted'])

    def test_unmet_fit_retains_native_evidence_and_never_succeeds(self):
        doc=document();doc['requirements'][0]['maximum']=.01
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SchemaxisError) as caught:self.fake_run(Path(temp),doc)
            self.assertEqual(caught.exception.fault.code,'FIT_REQUIREMENT_NOT_MET')
            output=Path(temp)/'run';self.assertTrue((output/'model.rds').is_file())
            self.assertFalse(json.loads((output/'result.json').read_text())['verified'])
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output,require_result=False)
            self.assertEqual(caught.exception.fault.code,'FIT_REQUIREMENT_NOT_MET')

    def test_changed_rds_cannot_use_stale_reopen_even_after_ordinary_hash_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));(output/'model.rds').write_bytes(b'changed model')
            self.refresh(output)
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            self.assertIn('consumed different input/model',caught.exception.fault.message)

    def test_forged_native_coefficients_and_acceptance_rejected_with_refreshed_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp))
            for stage in ('fit','reopen'):
                write_csv(output/(stage+'-coefficients.csv'),{'columns':['coefficientIndex','scaledCoefficient'],'rows':[[0,100],[1,2]]})
            self.refresh(output)
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));doc=json.loads((output/'authored.json').read_text());doc['requirements'][0]['maximum']=.01
            atomic_json(output/'authored.json',doc);atomic_json(output/'plan.json',adaptor.plan(doc))
            summary=json.loads((output/'regression-summary.json').read_text());summary['acceptance']['requirements'][0]['maximum']=.01
            summary['acceptance']['requirements'][0]['checks'][0].update(expected=.01,passed=True,margin=.01)
            atomic_json(output/'regression-summary.json',summary);self.refresh(output)
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_worker_completion_symlink_and_final_deadline_faults_are_structured(self):
        for name in ('worker.R','fit-launcher.py','reopen-inputs.json','training.csv'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                output=self.fake_run(Path(temp));(output/name).write_bytes((output/name).read_bytes()+b'corrupt');self.refresh(output)
                with self.assertRaises(SchemaxisError):adaptor.verify(output)
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));path=output/'fit-submission.json';submission=json.loads(path.read_text());submission['exitCode']=1
            atomic_json(path,submission);self.refresh(output)
            with self.assertRaises(SchemaxisError):adaptor.verify(output)
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));path=output/'model.rds';copy=output/'other';path.rename(copy)
            try:path.symlink_to(copy)
            except OSError:
                if os.name!='nt':raise
            else:
                with self.assertRaises(SchemaxisError):adaptor.verify(output)
        with tempfile.TemporaryDirectory() as temp,patch.object(adaptor.time,'monotonic',return_value=0) as clock:
            original=adaptor.verify
            def finish(*args,**kwargs):
                result=original(*args,**kwargs);clock.return_value=301;return result
            with patch.object(adaptor,'verify',side_effect=finish),self.assertRaises(SchemaxisError) as caught:self.fake_run(Path(temp))
            self.assertEqual(caught.exception.fault.code,'RUNNER_TIMED_OUT')


if __name__=='__main__':unittest.main()
