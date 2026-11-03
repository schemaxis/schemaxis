# Copyright (C) 2026 David L F Gaden
"""Classical OLS coefficient inference: closed forms, exact normal equations and evidence attacks."""
import copy
from fractions import Fraction
import json
import math
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


def document(name='inference'):
    return json.loads((ROOT/f'examples/schemaxis/r-{name}.json').read_text())


def exact(rows,intercept):
    """Exact rational OLS by normal equations, independent of the Householder path."""
    design=[[Fraction(1)]*intercept+[Fraction(v) for v in row[:-1]] for row in rows];y=[Fraction(row[-1]) for row in rows]
    p=len(design[0]);gram=[[sum(r[i]*r[j] for r in design) for j in range(p)]+[Fraction(int(i==k)) for k in range(p)] for i in range(p)]
    for c in range(p):
        pivot=next(r for r in range(c,p) if gram[r][c]!=0);gram[c],gram[pivot]=gram[pivot],gram[c]
        gram[c]=[v/gram[c][c] for v in gram[c]]
        for r in range(p):
            if r!=c:gram[r]=[a-gram[r][c]*b for a,b in zip(gram[r],gram[c])]
    inverse=[row[p:] for row in gram]
    xty=[sum(r[j]*v for r,v in zip(design,y)) for j in range(p)]
    beta=[sum(inverse[i][j]*xty[j] for j in range(p)) for i in range(p)]
    fitted=[sum(b*v for b,v in zip(beta,r)) for r in design];residuals=[a-b for a,b in zip(y,fitted)]
    df=len(rows)-p;rss=sum(r*r for r in residuals);variance=rss/df
    centre=sum(fitted)/len(fitted) if intercept else 0;mss=sum((f-centre)**2 for f in fitted)
    return {'beta':beta,'variance':variance,'covariance':[inverse[j][j]*variance for j in range(p)],'df':df,
            'rSquared':mss/(mss+rss),'f':(mss/(p-intercept))/variance,'numerator':p-intercept}


class DistributionTests(unittest.TestCase):
    def test_student_t_and_f_tails_match_closed_forms(self):
        for t in (1e-3,.5,1,2,28.284271247461902,1e3,1e7):
            s=math.sqrt(2+t*t)
            for df,expected in ((1,2/math.pi*math.atan(1/t)),(2,2/(s*(s+t)))):
                self.assertLess(abs(reference.t_two_sided(t,df)-expected)/expected,1e-13,(t,df))
        for f in (.01,1,3,800):
            for d2 in (1,2,7,60):
                expected=(1+2*f/d2)**(-d2/2)
                self.assertLess(abs(reference.f_upper(f,2,d2)-expected)/expected,1e-12,(f,d2))
                self.assertLess(abs(reference.f_upper(f,1,d2)-reference.t_two_sided(math.sqrt(f),d2))/reference.t_two_sided(math.sqrt(f),d2),1e-12)
        self.assertEqual(reference.t_two_sided(0,5),1.0);self.assertEqual(reference.f_upper(0,2,5),1.0)

    def test_critical_values_match_closed_forms_and_published_quantile(self):
        for level in (.5,.9,.95,.99,.999):
            self.assertTrue(math.isclose(reference.t_quantile(level,1),math.tan(math.pi*level/2),rel_tol=1e-12))
            self.assertTrue(math.isclose(reference.t_quantile(level,2),level*math.sqrt(2/(1-level*level)),rel_tol=1e-12))
        # Widely tabulated t(0.975, 10) = 2.228138851986...
        self.assertTrue(math.isclose(reference.t_quantile(.95,10),2.228138851986,rel_tol=1e-11))
        self.assertLess(reference.t_quantile(.95,511),reference.t_quantile(.95,10))


class InferenceTests(unittest.TestCase):
    def inferred(self,doc):
        prepared=adaptor.plan(doc);return prepared,reference.inference(prepared,reference.decompose(prepared['training'],prepared['intercept']))

    def test_known_calibration_closed_forms(self):
        prepared,inferred=self.inferred(document())
        slope=inferred['coefficients'][1];scale=prepared['scales'][1];s=math.sqrt(802)
        self.assertEqual((inferred['residualDF'],inferred['fNumeratorDF']),(2,1))
        expected={'se':math.sqrt(.005),'t':20*math.sqrt(2),'p':2/(s*(s+20*math.sqrt(2))),'q':.95*math.sqrt(2/.0975)}
        self.assertTrue(math.isclose(slope['scaledStandardError']/scale,expected['se'],rel_tol=1e-12))
        self.assertTrue(math.isclose(slope['tStatistic'],expected['t'],rel_tol=1e-12))
        self.assertTrue(math.isclose(slope['pValue'],expected['p'],rel_tol=1e-12))
        self.assertTrue(math.isclose(inferred['criticalValue'],expected['q'],rel_tol=1e-12))
        self.assertTrue(math.isclose(slope['scaledLower']/scale,2-expected['q']*expected['se'],rel_tol=1e-12))
        self.assertTrue(math.isclose(inferred['sigma'],math.sqrt(.05),rel_tol=1e-12))
        self.assertTrue(math.isclose(inferred['rSquared'],400/401,rel_tol=1e-13))
        self.assertTrue(math.isclose(inferred['adjustedRSquared'],1-1.5/401,rel_tol=1e-13))
        self.assertTrue(math.isclose(inferred['fStatistic'],800,rel_tol=1e-12))
        self.assertTrue(math.isclose(inferred['fPValue'],expected['p'],rel_tol=1e-11))

    def test_exact_normal_equations_agree_with_qr_inference(self):
        through_origin=document();through_origin.pop('requirements');through_origin.pop('heldout');through_origin['intercept']=False
        through_origin['training']=[[1,2.1],[2,3.9],[3,5.9],[4,8.1]]
        correlated=document();correlated.pop('requirements');correlated.pop('heldout')
        correlated['predictors']=[{'name':'a','unit':'K'},{'name':'b','unit':'Pa'},{'name':'c','unit':'s'}]
        state=12345;rows=[]
        for i in range(12):
            values=[]
            for _ in range(4):
                state=(1103515245*state+12345)%2**31;values.append(round(state/2**31*4-2,3))
            a,b,c,noise=values;b=round(.6*a+.4*b,3)  # deliberately correlated predictors
            rows.append([a,b*1e3,c*1e-3,round(5+2*a-.003*b*1e3+400*c*1e-3+.1*noise,6)])
        correlated['training']=rows
        for doc in (document(),document('inference-variant'),through_origin,correlated):
            with self.subTest(predictors=len(doc['predictors']),intercept=doc.get('intercept',True)):
                prepared,inferred=self.inferred(doc);known=exact(prepared['training'],prepared['intercept'])
                self.assertEqual(inferred['residualDF'],known['df'])
                for j,(item,scale) in enumerate(zip(inferred['coefficients'],prepared['scales'])):
                    se=math.sqrt(known['covariance'][j])
                    self.assertTrue(math.isclose(item['scaledEstimate']/scale,float(known['beta'][j]),rel_tol=1e-9,abs_tol=1e-12))
                    self.assertTrue(math.isclose(item['scaledStandardError']/scale,se,rel_tol=1e-9))
                    self.assertTrue(math.isclose(item['tStatistic'],float(known['beta'][j])/se,rel_tol=1e-9,abs_tol=1e-9))
                    self.assertTrue(math.isclose((item['scaledUpper']-item['scaledLower'])/2/scale,inferred['criticalValue']*se,rel_tol=1e-9))
                self.assertTrue(math.isclose(inferred['sigma'],math.sqrt(known['variance']),rel_tol=1e-9))
                self.assertTrue(math.isclose(1-inferred['rSquared'],float(1-known['rSquared']),rel_tol=1e-8))
                self.assertTrue(math.isclose(inferred['fStatistic'],float(known['f']),rel_tol=1e-8))
                self.assertEqual(inferred['fNumeratorDF'],known['numerator'])
        prepared,inferred=self.inferred(through_origin)
        self.assertTrue(math.isclose(inferred['rSquared'],120/120.04,rel_tol=1e-12))  # uncentred
        self.assertTrue(math.isclose(inferred['fStatistic'],9000,rel_tol=1e-11))

    def test_inference_faults_precede_native_launch(self):
        cases=[('r-inference-exact-invalid',None,'NO_RESIDUAL_VARIANCE','$.inference')]
        def variant(change):
            doc=document();change(doc);return doc
        def tiny(doc):
            doc.pop('requirements');doc['training']=[[x,y*1e-150] for x,y in doc['training']];doc['heldout']=[[0,1e-149]]
        def through_origin_intercept(doc):
            doc['intercept']=False;doc['requirements'][2]['term']='intercept'
        def interval_without_inference(doc):doc.pop('inference')
        changes=[(tiny,'UNSUPPORTED_INFERENCE','$.training'),
            (lambda d:d['inference'].update(level=1),'INVALID_ARGUMENT','$.arguments.inference.level'),
            (lambda d:d['inference'].update(level=.4),'INVALID_ARGUMENT','$.arguments.inference.level'),
            (lambda d:d['inference'].update(alpha=.05),'UNKNOWN_ARGUMENT','$.arguments.inference'),
            (interval_without_inference,'INVALID_REQUIREMENT','$.inference'),
            (lambda d:d['requirements'][2].update(scope='heldout'),'INVALID_REQUIREMENT','$.requirements[2].scope'),
            (lambda d:d['requirements'][2].update(term='pressure'),'INVALID_REQUIREMENT','$.requirements[2].term'),
            (through_origin_intercept,'INVALID_REQUIREMENT','$.requirements[2].term'),
            (lambda d:d['requirements'][2].pop('term'),'INVALID_REQUIREMENT','$.requirements[2].term'),
            (lambda d:d['requirements'][0].update(term='temperature'),'INVALID_REQUIREMENT','$.requirements[0].term'),
            (lambda d:d['requirements'][2].update(sampleIndex=0),'INVALID_REQUIREMENT','$.requirements[2].sampleIndex'),
            (lambda d:[d['requirements'][2].pop(k) for k in ('minimum','maximum')],'INVALID_REQUIREMENT','$.requirements[2]'),
            (lambda d:d['requirements'][2].update(minimum=3,maximum=2),'INVALID_REQUIREMENT','$.requirements[2]'),
            (lambda d:d.update(training=[[2,6.1],[2,7.8],[2,12.2],[2,13.9]]),'RANK_DEFICIENT_DATA','$.training'),
            (lambda d:d.update(training=d['training'][:2]),'INVALID_ARGUMENT','$.arguments.training')]
        for change,code,location in changes:
            doc=variant(change)
            with self.subTest(code=code,location=location),patch.object(adaptor,'execute') as execute:
                with self.assertRaises(SchemaxisError) as caught:adaptor.run(doc,'/never-created',executable='/bin/true')
                self.assertEqual((caught.exception.fault.code,caught.exception.fault.location),(code,location))
                execute.assert_not_called()
        doc=document('inference-exact-invalid')
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        fault=caught.exception.fault.to_dict();self.assertEqual((fault['code'],fault['location']),cases[0][2:])
        self.assertIn('recovery',fault);self.assertLess(fault['observed']['residualStandardError'],fault['observed']['minimumResidualStandardError'])
        # n == p: four rows cannot estimate four coefficients and a residual variance.
        doc=document('inference-variant');doc['predictors']+=[{'name':'humidity','unit':'percent'},{'name':'pressure','unit':'kPa'}]
        doc['training']=[[x,x*x,x**3,y] for x,y in doc['training'][:4]];doc['heldout']=[[0,0,0,10]];doc['requirements']=doc['requirements'][:2]
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        self.assertEqual(caught.exception.fault.code,'INSUFFICIENT_DATA')

    def test_schema_matches_planner_for_interval_requirements(self):
        import jsonschema
        validator=jsonschema.Draft202012Validator(adaptor.schema())
        for name in ('inference','inference-variant','inference-exact-invalid'):validator.validate(document(name))
        rejected=[]
        for change in (lambda d:d['requirements'][2].update(scope='heldout'),lambda d:d['requirements'][2].pop('term'),
                       lambda d:[d['requirements'][2].pop(k) for k in ('minimum','maximum')],lambda d:d['requirements'][0].update(term='temperature'),
                       lambda d:d['inference'].update(level=1),lambda d:d['inference'].update(alpha=.05),lambda d:d['requirements'][2].update(term='Bad')):
            doc=document();change(doc);rejected.append(not validator.is_valid(doc))
            with self.assertRaises(SchemaxisError):adaptor.plan(doc)
        self.assertTrue(all(rejected))
        self.assertEqual(adaptor.plan({**document(),'inference':{}})['inference'],{'level':.95})

    def test_level_study_visits_are_independent_plans(self):
        doc=document();doc['inference']['level']={'$analytic':{'type':'values','values':[.9,.99]}}
        prepared=adaptor.plan(doc)
        self.assertEqual([v['plan']['inference']['level'] for v in prepared['visits']],[.9,.99])

    def test_comparison_tolerances_are_tight_and_p_values_follow_t(self):
        prepared,expected=self.inferred(document())
        tolerance=reference.response_tolerance(prepared['training'],prepared['scaledInfinityCondition'])
        native=copy.deepcopy(expected);self.assertIsNone(reference.compare_inference(native,expected,tolerance))
        for path,factor,name in ((('sigma',),1+1e-3,'sigma'),(('coefficients',1,'scaledStandardError'),1+1e-3,'scaledStandardError'),
                                 (('coefficients',1,'pValue'),1.01,'pValue'),(('fPValue',),.99,'fPValue'),
                                 (('criticalValue',),1+1e-9,'criticalValue'),(('coefficients',0,'scaledUpper'),1+1e-3,'scaledUpper')):
            changed=copy.deepcopy(expected);target=changed
            for key in path[:-1]:target=target[key]
            target[path[-1]]*=factor
            self.assertEqual(reference.compare_inference(changed,expected,tolerance),name)
        # p-value fidelity is the independent image of the t tolerance, not a free threshold.
        changed=copy.deepcopy(expected);changed['coefficients'][1]['pValue']*=1+1e-6
        self.assertIsNone(reference.compare_inference(changed,expected,tolerance))
        changed=copy.deepcopy(expected);changed['level']=.9500000000000001
        self.assertEqual(reference.compare_inference(changed,expected,tolerance),'level')


class InferenceEvidenceTests(unittest.TestCase):
    def fake_run(self,root,doc=None):
        doc=doc or document();prepared=adaptor.plan(doc);output=root/'run'
        independent=reference.decompose(prepared['training'],prepared['intercept']);inferred=reference.inference(prepared,independent)
        def execute(command,directory,stage,timeout,environment=None):
            atomic_json(directory/(stage+'-submission.json'),{'exitCode':0,'nativeCommand':command,'interpreter':{'executable':sys.executable}})
            atomic_json(directory/(stage+'-inputs.json'),{str(path):file_digest(path) for path in adaptor.stage_inputs(directory,prepared,stage)})
            for suffix in ('.stdout','.stderr'):(directory/(stage+suffix)).write_text('')
            if stage=='fit':(directory/'model.rds').write_bytes(b'synthetic RDS fixture: native-only decode')
            (directory/(stage+'-runtime.txt')).write_text('R version 4.6.1 (2026-06-24)\n')
            write_csv(directory/(stage+'-coefficients.csv'),{'columns':['coefficientIndex','scaledCoefficient'],
                'rows':[[i,v] for i,v in enumerate(independent['scaledCoefficients'])]})
            write_csv(directory/(stage+'-metadata.csv'),{'columns':['rank','residualDF'],'rows':[[prepared['rank'],prepared['residualDF']]]})
            for scope in ('training','heldout'):
                if scope not in prepared:continue
                rows=[]
                for i,row in enumerate(prepared[scope]):
                    predicted=reference.predicted(prepared,row,independent['coefficients']);residual=row[-1]-predicted
                    rows.append([i,row[-1],predicted,residual]+([predicted,residual] if scope=='training' else []))
                write_csv(directory/(stage+'-'+scope+'.csv'),{'columns':['sample','observed','prediction','residual']+
                    (['fitted','fitResidual'] if scope=='training' else []),'rows':rows})
            write_csv(directory/(stage+'-inference.csv'),{'columns':adaptor.INFERENCE_COLUMNS,
                'rows':[[i]+[item[k] for k in adaptor.INFERENCE_COLUMNS[1:]] for i,item in enumerate(inferred['coefficients'])]})
            write_csv(directory/(stage+'-statistics.csv'),{'columns':adaptor.STATISTICS_COLUMNS,'rows':[[inferred[k] for k in adaptor.STATISTICS_COLUMNS]]})
        with patch.object(adaptor,'execute',side_effect=execute),patch.object(adaptor.os,'access',return_value=True):
            adaptor.run(doc,output,executable=str(Path(sys.executable).resolve()))
        return output

    def refresh(self,output):
        prepared=adaptor.plan(json.loads((output/'authored.json').read_text()))
        receipt=json.loads((output/'verification.json').read_text());receipt['artifacts']=adaptor.manifest(output,prepared)
        receipt['evidence']={name:file_digest(output/name) for name in adaptor.evidence_names(prepared)}
        atomic_json(output/'verification.json',receipt);finalise(output)

    def test_publications_append_inference_and_preserve_existing_indices(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));result=adaptor.verify(output)
            self.assertEqual(result['inference'],{'level':.95,'residualDF':2})
            names=[Path(a['file']).name for a in json.loads((output/'verification.json').read_text())['artifacts']]
            self.assertEqual(names,['coefficients.csv','training.csv','heldout.csv','regression-summary.json','inference.csv'])
            summary=json.loads((output/'regression-summary.json').read_text())['inference']
            self.assertEqual([c['units'] for c in summary['coefficients']],['V','V/degC'])
            self.assertEqual(summary['rSquaredBasis'],'centred on the mean response')
            self.assertTrue(math.isclose(summary['coefficients'][1]['standardError'],math.sqrt(.005),rel_tol=1e-12))
            self.assertTrue(any('normally distributed' in a for a in summary['assumptions']))
            item=json.loads((output/'regression-summary.json').read_text())['acceptance']['requirements'][2]
            self.assertTrue(item['accepted']);self.assertEqual(item['units'],'V/degC')
            self.assertTrue(math.isclose(item['checks'][0]['margin'],2-.95*math.sqrt(2/.0975)*math.sqrt(.005)-1.5,rel_tol=1e-12))
        plain=document('regression');self.assertEqual([n for n,_ in adaptor.publications(adaptor.plan(plain))][-1],'regression-summary.json')

    def test_imprecise_but_centred_slope_is_unmet_and_blocks_success(self):
        doc=document();doc['requirements'][2].update(minimum=1.9,maximum=2.1)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SchemaxisError) as caught:self.fake_run(Path(temp),doc)
            self.assertEqual(caught.exception.fault.code,'FIT_REQUIREMENT_NOT_MET')
            failed=[r for r in caught.exception.fault.observed['assessment']['requirements'] if not r['accepted']]
            self.assertEqual([r['name'] for r in failed],['slope_interval'])
            self.assertEqual({c['bound'] for c in failed[0]['checks'] if not c['passed']},{'minimum','maximum'})
            self.assertTrue(math.isclose(failed[0]['observed']['estimate'],2,rel_tol=1e-12))
            output=Path(temp)/'run';self.assertFalse(json.loads((output/'result.json').read_text())['verified'])
            with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output,require_result=False)
            self.assertEqual(caught.exception.fault.code,'FIT_REQUIREMENT_NOT_MET')

    def test_forged_native_inference_rejected_after_ordinary_hash_refresh(self):
        def p_value(output):
            for stage in ('fit','reopen'):
                path=output/(stage+'-inference.csv');lines=path.read_text().splitlines();cells=lines[2].split(',');cells[4]=repr(float(cells[4])*1.01)
                lines[2]=','.join(cells);path.write_text('\n'.join(lines)+'\n')
        def level(output):
            for stage in ('fit','reopen'):
                path=output/(stage+'-statistics.csv');lines=path.read_text().splitlines();cells=lines[1].split(',');cells[0]='0.9'
                lines[1]=','.join(cells);path.write_text('\n'.join(lines)+'\n')
        def reopen_only(output):
            path=output/'reopen-inference.csv';lines=path.read_text().splitlines();cells=lines[2].split(',');cells[2]=repr(float(cells[2])*(1+1e-6))
            lines[2]=','.join(cells);path.write_text('\n'.join(lines)+'\n')
        def published(output):
            path=output/'inference.csv';lines=path.read_text().splitlines();cells=lines[2].split(',');cells[5]='1.95'
            lines[2]=','.join(cells);path.write_text('\n'.join(lines)+'\n')
        def acceptance(output):
            doc=json.loads((output/'authored.json').read_text());doc['requirements'][2].update(minimum=1.9,maximum=2.1)
            atomic_json(output/'authored.json',doc);atomic_json(output/'plan.json',adaptor.plan(doc))
            summary=json.loads((output/'regression-summary.json').read_text());item=summary['acceptance']['requirements'][2]
            item.update(minimum=1.9,maximum=2.1)
            for check in item['checks']:check.update(expected=1.9 if check['bound']=='minimum' else 2.1,passed=True,margin=.01)
            atomic_json(output/'regression-summary.json',summary)
        def missing(output):(output/'fit-statistics.csv').unlink()
        for forge,message in ((p_value,'pValue'),(level,'level'),(reopen_only,'reopen inference differs'),(published,'inference table'),
                              (acceptance,'summary differs'),(missing,'')):
            with self.subTest(forge=forge.__name__),tempfile.TemporaryDirectory() as temp:
                output=self.fake_run(Path(temp));forge(output)
                if forge is not missing:self.refresh(output)
                with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
                self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED');self.assertIn(message,caught.exception.fault.message)

    def test_native_command_carries_exact_level_and_plain_route_is_unchanged(self):
        prepared=adaptor.plan(document());commands=adaptor.commands('/opt/Rscript',Path('/x'),prepared)
        self.assertEqual(commands['fit'][-1],'0.95');self.assertEqual(float(commands['fit'][-1]),prepared['inference']['level'])
        plain=adaptor.plan(document('regression'))
        self.assertEqual(adaptor.commands('/opt/Rscript',Path('/x'),plain)['fit'][-1],'none')
        self.assertNotIn('fit-inference.csv',adaptor.evidence_names(plain))
        from schemaxis.adaptors.r.worker import WORKER
        for native in ('stats::summary.lm(model)','stats::confint(model, level=level)','stats::pf(','sprintf("%.17g"'):self.assertIn(native,WORKER)


class StudioDiscoveryTests(unittest.TestCase):
    def test_starters_plan_and_unfilled_fields_remain_placeholders(self):
        from schemaxis.studio_library import instantiate_item,load_library,plan_item
        library=load_library('r');items=library['templates']+library['snippets']
        self.assertIn('calibration-inference',[t['id'] for t in library['templates']])
        for item in items:
            with self.subTest(item=item['id']):
                prepared=plan_item(instantiate_item(library,item,provider='r'))
                self.assertEqual(prepared['operation'],'linearRegression')
                if item.get('fields'):
                    self.assertIn('$fill',json.dumps(instantiate_item(library,item,provider='r',filled=False)))
        interval=next(i for i in items if i['id']=='coefficient-interval')
        doc=instantiate_item(library,{**interval,'testValues':{'term':'pressure'}},provider='r')
        with self.assertRaises(SchemaxisError) as caught:plan_item(doc)
        self.assertEqual(caught.exception.fault.code,'INVALID_REQUIREMENT')

    def test_curated_search_cases_cover_kinds_and_match_capability_search(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        result=check_cases(CapabilityCatalogue(['r']),'r')
        self.assertTrue(result['complete'],result)
        observed={item['query']:item['observed'] for item in result['evidence']}
        self.assertEqual(observed['logistic regression'],[])
        self.assertEqual(observed['OLS'],['operation/r/linearRegression'])


if __name__=='__main__':unittest.main()
