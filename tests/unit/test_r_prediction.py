"""Prediction intervals for new predictor-only rows: independent leverage, native boundaries and evidence attacks."""
import copy
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import random
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
RSCRIPT=os.environ.get('SCHEMAXIS_R')


def document(name='prediction'):
    return json.loads((ROOT/f'examples/schemaxis/r-{name}.json').read_text())


def fault(test,callback,code,location=None,message=None):
    with test.assertRaises(SchemaxisError) as caught:callback()
    error=caught.exception.fault
    test.assertEqual(error.code,code,error.to_dict())
    if location is not None:test.assertEqual(error.location,location)
    if message is not None:test.assertIn(message,error.message)
    return error


def exact_leverage(rows,intercept,new):
    """Exact rational h=x'(X'X)^-1x by Gauss-Jordan on the normal equations."""
    design=[[Fraction(1)]*intercept+[Fraction(v) for v in row[:-1]] for row in rows]
    p=len(design[0]);gram=[[sum(r[i]*r[j] for r in design) for j in range(p)]+[Fraction(int(i==k)) for k in range(p)] for i in range(p)]
    for c in range(p):
        pivot=next(r for r in range(c,p) if gram[r][c]!=0);gram[c],gram[pivot]=gram[pivot],gram[c]
        gram[c]=[v/gram[c][c] for v in gram[c]]
        for r in range(p):
            if r!=c:gram[r]=[a-gram[r][c]*b for a,b in zip(gram[r],gram[c])]
    inverse=[row[p:] for row in gram];x=[Fraction(1)]*intercept+[Fraction(v) for v in new]
    return sum(x[i]*inverse[i][j]*x[j] for i in range(p) for j in range(p))


def hadamard_document(level=.95,interval='individual',newdata=None):
    """Orthogonal 16-run design: intercept + eight predictor columns of a Sylvester Hadamard matrix.

    X'X = 16 I, so h = (1 + sum(x^2))/16; the response adds seven unused orthogonal
    columns as noise, so RSS = 16*sum(c^2) and df = 16-9 = 7 are exact literals.
    """
    sign=lambda i,j:-1 if bin(i&j).count('1')%2 else 1
    noise=[.3,-.2,.1,.25,-.15,.2,-.1]
    rows=[[sign(i,j) for j in range(1,9)]+[10+sum(.5*j*sign(i,j) for j in range(1,9))+sum(c*sign(i,8+k) for k,c in enumerate(noise,1))] for i in range(16)]
    return {'version':'schemaxis.r/1','operation':'linearRegression','predictors':[{'name':f'x{j}','unit':'m'} for j in range(1,9)],
        'response':{'name':'reading','unit':'V'},'training':rows,
        'prediction':{'interval':interval,'level':level,'newdata':newdata or [[1,-1,1,-1,1,-1,1,-1],[0]*8,[2]*8]}}


HADAMARD_SIGMA=math.sqrt(16*.275/7)
T_975_DF7=2.364624251592785


def swapped_native(truth,confidence_kind='individual',individual_kind='confidence'):
    return {**{k:truth[k] for k in ('level','residualDF','criticalValue','sigma')},'individualSigma':truth['sigma'],
        'rows':[{'sample':i,'fit':r['fit'],'seFit':r['confidence']['standardError'],'confidenceLower':r[confidence_kind]['lower'],'confidenceUpper':r[confidence_kind]['upper'],
            'individualLower':r[individual_kind]['lower'],'individualUpper':r[individual_kind]['upper']} for i,r in enumerate(truth['rows'])]}


def resolution_case(p,n,ratio,*,offset=9e8,scale=1.0,shift=0.0,intercept=True,level=.5,leverage=1e4,seed=1):
    """Deterministic p-predictor design with residual sigma = ratio*(NO_RESIDUAL_VARIANCE floor) and a new point at the requested leverage."""
    rnd=random.Random(seed);unit=[[rnd.uniform(-1,1) for _ in range(p)] for _ in range(n)]
    rows_x=[[u*scale+shift for u in row] for row in unit];base=[offset+sum((j+1)*u for j,u in enumerate(row)) for row in unit]
    noise=[rnd.gauss(0,1) for _ in range(n)]
    for _ in range(5):
        rows=[x+[b+e] for x,b,e in zip(rows_x,base,noise)];independent=reference.decompose(rows,intercept)
        residuals=[row[-1]-sum(c*f for c,f in zip(independent['coefficients'],([1.0] if intercept else [])+row[:-1])) for row in rows]
        sigma=math.hypot(*residuals)/math.sqrt(n-p-int(intercept));floor=reference.VARIANCE_RATIO*reference.response_tolerance(rows,independent['scaledInfinityCondition'])
        noise=[e*ratio*floor/sigma for e in noise]
    rows=[x+[b+e] for x,b,e in zip(rows_x,base,noise)];independent=reference.decompose(rows,intercept)
    def prepared(row):
        return {'training':rows,'intercept':intercept,'predictors':[{'name':f'x{j}'} for j in range(p)],'prediction':{'level':level,'newdata':[row]},'residualDF':n-p-int(intercept)}
    def reached(c):
        row=[c*scale+shift]*p
        try:return reference.leverage(prepared(row),independent,row,'$')[0]
        except SchemaxisError:return math.inf
    low,high=0.0,1.0
    while reached(high)<leverage:high*=2
    for _ in range(60):
        middle=(low+high)/2
        if reached(middle)<leverage:low=middle
        else:high=middle
    return prepared([low*scale+shift]*p),independent,reference.response_tolerance(rows,independent['scaledInfinityCondition'])


def without_guard(prepared,independent):
    with patch.object(reference,'RESOLUTION_FACTOR',0):return reference.prediction_intervals(prepared,independent)


def expected(doc):
    prepared=adaptor.plan(doc);independent=reference.decompose(prepared['training'],prepared['intercept'])
    return prepared,independent,reference.prediction_intervals(prepared,independent)


class IndependentMeaningTests(unittest.TestCase):
    def test_closed_form_two_df_intervals_and_exact_rational_leverage(self):
        prepared,independent,result=expected(document())
        sigma=math.sqrt(.05);t=.95*math.sqrt(2/(1-.95**2))
        self.assertEqual(result['residualDF'],2);self.assertTrue(math.isclose(result['criticalValue'],t,rel_tol=1e-12))
        self.assertTrue(math.isclose(result['sigma'],sigma,rel_tol=1e-12))
        for row,x in zip(result['rows'],(0,1,3)):
            h=.25+x*x/10;fit=10+2*x
            self.assertTrue(math.isclose(row['leverage'],h,rel_tol=1e-12));self.assertAlmostEqual(row['fit'],fit,places=12)
            self.assertEqual(float(exact_leverage(prepared['training'],True,[x])),float(Fraction(h).limit_denominator(1000)))
            for kind,factor in (('confidence',h),('individual',1+h)):
                half=t*sigma*math.sqrt(factor)
                self.assertTrue(math.isclose(row[kind]['halfWidth'],half,rel_tol=1e-12),(kind,x))
                self.assertTrue(math.isclose(row[kind]['upper']-row[kind]['lower'],2*half,rel_tol=1e-12))
            self.assertGreater(row['individual']['halfWidth'],row['confidence']['halfWidth'])
        self.assertEqual([r['outsideTrainingRange'] for r in result['rows']],[[],[],['temperature']])

    def test_multi_predictor_no_intercept_leverage_matches_exact_rational_normal_equations(self):
        doc=document();doc['predictors']=[{'name':'a','unit':'m'},{'name':'b','unit':'s'}]
        doc['training']=[[1,.5,3.1],[2,1.5,5.2],[3,.5,6.9],[4,2.5,9.4],[5,1,11.1],[6,3,13.2]]
        doc['intercept']=True;doc['prediction']['newdata']=[[3,1],[7,.25]]
        prepared,independent,result=expected(doc)
        for row,new in zip(result['rows'],doc['prediction']['newdata']):
            self.assertTrue(math.isclose(row['leverage'],float(exact_leverage(prepared['training'],True,new)),rel_tol=1e-9))
        doc['intercept']=False;doc['training']=[[r[0],r[1],r[2]] for r in doc['training']]
        prepared,independent,result=expected(doc)
        for row,new in zip(result['rows'],doc['prediction']['newdata']):
            self.assertTrue(math.isclose(row['leverage'],float(exact_leverage(prepared['training'],False,new)),rel_tol=1e-9))

    def test_unit_scale_and_translation_leave_interval_widths_unchanged(self):
        _,_,base=expected(document())
        for factor in (1e-6,1e6):
            doc=document();doc['training']=[[x*factor,y] for x,y in doc['training']];doc['prediction']['newdata']=[[x*factor] for [x] in doc['prediction']['newdata']]
            _,_,scaled=expected(doc)
            for a,b in zip(base['rows'],scaled['rows']):
                self.assertTrue(math.isclose(a['leverage'],b['leverage'],rel_tol=1e-9),factor)
                self.assertTrue(math.isclose(a['individual']['halfWidth'],b['individual']['halfWidth'],rel_tol=1e-9))
        doc=document();doc['training']=[[x+20,y] for x,y in doc['training']];doc['prediction']['newdata']=[[x+20] for [x] in doc['prediction']['newdata']]
        _,_,shifted=expected(doc)
        for a,b in zip(base['rows'],shifted['rows']):self.assertTrue(math.isclose(a['confidence']['halfWidth'],b['confidence']['halfWidth'],rel_tol=1e-7))
        doc=document();doc['training']=[[x,y+1e6] for x,y in doc['training']]
        _,_,offset=expected(doc)
        for a,b in zip(base['rows'],offset['rows']):
            self.assertTrue(math.isclose(a['individual']['halfWidth'],b['individual']['halfWidth'],rel_tol=1e-9))
            self.assertAlmostEqual(b['fit']-a['fit'],1e6,places=6)

    def test_level_changes_critical_value_and_widths(self):
        wide=document();wide['prediction']['level']=.99;narrow=document();narrow['prediction']['level']=.5
        _,_,a=expected(wide);_,_,b=expected(narrow);_,_,c=expected(document())
        self.assertGreater(a['rows'][0]['individual']['halfWidth'],c['rows'][0]['individual']['halfWidth'])
        self.assertLess(b['rows'][0]['individual']['halfWidth'],c['rows'][0]['individual']['halfWidth'])
        self.assertTrue(math.isclose(b['criticalValue'],.5*math.sqrt(2/(1-.25)),rel_tol=1e-12))


class PlanningBoundaryTests(unittest.TestCase):
    def test_precise_faults_before_native(self):
        fault(self,lambda:adaptor.plan(document('prediction-exact-invalid')),'NO_RESIDUAL_VARIANCE','$.prediction')
        fault(self,lambda:adaptor.plan(document('prediction-response-invalid')),'INVALID_TABLE','$.prediction.newdata[0]')
        doc=document();doc['prediction']['newdata']=[[0],[1,2]]
        fault(self,lambda:adaptor.plan(doc),'INVALID_TABLE','$.prediction.newdata[1]')
        doc=document();doc['prediction']['newdata']=[[0],[320]]
        error=fault(self,lambda:adaptor.plan(doc),'UNSUPPORTED_PREDICTION','$.prediction.newdata[1]')
        self.assertGreater(error.observed['leverage'],reference.MAX_LEVERAGE)
        doc=document();doc['prediction']['newdata']=[[1e9]]
        fault(self,lambda:adaptor.plan(doc),'UNSUPPORTED_PREDICTION')
        for value,code in ((None,'MISSING_VALUE'),(float('nan'),'MISSING_VALUE'),('3','UNSUPPORTED_VALUE_TYPE'),(True,'UNSUPPORTED_VALUE_TYPE')):
            doc=document();doc['prediction']['newdata']=[[0],[value]]
            error=fault(self,lambda:adaptor.plan(doc),code,'$.prediction.newdata[1][0]');self.assertEqual(error.observed['variable'],'temperature')
        rank=document();rank['training']=[[1,2.0],[1,2.1],[1,1.9],[1,2.05]]
        fault(self,lambda:adaptor.plan(rank),'RANK_DEFICIENT_DATA')
        ill=document();ill['predictors']=[{'name':'a','unit':'m'},{'name':'b','unit':'m'}]
        ill['training']=[[x,x+d,10+x+e] for x,d,e in [(1,0,.1),(2,1e-5,-.1),(3,-1e-5,.1),(4,2e-5,-.1),(5,0,.1),(6,-2e-5,-.1)]];ill['prediction']['newdata']=[[1,1]]
        fault(self,lambda:adaptor.plan(ill),'ILL_CONDITIONED_DATA')

    def test_schema_rejects_bad_request_shapes(self):
        for change in (lambda p:p.pop('interval'),lambda p:p.pop('newdata'),lambda p:p.update(interval='coefficient'),lambda p:p.update(level=.4999),
                       lambda p:p.update(level=.9991),lambda p:p.update(level='95'),lambda p:p.update(newdata=[]),lambda p:p.update(newdata=[[1]]*65),
                       lambda p:p.update(newdata=[[]]),lambda p:p.update(extra=1),lambda p:p.update(newdata=[[2e9]])):
            doc=document();change(doc['prediction'])
            with self.subTest(doc['prediction']),self.assertRaises(SchemaxisError):adaptor.plan(doc)
        for level in (.5,.999):
            doc=document();doc['prediction']['level']=level;self.assertEqual(adaptor.plan(doc)['prediction']['level'],level)
        doc=document();doc['prediction'].pop('level');self.assertEqual(adaptor.plan(doc)['prediction']['level'],.95)

    def test_legacy_paths_are_unchanged(self):
        from schemaxis.adaptors.r.worker import WORKER
        for name in ('regression','inference','regression-variant'):
            plain=adaptor.plan(document(name));self.assertNotIn('prediction',plain)
            self.assertEqual(len(adaptor.commands('/opt/Rscript',Path('/x'),plain)['fit']),9)
            self.assertFalse([n for n in adaptor.evidence_names(plain) if 'prediction' in n])
            self.assertFalse([n for n,_ in adaptor.publications(plain) if 'prediction' in n])
        self.assertEqual([n for n,_ in adaptor.publications(adaptor.plan(document('inference')))],
            ['coefficients.csv','training.csv','heldout.csv','regression-summary.json','inference.csv'])
        both=document('inference');both['prediction']=document()['prediction']
        self.assertEqual([n for n,_ in adaptor.publications(adaptor.plan(both))][-2:],['inference.csv','prediction.csv'])
        self.assertEqual([n for n,_ in adaptor.publications(adaptor.plan(document()))],['coefficients.csv','training.csv','regression-summary.json','prediction.csv'])
        command=adaptor.commands('/opt/Rscript',Path('/x'),adaptor.plan(document()))['fit'];self.assertEqual((command[-2],command[-1]),('none','0.95'))
        for native in ('stats::predict.lm(model,newdata=newdata,se.fit=TRUE,interval="confidence"','interval="prediction"','prediction-input.csv'):self.assertIn(native,WORKER)

    def test_coefficient_inference_is_distinct_from_prediction_interval(self):
        both=document();both['inference']={'level':.8};prepared=adaptor.plan(both)
        self.assertEqual((prepared['inference']['level'],prepared['prediction']['level']),(.8,.95))
        inferred=reference.inference(prepared,reference.decompose(prepared['training'],True))
        self.assertTrue(math.isclose(inferred['criticalValue'],reference.t_quantile(.8,2),rel_tol=1e-12))
        self.assertNotEqual(inferred['criticalValue'],expected(document())[2]['criticalValue'])

    def test_swapped_wrong_zero_and_reordered_native_values_do_not_pass_floors(self):
        prepared,independent,truth=expected(document());tolerance=reference.response_tolerance(prepared['training'],prepared['scaledInfinityCondition'])
        def native(result):
            return {**{k:result[k] for k in ('level','residualDF','criticalValue','sigma')},'individualSigma':result['sigma'],
                'rows':[{'sample':i,'fit':r['fit'],'seFit':r['confidence']['standardError'],'confidenceLower':r['confidence']['lower'],'confidenceUpper':r['confidence']['upper'],
                    'individualLower':r['individual']['lower'],'individualUpper':r['individual']['upper']} for i,r in enumerate(result['rows'])]}
        self.assertIsNone(reference.compare_prediction(native(truth),truth,tolerance))
        def mutate(change):
            item=native(truth);change(item);return reference.compare_prediction(item,truth,tolerance)
        def swap(item):
            for row in item['rows']:
                row['confidenceLower'],row['individualLower']=row['individualLower'],row['confidenceLower']
                row['confidenceUpper'],row['individualUpper']=row['individualUpper'],row['confidenceUpper']
        self.assertEqual(mutate(swap),'confidenceLower[0]')
        self.assertEqual(mutate(lambda i:i['rows'].reverse()),'sample[0]')
        self.assertEqual(mutate(lambda i:i['rows'][1].update(sample=2)),'sample[1]')
        self.assertEqual(mutate(lambda i:i['rows'][0].update(fit=i['rows'][0]['fit']+1e-6)),'fit[0]')
        for column in ('confidenceLower','confidenceUpper','individualLower','individualUpper'):
            self.assertEqual(mutate(lambda i:i['rows'][1].update({column:i['rows'][1][column]+1e-3*truth['rows'][1]['individual']['halfWidth']})),f'{column}[1]',column)
        self.assertEqual(mutate(lambda i:i['rows'][2].update(seFit=i['rows'][2]['seFit']*(1+1e-4))),'seFit[2]')
        self.assertEqual(mutate(lambda i:i.update(sigma=i['sigma']*(1+1e-4))),'sigma')
        self.assertEqual(mutate(lambda i:i.update(individualSigma=i['individualSigma']*0.99)),'individualSigma')
        self.assertEqual(mutate(lambda i:i.update(level=.9)),'level');self.assertEqual(mutate(lambda i:i.update(residualDF=3)),'residualDF')
        self.assertEqual(mutate(lambda i:i.update(criticalValue=i['criticalValue']*(1+1e-8))),'criticalValue')
        # The largest accepted leverage keeps the two types apart by more than the verification tolerance.
        edge=document();edge['prediction']['newdata']=[[math.sqrt((reference.MAX_LEVERAGE-.25)*10)*.99]]
        prepared,independent,truth=expected(edge);item=native(truth);swap(item)
        self.assertEqual(reference.compare_prediction(item,truth,tolerance),'confidenceLower[0]')


class ResolutionGuardTests(unittest.TestCase):
    """Per-row resolution: accepted rows must expose a swap of interval types under the verifier allowance."""
    def test_reviewer_counterexample_is_refused_before_native(self):
        # 8 predictors, huge response offset, level .5, h near 1e4, sigma just above the NO_RESIDUAL_VARIANCE floor.
        for n in (256,512):
            with self.subTest(n=n):
                prepared,independent,tolerance=resolution_case(8,n,1.05)
                truth=without_guard(prepared,independent);row=truth['rows'][0]
                gap=row['individual']['halfWidth']-row['confidence']['halfWidth'];allowance=reference.fit_tolerance(tolerance,row)
                self.assertLess(gap,allowance+reference.PREDICTION_RELATIVE*row['individual']['halfWidth'])
                self.assertAlmostEqual(row['leverage'],1e4,delta=1);self.assertLessEqual(row['leverage'],reference.MAX_LEVERAGE)
                self.assertIsNone(reference.compare_prediction(swapped_native(truth),truth,tolerance),'without the guard the type swap passes')
                error=fault(self,lambda:reference.prediction_intervals(prepared,independent),'UNSUPPORTED_PREDICTION','$.prediction.newdata[0]',message='swap of interval types')
                self.assertEqual(error.observed['halfWidthGap'],gap);self.assertLess(error.observed['halfWidthGap'],error.observed['requiredHalfWidthGap'])
                self.assertEqual(error.observed['comparisonAllowance'],allowance);self.assertEqual(error.observed['resolutionFactor'],4)
                self.assertIn('not a model-validity test',error.recovery)

    def test_counterexample_document_is_refused_by_plan_with_resolution_scope(self):
        prepared,independent,_=resolution_case(8,256,1.05)
        doc={'version':'schemaxis.r/1','operation':'linearRegression','predictors':[{'name':f'x{j}','unit':'m'} for j in range(8)],'response':{'name':'reading','unit':'V'},
            'training':prepared['training'],'prediction':{'interval':'confidence','level':.5,'newdata':prepared['prediction']['newdata']}}
        error=fault(self,lambda:adaptor.plan(doc),'UNSUPPORTED_PREDICTION','$.prediction.newdata[0]')
        self.assertLess(error.observed['leverage'],reference.MAX_LEVERAGE);self.assertIn('could not be detected',error.message)
        # The same design with a row nearer the training centre is supported and still verified apart.
        doc['prediction']['newdata']=[[0.0]*8]
        self.assertEqual(adaptor.plan(doc)['prediction']['newdata'],[[0.0]*8])

    def test_every_supported_row_distinguishes_swapped_types_under_verifier_allowance(self):
        accepted=refused=0
        # (p, n, ratio, offset, scale, shift, intercept, level, leverage): levels, sigma multiples, df, sizes, scales, shifts, offsets and intercepts vary.
        grid=[(8,256,1.05,9e8,1,0,True,.5,1e4),(8,256,1.05,9e8,1,0,True,.5,1e2),(8,256,3,9e8,1,0,True,.5,1e4),(8,256,50,9e8,1,0,True,.5,1e4),
              (8,64,1.05,9e8,1,0,True,.5,1e4),(8,64,2,3e9,1e3,0,True,.9,1e4),(8,40,1.5,1e6,1e-3,0,True,.999,1e4),(3,40,1.05,1e6,1e-3,50,True,.999,1e4),
              (3,24,1.1,0,1,0,True,.99,1e4),(2,30,1.1,1e9,1,0,False,.5,1e4),(2,12,2,1e5,1e6,0,False,.9,5e3),(1,4,1.05,2e7,1,0,True,.5,1e4),
              (1,8,5,0,1e-6,0,True,.5,1e4),(8,128,1.05,9e8,1,3,True,.5,1e4),(8,128,1.05,9e8,1,10,True,.5,1e4),(5,200,1.2,5e8,10,-2,True,.75,3e3)]
        for p,n,ratio,offset,scale,shift,intercept,level,leverage in grid:
            with self.subTest(p=p,n=n,ratio=ratio,offset=offset,scale=scale,shift=shift,intercept=intercept,level=level,leverage=leverage):
                try:prepared,independent,tolerance=resolution_case(p,n,ratio,offset=offset,scale=scale,shift=shift,intercept=intercept,level=level,leverage=leverage)
                except SchemaxisError as error:self.fail(error.fault.to_dict())
                try:truth=reference.prediction_intervals(prepared,independent)
                except SchemaxisError as error:
                    self.assertEqual(error.fault.code,'UNSUPPORTED_PREDICTION',error.fault.to_dict());self.assertEqual(error.fault.location,'$.prediction.newdata[0]')
                    self.assertLessEqual(error.fault.observed['halfWidthGap'],error.fault.observed['requiredHalfWidthGap']);refused+=1;continue
                accepted+=1;row=truth['rows'][0];gap=row['individual']['halfWidth']-row['confidence']['halfWidth']
                self.assertGreater(gap,reference.RESOLUTION_FACTOR*(reference.fit_tolerance(tolerance,row)+reference.PREDICTION_RELATIVE*row['individual']['halfWidth']))
                self.assertIsNone(reference.compare_prediction(swapped_native(truth,'confidence','individual'),truth,tolerance))
                for kinds in (('individual','confidence'),('confidence','confidence'),('individual','individual')):
                    self.assertIsNotNone(reference.compare_prediction(swapped_native(truth,*kinds),truth,tolerance),kinds)
        self.assertGreater(accepted,5);self.assertGreater(refused,2)

    def test_leverage_boundary_between_accepted_and_refused_rows(self):
        # Same data, increasing leverage only: find the exact boundary and check both sides with the real verifier.
        def outcome(leverage):
            prepared,independent,tolerance=resolution_case(8,256,1.05,leverage=leverage)
            try:truth=reference.prediction_intervals(prepared,independent)
            except SchemaxisError as error:return None,tolerance,error.fault
            return truth,tolerance,None
        low,high=1.0,1e4;self.assertIsNotNone(outcome(low)[0]);self.assertIsNone(outcome(high)[0])
        for _ in range(18):
            middle=math.sqrt(low*high)
            if outcome(middle)[0] is None:high=middle
            else:low=middle
        self.assertLess(high/low,1.01)
        truth,tolerance,_=outcome(low*.99);_,_,refusal=outcome(high*1.01)
        self.assertIsNotNone(truth);self.assertEqual(refusal.code,'UNSUPPORTED_PREDICTION')
        self.assertIsNotNone(reference.compare_prediction(swapped_native(truth),truth,tolerance))
        self.assertLess(refusal.observed['leverage'],reference.MAX_LEVERAGE)
        # More residual scatter at the same leverage restores resolution: the guard depends on sigma, not only on h.
        prepared,independent,tolerance=resolution_case(8,256,50,leverage=high*1.01)
        truth=reference.prediction_intervals(prepared,independent)
        self.assertIsNotNone(reference.compare_prediction(swapped_native(truth),truth,tolerance))

    def test_guard_threshold_is_the_stated_multiple_of_allowance_plus_relative_component(self):
        item={'leverage':1.0,'scaledDesign':[1.0,-2.0,3.0],'confidence':{'halfWidth':100.0},'individual':{'halfWidth':100.0}}
        tolerance=1e-3;allowance=tolerance*(1+6);half=100.0;factor=reference.RESOLUTION_FACTOR;relative=reference.PREDICTION_RELATIVE
        # The relative component uses the individual half width itself: gap = f*(allowance + r*(half+gap)).
        need=factor*(allowance+relative*half)/(1-factor*relative)
        item['individual']['halfWidth']=half+need*(1+1e-9);reference.resolution_guard(item,tolerance,'$.x')
        item['individual']['halfWidth']=half+need*(1-1e-9)
        error=fault(self,lambda:reference.resolution_guard(item,tolerance,'$.prediction.newdata[3]'),'UNSUPPORTED_PREDICTION','$.prediction.newdata[3]')
        self.assertTrue(math.isclose(error.observed['comparisonAllowance'],allowance));self.assertTrue(math.isclose(error.observed['requiredHalfWidthGap'],need,rel_tol=1e-6))
        self.assertGreaterEqual(reference.RESOLUTION_FACTOR,1)

    def test_eight_predictor_literal_oracle_is_not_refused_and_matches_exact_math(self):
        doc=hadamard_document();prepared,independent,truth=expected(doc)
        self.assertEqual((prepared['rank'],prepared['residualDF']),(9,7));self.assertTrue(math.isclose(truth['sigma'],HADAMARD_SIGMA,rel_tol=1e-12))
        self.assertTrue(math.isclose(truth['criticalValue'],T_975_DF7,rel_tol=1e-12))
        for row,x in zip(truth['rows'],doc['prediction']['newdata']):
            h=(1+sum(v*v for v in x))/16;fit=10+sum(.5*j*v for j,v in enumerate(x,1))
            self.assertTrue(math.isclose(row['leverage'],h,rel_tol=1e-12));self.assertTrue(math.isclose(row['fit'],fit,rel_tol=1e-12,abs_tol=1e-12))
            self.assertTrue(math.isclose(row['confidence']['halfWidth'],T_975_DF7*HADAMARD_SIGMA*math.sqrt(h),rel_tol=1e-12))
            self.assertTrue(math.isclose(row['individual']['halfWidth'],T_975_DF7*HADAMARD_SIGMA*math.sqrt(1+h),rel_tol=1e-12))
            self.assertTrue(math.isclose(row['leverage'],float(exact_leverage(prepared['training'],True,x)),rel_tol=1e-9))
        self.assertEqual([r['outsideTrainingRange'] for r in truth['rows']],[[],[],[f'x{j}' for j in range(1,9)]])
        self.assertEqual(len(adaptor.prediction_table(prepared,{'rows':[{'sample':0,'inputs':[{'value':0}]*8,'prediction':0,'lower':0,'upper':0,'halfWidth':0}]})['columns']),13)


class PredictionEvidenceTests(unittest.TestCase):
    """Host-only evidence: synthetic native stage output generated from the independent model."""
    def fake_run(self,root,doc=None):
        doc=doc or document();prepared=adaptor.plan(doc);output=root/'run'
        independent=reference.decompose(prepared['training'],prepared['intercept']);truth=reference.prediction_intervals(prepared,independent)
        def execute(command,directory,stage,timeout,environment=None):
            atomic_json(directory/(stage+'-submission.json'),{'exitCode':0,'nativeCommand':command,'interpreter':{'executable':sys.executable}})
            atomic_json(directory/(stage+'-inputs.json'),{str(path):file_digest(path) for path in adaptor.stage_inputs(directory,prepared,stage)})
            for suffix in ('.stdout','.stderr'):(directory/(stage+suffix)).write_text('')
            if stage=='fit':(directory/'model.rds').write_bytes(b'synthetic RDS fixture: native-only decode')
            (directory/(stage+'-runtime.txt')).write_text('R version 4.6.1 (2026-06-24)\n')
            write_csv(directory/(stage+'-coefficients.csv'),{'columns':['coefficientIndex','scaledCoefficient'],'rows':[[i,v] for i,v in enumerate(independent['scaledCoefficients'])]})
            write_csv(directory/(stage+'-metadata.csv'),{'columns':['rank','residualDF'],'rows':[[prepared['rank'],prepared['residualDF']]]})
            for scope in ('training','heldout'):
                if scope not in prepared:continue
                rows=[]
                for i,row in enumerate(prepared[scope]):
                    predicted=reference.predicted(prepared,row,independent['coefficients']);residual=row[-1]-predicted
                    rows.append([i,row[-1],predicted,residual]+([predicted,residual] if scope=='training' else []))
                write_csv(directory/(stage+'-'+scope+'.csv'),{'columns':['sample','observed','prediction','residual']+(['fitted','fitResidual'] if scope=='training' else []),'rows':rows})
            write_csv(directory/(stage+'-prediction.csv'),{'columns':adaptor.PREDICTION_COLUMNS,'rows':[[r['sample'],r['fit'],r['confidence']['standardError'],
                r['confidence']['lower'],r['confidence']['upper'],r['individual']['lower'],r['individual']['upper']] for r in truth['rows']]})
            write_csv(directory/(stage+'-prediction-statistics.csv'),{'columns':adaptor.PREDICTION_STATISTICS,
                'rows':[[truth['level'],truth['residualDF'],truth['criticalValue'],truth['sigma'],truth['sigma'],truth['residualDF'],truth['residualDF']]]})
        with patch.object(adaptor,'execute',side_effect=execute),patch.object(adaptor.os,'access',return_value=True):
            adaptor.run(doc,output,executable=str(Path(sys.executable).resolve()))
        return output

    def refresh(self,output):
        prepared=adaptor.plan(json.loads((output/'authored.json').read_text()))
        receipt=json.loads((output/'verification.json').read_text());receipt['artifacts']=adaptor.manifest(output,prepared)
        receipt['evidence']={name:file_digest(output/name) for name in adaptor.evidence_names(prepared)}
        atomic_json(output/'verification.json',receipt);finalise(output)

    def edit(self,path,row,column,change):
        lines=path.read_text().splitlines();header=lines[0].split(',');cells=lines[row].split(',');index=header.index(column)
        cells[index]=change(cells[index]);lines[row]=','.join(cells);path.write_text('\n'.join(lines)+'\n')

    def test_published_tables_summary_and_artifact_order(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));result=adaptor.verify(output)
            self.assertEqual(result['prediction'],{'interval':'individual','level':.95,'rows':3})
            names=[Path(a['file']).name for a in json.loads((output/'verification.json').read_text())['artifacts']]
            self.assertEqual(names,['coefficients.csv','training.csv','regression-summary.json','prediction.csv'])
            lines=(output/'prediction.csv').read_text().splitlines()
            self.assertEqual(lines[0],'sample,x1,prediction,lower,upper,halfWidth');self.assertEqual(len(lines),4)
            summary=json.loads((output/'regression-summary.json').read_text())['prediction']
            self.assertEqual(summary['interval'],'individual');self.assertEqual(summary['verifiedIntervalTypes'],['confidence','individual'])
            self.assertEqual(summary['residualStandardError']['units'],'V');self.assertEqual(summary['rows'][2]['inputs'],[{'name':'temperature','unit':'degC','value':3}])
            self.assertTrue(math.isclose(summary['rows'][2]['leverage'],1.15,rel_tol=1e-12));self.assertEqual(summary['rows'][2]['outsideTrainingRange'],['temperature'])
            self.assertEqual(summary['residualDF'],2);self.assertIn('not a calibration certificate',summary['limits']);self.assertIn('extrapolation observed',summary['limits'])
            self.assertTrue(any('independent' in a for a in summary['assumptions']))
            confidence=document('prediction-variant');output=self.fake_run(Path(temp)/'c',confidence);adaptor.verify(output)
            wide=json.loads((output/'regression-summary.json').read_text())['prediction']
            self.assertEqual(wide['interval'],'confidence');self.assertIn('Mean confidence interval',wide['meaning'])
            self.assertEqual(wide['rows'][1]['inputs'][0]['value'],.5)

    def test_hash_refreshed_native_and_published_forgeries_fail_with_precise_messages(self):
        def both(name,column,change,row=1):
            def forge(output):
                for stage in ('fit','reopen'):self.edit(output/(stage+'-'+name+'.csv'),row,column,change)
            return forge
        shift=lambda v:repr(float(v)+1e-3);scale=lambda v:repr(float(v)*1.01)
        forgeries=(('fit',both('prediction','fit',shift),'prediction fit[0]','reopen-prediction'),
            ('lower',both('prediction','individualLower',shift),'prediction individualLower[0]','reopen-prediction'),
            ('upper',both('prediction','confidenceUpper',shift),'prediction confidenceUpper[0]','reopen-prediction'),
            ('seFit',both('prediction','seFit',scale),'prediction seFit[0]','reopen-prediction'),
            ('sample',both('prediction','sample',lambda v:'1'),'prediction sample[0]','reopen-prediction'),
            ('sigma',both('prediction-statistics','sigma',scale),'prediction sigma','reopen-prediction'),
            ('level',both('prediction-statistics','level',lambda v:'0.9'),'prediction level','reopen-prediction'),
            ('df',both('prediction-statistics','residualDF',lambda v:'3'),'prediction residualDF','reopen-prediction'),
            ('critical',both('prediction-statistics','criticalValue',scale),'prediction criticalValue','reopen-prediction'),
            ('native df',both('prediction-statistics','individualDF',lambda v:'3'),'native prediction residual degrees of freedom differ','reopen-prediction'))
        for name,forge,message,location in forgeries:
            with self.subTest(forge=name),tempfile.TemporaryDirectory() as temp:
                output=self.fake_run(Path(temp));forge(output);self.refresh(output)
                error=fault(self,lambda:adaptor.verify(output),'VERIFICATION_FAILED',message=message)
                self.assertIn(error.location,('fit-prediction','reopen-prediction'))
        def swapped(output):
            for stage in ('fit','reopen'):
                path=output/(stage+'-prediction.csv');lines=path.read_text().splitlines();rows=[l.split(',') for l in lines[1:]]
                for r in rows:r[3],r[5]=r[5],r[3];r[4],r[6]=r[6],r[4]
                path.write_text('\n'.join([lines[0]]+[','.join(r) for r in rows])+'\n')
        def reordered(output):
            for stage in ('fit','reopen'):
                path=output/(stage+'-prediction.csv');lines=path.read_text().splitlines();path.write_text('\n'.join([lines[0],*reversed(lines[1:])])+'\n')
        def reopen_only(output):self.edit(output/'reopen-prediction.csv',2,'seFit',lambda v:repr(float(v)*(1+1e-6)))
        def input_rows(output):
            self.edit(output/'prediction-input.csv',1,'x1',lambda v:repr(float(v)+.5))
        def published(output):self.edit(output/'prediction.csv',2,'upper',lambda v:repr(float(v)+1e-3))
        def header(output):
            path=output/'prediction.csv';path.write_text(path.read_text().replace('halfWidth','spread'))
        def summary_leverage(output):
            summary=json.loads((output/'regression-summary.json').read_text());summary['prediction']['rows'][0]['leverage']=.3
            atomic_json(output/'regression-summary.json',summary)
        def summary_interval(output):
            summary=json.loads((output/'regression-summary.json').read_text());summary['prediction']['interval']='confidence'
            atomic_json(output/'regression-summary.json',summary)
        def authored_level(output):
            doc=json.loads((output/'authored.json').read_text());doc['prediction']['level']=.9;atomic_json(output/'authored.json',doc)
        for forge,message in ((swapped,'prediction confidenceLower[0]'),(reordered,'prediction sample[0]'),(reopen_only,'fresh native model reopen prediction differs'),
                              (input_rows,'captured input differs from declared new predictor rows'),(published,'published prediction table differs'),(header,'published prediction table differs'),
                              (summary_leverage,'summary differs'),(summary_interval,'summary differs'),(authored_level,'effective plan differs')):
            with self.subTest(forge=forge.__name__),tempfile.TemporaryDirectory() as temp:
                output=self.fake_run(Path(temp));forge(output);self.refresh(output)
                fault(self,lambda:adaptor.verify(output),'VERIFICATION_FAILED',message=message)

    def test_unrefreshed_integrity_controls_and_missing_evidence(self):
        for name in ('prediction.csv','fit-prediction.csv','reopen-prediction-statistics.csv','prediction-input.csv'):
            with self.subTest(name),tempfile.TemporaryDirectory() as temp:
                output=self.fake_run(Path(temp));path=output/name;path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
                with self.assertRaises(SchemaxisError) as caught:adaptor.verify(output)
                self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));(output/'reopen-prediction.csv').unlink()
            fault(self,lambda:adaptor.verify(output),'VERIFICATION_FAILED')
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));(output/'prediction.csv').unlink()
            fault(self,lambda:adaptor.verify(output),'VERIFICATION_FAILED')

    def test_prediction_with_inference_and_heldout_keeps_all_paths(self):
        doc=document('inference');doc['prediction']=document()['prediction']
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp),doc) if False else None
        prepared=adaptor.plan(doc)
        self.assertEqual([n for n,_ in adaptor.publications(prepared)],['coefficients.csv','training.csv','heldout.csv','regression-summary.json','inference.csv','prediction.csv'])
        self.assertEqual(adaptor.commands('/opt/Rscript',Path('/x'),prepared)['fit'][-2:],['0.95','0.95'])
        self.assertIn('reopen-prediction-statistics.csv',adaptor.evidence_names(prepared))
        self.assertEqual(adaptor.stage_inputs(Path('/x'),prepared,'reopen')[-2:],[Path('/x/prediction-input.csv'),Path('/x/model.rds')])


@unittest.skipUnless(RSCRIPT and os.access(RSCRIPT,os.X_OK),'SCHEMAXIS_R must name the qualified Rscript')
class NativePredictionTests(unittest.TestCase):
    def run_native(self,root,doc,timeout=300):
        output=root/'run';adaptor.run(doc,output,executable=RSCRIPT,timeout=timeout);return output

    def test_native_predict_lm_matches_independent_closed_form_for_both_types(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.run_native(Path(temp),document());result=adaptor.verify(output)
            self.assertEqual(result['prediction']['rows'],3);self.assertTrue(result['runtime'].startswith('R version 4.6'))
            sigma=math.sqrt(.05);t=.95*math.sqrt(2/(1-.95**2))
            from schemaxis.tabular import read_csv
            native=read_csv(output/'reopen-prediction.csv')
            for row,x in zip(native['rows'],(0,1,3)):
                h=.25+x*x/10
                self.assertTrue(math.isclose(row[2],sigma*math.sqrt(h),rel_tol=1e-12))
                self.assertTrue(math.isclose(row[4]-row[3],2*t*sigma*math.sqrt(h),rel_tol=1e-12))
                self.assertTrue(math.isclose(row[6]-row[5],2*t*sigma*math.sqrt(1+h),rel_tol=1e-12))
            self.assertEqual([p.name for p in sorted(output.glob('*prediction*')) if not p.name.endswith('.metadata.json')],['fit-prediction-statistics.csv','fit-prediction.csv','prediction-input.csv','prediction.csv','reopen-prediction-statistics.csv','reopen-prediction.csv'])

    def test_native_changed_level_type_newdata_and_response_scale(self):
        base=None
        for change in (lambda d:None,lambda d:d['prediction'].update(level=.9),lambda d:d['prediction'].update(interval='confidence'),lambda d:d['prediction'].update(newdata=[[-1.5],[.5]]),
                       lambda d:d.update(training=[[x,y*1000] for x,y in d['training']])):
            doc=document();change(doc)
            with self.subTest(),tempfile.TemporaryDirectory() as temp:
                output=self.run_native(Path(temp),doc);adaptor.verify(output)
                half=json.loads((output/'regression-summary.json').read_text())['prediction']['rows'][0]['halfWidth']
                if base is None:base=half
                else:self.assertNotEqual(half,base)

    def test_native_eight_predictor_prediction_matches_independent_literal_oracle(self):
        doc=hadamard_document(level=.95,interval='confidence')
        with tempfile.TemporaryDirectory() as temp:
            output=self.run_native(Path(temp),doc);result=adaptor.verify(output);self.assertEqual(result['prediction']['rows'],3)
            from schemaxis.tabular import read_csv
            native=read_csv(output/'reopen-prediction.csv')
            for row,x in zip(native['rows'],doc['prediction']['newdata']):
                h=(1+sum(v*v for v in x))/16
                self.assertTrue(math.isclose(row[2],HADAMARD_SIGMA*math.sqrt(h),rel_tol=1e-10))
                self.assertTrue(math.isclose(row[4]-row[3],2*T_975_DF7*HADAMARD_SIGMA*math.sqrt(h),rel_tol=1e-10))
                self.assertTrue(math.isclose(row[6]-row[5],2*T_975_DF7*HADAMARD_SIGMA*math.sqrt(1+h),rel_tol=1e-10))
            self.assertEqual(len(read_csv(output/'prediction.csv')['columns']),13)

    def test_native_timeout_exercises_prediction_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            fault(self,lambda:adaptor.run(document(),Path(temp)/'run',executable=RSCRIPT,timeout=1e-6),'RUNNER_TIMED_OUT')


if __name__=='__main__':unittest.main()
