#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Bounded R models, native reopen, finite requirements, coefficient inference and Calc handoff gates."""
import argparse
import copy
from fractions import Fraction
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from schemaxis import workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors.r import adaptor
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise
from schemaxis.tabular import close,read_csv

ROOT=Path(__file__).resolve().parents[1]


def example(name='regression'):
    return json.loads((ROOT/f'examples/schemaxis/r-{name}.json').read_text())


def fault(callback,code):
    try:callback()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('expected '+code)


def exact_ols(rows,intercept):
    """Exact rational normal equations; independent of the adaptor's QR and distributions."""
    design=[[Fraction(1)]*intercept+[Fraction(v) for v in row[:-1]] for row in rows];y=[Fraction(row[-1]) for row in rows]
    p=len(design[0]);augmented=[[sum(r[i]*r[j] for r in design) for j in range(p)]+[Fraction(int(i==k)) for k in range(p)] for i in range(p)]
    for c in range(p):
        pivot=next(r for r in range(c,p) if augmented[r][c]!=0);augmented[c],augmented[pivot]=augmented[pivot],augmented[c]
        augmented[c]=[v/augmented[c][c] for v in augmented[c]]
        for r in range(p):
            if r!=c:augmented[r]=[a-augmented[r][c]*b for a,b in zip(augmented[r],augmented[c])]
    inverse=[row[p:] for row in augmented];xty=[sum(r[j]*v for r,v in zip(design,y)) for j in range(p)]
    beta=[sum(inverse[i][j]*xty[j] for j in range(p)) for i in range(p)]
    fitted=[sum(b*v for b,v in zip(beta,r)) for r in design];rss=sum((a-b)**2 for a,b in zip(y,fitted));df=len(rows)-p
    centre=sum(fitted)/len(fitted) if intercept else 0;mss=sum((f-centre)**2 for f in fitted)
    return {'beta':[float(b) for b in beta],'se':[math.sqrt(inverse[j][j]*rss/df) for j in range(p)],'df':df,
            'sigma':math.sqrt(rss/df),'rSquared':float(mss/(mss+rss)),'f':float(mss/(p-intercept)/(rss/df))}


def check_exact(summary,rows,intercept):
    known=exact_ols(rows,intercept);inference=summary['inference']
    assert inference['residualDF']==known['df']
    for item,beta,se in zip(inference['coefficients'],known['beta'],known['se']):
        assert math.isclose(item['estimate'],beta,rel_tol=1e-9,abs_tol=1e-12),(item,beta)
        assert math.isclose(item['standardError'],se,rel_tol=1e-9),(item,se)
        assert math.isclose(item['tStatistic'],beta/se,rel_tol=1e-9,abs_tol=1e-9)
        assert math.isclose((item['upper']-item['lower'])/2,inference['criticalValue']*se,rel_tol=1e-9)
    assert math.isclose(inference['residualStandardError']['value'],known['sigma'],rel_tol=1e-9)
    assert math.isclose(1-inference['rSquared'],1-known['rSquared'],rel_tol=1e-8)
    assert math.isclose(inference['fTest']['statistic'],known['f'],rel_tol=1e-8)
    return {'residualDF':known['df'],'coefficients':len(known['beta']),'maximumStandardErrorRelativeDifference':
        max(abs(i['standardError']-se)/se for i,se in zip(inference['coefficients'],known['se']))}


def workbook_observations(directory):
    """Read native summary caches without importing Calc's parser or assessment."""
    addresses=('C3','C4','C5','E5','F5')
    with ZipFile(directory/'analysis.xlsx') as archive:
        tree=ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    xlsx={cell.get('r'):float(cell.findtext('s:v',namespaces=ns))
          for cell in tree.findall('.//s:c',ns) if cell.get('r') in addresses}
    with ZipFile(directory/'analysis.ods') as archive:
        tree=ET.fromstring(archive.read('content.xml'))
    ns={'t':'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
        'o':'urn:oasis:names:tc:opendocument:xmlns:office:1.0'}
    summary=next(sheet for sheet in tree.findall('.//t:table',ns)
                 if sheet.get('{'+ns['t']+'}name')=='Summary')
    rows=summary.findall('t:table-row',ns)
    ods={address:float(rows[int(address[1:])-1].findall('t:table-cell',ns)[ord(address[0])-ord('A')].get('{'+ns['o']+'}value'))
         for address in addresses}
    expected={'C3':25.9,'C4':26,'C5':-.1,'E5':-.2,'F5':.1}
    for cells in (xlsx,ods):
        assert set(cells)==set(expected)
        for address,value in expected.items():assert math.isclose(cells[address],value,rel_tol=1e-12,abs_tol=1e-12),(address,cells)
        assert abs(cells['C3']-cells['C4']-cells['C5'])<=1e-10
    return {'xlsx':xlsx,'ods':ods}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True);parser.add_argument('--calc',required=True)
    parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--timeout',type=float,default=120)
    args=parser.parse_args();root=args.output_directory.absolute();root.mkdir(parents=True,exist_ok=False)
    report={'version':'schemaxis.r.qualification/1','verified':False,'sourceDigest':source_digest('r'),
        'sourceDigests':{name:source_digest(name) for name in ('r','calc')},
        'recipeSHA256':file_digest(__file__),'workflowSHA256':file_digest(ROOT/'examples/schemaxis/r-to-calc.json'),
        'scope':'Exact recorded Rscript runtime; numeric additive OLS,1–8 predictors, declared training/held-out rows, fixed formula symbols, independent QR/condition checks, RDS fresh reopen, optional classical coefficient inference (summary.lm/confint/pf) checked against exact rational normal equations and closed-form t quantiles, and Calc numeric handoff. Inference holds only under independent constant-variance normal errors; no prediction intervals or future-generalisation guarantee.',
        'accepted':{},'unmet':{},'negative':{},'workflows':{},'inference':{}}
    def refresh(directory):
        prepared=adaptor.plan(json.loads((directory/'authored.json').read_text()))
        receipt=json.loads((directory/'verification.json').read_text());receipt['artifacts']=adaptor.manifest(directory,prepared)
        receipt['evidence']={name:adaptor.digest(directory,name) for name in adaptor.evidence_names(prepared)}
        atomic_json(directory/'verification.json',receipt);finalise(directory)
    try:
        for name in ('regression','regression-variant','no-intercept','eight-predictors'):
            directory=root/name;adaptor.run(example(name),directory,executable=args.executable,timeout=args.timeout)
            result=adaptor.verify(directory);summary=json.loads((directory/'regression-summary.json').read_text())
            expected=[2] if name=='no-intercept' else [10,3] if name=='regression-variant' else [10,*range(1,9)] if name=='eight-predictors' else [10,2]
            assert close([c['estimate'] for c in summary['coefficients']],expected,rel=1e-10,absolute=1e-10)
            report['accepted'][name]=result
        # Nontrivial units/scales preserve the same model after coefficient unscaling.
        scaled=example();scaled['training']=[[x*1e8,y] for x,y in scaled['training']]
        scaled['heldout']=[[x*1e8,y] for x,y in scaled['heldout']]
        directory=root/'scaled-predictor';adaptor.run(scaled,directory,executable=args.executable,timeout=args.timeout)
        summary=json.loads((directory/'regression-summary.json').read_text());assert close(summary['coefficients'][1]['estimate'],2e-8,rel=1e-10,absolute=1e-16)
        report['accepted']['scaled-predictor']=adaptor.verify(directory)
        tiny=example();tiny.pop('requirements');tiny['training']=[[x,y*1e-100] for x,y in tiny['training']];tiny['heldout']=[[x,y*1e-100] for x,y in tiny['heldout']]
        directory=root/'tiny-response';adaptor.run(tiny,directory,executable=args.executable,timeout=args.timeout)
        summary=json.loads((directory/'regression-summary.json').read_text())
        assert close([c['estimate'] for c in summary['coefficients']],[1e-99,2e-100],rel=1e-10,absolute=1e-110)
        assert summary['verificationTolerance']['absoluteResponseUnits']<1e-110
        report['accepted']['tiny-response']=adaptor.verify(directory)
        for name,modify in (('tight-training',lambda d:d['requirements'][0].update(maximum=.01)),
            ('changed-heldout',lambda d:d['heldout'][1].__setitem__(-1,20)),
            ('low-prediction',lambda d:d['requirements'][2].update(minimum=11,maximum=12))):
            document=example();modify(document);directory=root/name
            failure=fault(lambda:adaptor.run(document,directory,executable=args.executable,timeout=args.timeout),'FIT_REQUIREMENT_NOT_MET')
            replay=fault(lambda:adaptor.verify(directory,require_result=False),'FIT_REQUIREMENT_NOT_MET')
            assert json.loads((directory/'result.json').read_text())['verified'] is False
            report['unmet'][name]={'fault':failure['code'],'replay':replay['code'],'assessment':failure['observed']['assessment']}
        # Coefficient inference: closed forms, exact normal equations, levels, scales and misses.
        s802=math.sqrt(802);closed={'se':math.sqrt(.005),'t':20*math.sqrt(2),'p':2/(s802*(s802+20*math.sqrt(2)))}
        directory=root/'inference';adaptor.run(example('inference'),directory,executable=args.executable,timeout=args.timeout)
        result=adaptor.verify(directory);summary=json.loads((directory/'regression-summary.json').read_text());slope=summary['inference']['coefficients'][1]
        assert math.isclose(slope['standardError'],closed['se'],rel_tol=1e-12) and math.isclose(slope['tStatistic'],closed['t'],rel_tol=1e-12)
        assert math.isclose(slope['pValue'],closed['p'],rel_tol=1e-11) and math.isclose(summary['inference']['fTest']['pValue'],closed['p'],rel_tol=1e-11)
        assert math.isclose(summary['inference']['criticalValue'],.95*math.sqrt(2/(1-.95**2)),rel_tol=1e-12)
        assert summary['inference']['rSquaredBasis'].startswith('centred') and slope['units']=='V/degC'
        names=[Path(a['file']).name for a in json.loads((directory/'verification.json').read_text())['artifacts']]
        assert names==['coefficients.csv','training.csv','heldout.csv','regression-summary.json','inference.csv'],names
        report['inference']['closed-form-calibration']={'result':result,'exact':check_exact(summary,example('inference')['training'],True),'artifacts':names}
        variant=example('inference-variant');directory=root/'inference-variant'
        adaptor.run(variant,directory,executable=args.executable,timeout=args.timeout);result=adaptor.verify(directory)
        summary=json.loads((directory/'regression-summary.json').read_text())
        assert math.isclose(summary['inference']['coefficients'][1]['standardError'],math.sqrt(.08/6/168),rel_tol=1e-12)
        assert math.isclose(summary['inference']['fTest']['statistic'],113400,rel_tol=1e-11)
        report['inference']['eight-point-ninety-percent']={'result':result,'exact':check_exact(summary,variant['training'],True)}
        for level in (.5,.99,.999):
            document=example('inference');document['requirements']=document['requirements'][:2];document['inference']['level']=level
            directory=root/f'inference-level-{level}';adaptor.run(document,directory,executable=args.executable,timeout=args.timeout);adaptor.verify(directory)
            native=read_csv(directory/'reopen-statistics.csv')['rows'][0];summary=json.loads((directory/'regression-summary.json').read_text())
            assert native[0]==level and math.isclose(native[2],level*math.sqrt(2/(1-level*level)),rel_tol=1e-12),native
            report['inference'][f'level-{level}']={'nativeLevelReadback':native[0],'criticalValue':native[2],'slopeInterval':[summary['inference']['coefficients'][1][k] for k in ('lower','upper')]}
        origin=example('inference');origin.pop('requirements');origin.pop('heldout');origin['intercept']=False
        origin['training']=[[1,2.1],[2,3.9],[3,5.9],[4,8.1]];directory=root/'inference-through-origin'
        adaptor.run(origin,directory,executable=args.executable,timeout=args.timeout);adaptor.verify(directory)
        summary=json.loads((directory/'regression-summary.json').read_text())
        assert summary['inference']['rSquaredBasis'].startswith('uncentred') and summary['inference']['fTest']['numeratorDF']==1
        assert math.isclose(summary['inference']['rSquared'],120/120.04,rel_tol=1e-12) and math.isclose(summary['inference']['fTest']['statistic'],9000,rel_tol=1e-11)
        report['inference']['through-origin-uncentred']=check_exact(summary,origin['training'],False)
        correlated=example('inference');correlated.pop('requirements');correlated.pop('heldout')
        correlated['predictors']=[{'name':'a','unit':'K'},{'name':'b','unit':'Pa'},{'name':'c','unit':'s'}];state=20261016;rows=[]
        for _ in range(12):
            values=[]
            for _ in range(4):state=(1103515245*state+12345)%2**31;values.append(round(state/2**31*4-2,3))
            a,b,c,noise=values;b=round(.6*a+.4*b,3);rows.append([a,b*1e3,c*1e-3,round(5+2*a-.003*b*1e3+400*c*1e-3+.1*noise,6)])
        correlated['training']=rows;directory=root/'inference-correlated-scaled'
        adaptor.run(correlated,directory,executable=args.executable,timeout=args.timeout);adaptor.verify(directory)
        summary=json.loads((directory/'regression-summary.json').read_text())
        report['inference']['correlated-three-predictor-scaled']={**check_exact(summary,rows,True),'scaledInfinityCondition':summary['scaledInfinityCondition']}
        scaled=example('inference');scaled['training']=[[x*1e8,y] for x,y in scaled['training']];scaled['heldout']=[[x*1e8,y] for x,y in scaled['heldout']]
        scaled['requirements'][2].update(minimum=1.5e-8,maximum=2.5e-8);directory=root/'inference-scaled-predictor'
        adaptor.run(scaled,directory,executable=args.executable,timeout=args.timeout);adaptor.verify(directory)
        slope=json.loads((directory/'regression-summary.json').read_text())['inference']['coefficients'][1]
        assert math.isclose(slope['standardError'],closed['se']*1e-8,rel_tol=1e-10) and math.isclose(slope['tStatistic'],closed['t'],rel_tol=1e-10)
        report['inference']['predictor-scale-1e8']={'standardError':slope['standardError'],'tStatistic':slope['tStatistic']}
        imprecise=example('inference');imprecise['requirements'][2].update(minimum=1.9,maximum=2.1);directory=root/'inference-imprecise-slope'
        failure=fault(lambda:adaptor.run(imprecise,directory,executable=args.executable,timeout=args.timeout),'FIT_REQUIREMENT_NOT_MET')
        replay=fault(lambda:adaptor.verify(directory,require_result=False),'FIT_REQUIREMENT_NOT_MET')
        missed=[item for item in failure['observed']['assessment']['requirements'] if not item['accepted']]
        assert [item['name'] for item in missed]==['slope_interval'] and math.isclose(missed[0]['observed']['estimate'],2,rel_tol=1e-12)
        report['unmet']['imprecise-centred-slope']={'fault':failure['code'],'replay':replay['code'],'interval':missed[0]['observed']}
        directory=root/'inference-exact-fit'
        rejected=fault(lambda:adaptor.run(example('inference-exact-invalid'),directory,executable=args.executable,timeout=args.timeout),'NO_RESIDUAL_VARIANCE')
        assert rejected['location']=='$.inference' and not directory.exists()
        report['negative']['exactFitInference']={'code':rejected['code'],'location':rejected['location'],'nativeLaunched':False}
        directory=root/'inference';saved={path:path.read_bytes() for path in directory.iterdir() if path.is_file()}
        try:
            for stage in ('fit','reopen'):
                path=directory/(stage+'-inference.csv');lines=path.read_text().splitlines();cells=lines[2].split(',')
                cells[4]=format(float(cells[4])*1.01,'.17g');lines[2]=','.join(cells);path.write_text('\n'.join(lines)+'\n')
            refresh(directory);rejected=fault(lambda:adaptor.verify(directory),'VERIFICATION_FAILED')
            assert 'pValue' in rejected['message'];report['negative']['forgedNativePValueWithRefreshedOrdinaryHashes']=rejected['code']
        finally:
            for path,data in saved.items():path.write_bytes(data)
            finalise(directory)
        assert adaptor.verify(directory)['verified']
        study=example('requirement-study');directory=root/'finite-study'
        adaptor.run(study,directory,executable=args.executable,timeout=args.timeout)
        assert adaptor.verify(directory)['verified'];report['accepted']['finite-study']=True
        directory=root/'regression';saved={path:path.read_bytes() for path in directory.iterdir() if path.is_file()}
        try:
            (directory/'model.rds').write_bytes(b'\0'*(directory/'model.rds').stat().st_size);refresh(directory)
            rejected=fault(lambda:adaptor.verify(directory),'VERIFICATION_FAILED')
            assert 'consumed different input/model' in rejected['message'];report['negative']['changedModelWithRefreshedOrdinaryHashes']=rejected['code']
        finally:
            for path,data in saved.items():path.write_bytes(data)
            finalise(directory)
        try:
            authored=json.loads(saved[directory/'authored.json']);authored['requirements'][0]['maximum']=.01
            atomic_json(directory/'authored.json',authored);atomic_json(directory/'plan.json',adaptor.plan(authored))
            summary=json.loads(saved[directory/'regression-summary.json']);item=summary['acceptance']['requirements'][0]
            item['maximum']=.01;item['checks'][0].update(expected=.01,passed=True,margin=.01)
            atomic_json(directory/'regression-summary.json',summary);refresh(directory)
            report['negative']['forgedAcceptanceWithRefreshedOrdinaryHashes']=fault(lambda:adaptor.verify(directory),'VERIFICATION_FAILED')['code']
        finally:
            for path,data in saved.items():path.write_bytes(data)
            finalise(directory)
        assert adaptor.verify(directory)['verified']
        doc=example('to-calc');locations={'r':args.executable,'calc':args.calc};directory=root/'calc-handoff'
        result=workflow.execute(doc,directory,locations=locations,timeout=args.timeout);assert workflow.verify(directory)['verified']
        jobs={job['operation']:job for job in result['jobs']};assert set(jobs)=={'regression','workbook'}
        source=read_csv(Path(jobs['regression']['directory'])/'heldout.csv');observed=read_csv(Path(jobs['workbook']['directory'])/'data.csv')
        assert close(source,observed,rel=1e-12,absolute=1e-12)
        workbook_directory=Path(jobs['workbook']['directory'])
        caches=workbook_observations(workbook_directory)
        assessment=json.loads((workbook_directory/'requirements.json').read_text())
        assert assessment['passed'] and len(assessment['requirements'])==3
        assert set(assessment['formats'])=={'xlsx','ods'}
        for format_result in assessment['formats'].values():
            assert format_result['passed'] and len(format_result['checks'])==3
            assert {check['name'] for check in format_result['checks']}=={'residual_lower','residual_upper','residual_identity'}
            assert all(check['status']=='passed' for check in format_result['checks'])
        resumed=workflow.execute(doc,directory,locations=locations,timeout=args.timeout,resume=True)
        assert {job['operation'] for job in resumed['jobs']}==set(jobs) and all(job['reused'] for job in resumed['jobs'])
        report['workflows']['acceptedCalcHandoffAndReuse']={'jobs':2,'sameNumericTable':True,'namedChecksPerFormat':3,'independentNativeCaches':caches}
        bad=copy.deepcopy(doc);bad['operations'][0]['document']['requirements'][0]['maximum']=.01
        directory=root/'unmet-calc-handoff'
        for attempt in (1,2):
            rejected=fault(lambda:workflow.execute(bad,directory,locations=locations,timeout=args.timeout,resume=attempt==2),'FIT_REQUIREMENT_NOT_MET')
            failed=json.loads((directory/'result.json').read_text());assert failed['status']=='failed' and not failed['verified']
            assert len(failed['jobs'])==1 and failed['jobs'][0]['operation']=='regression' and failed['jobs'][0]['status']=='failed'
            assert any(job.startswith('workbook') for job in failed['pendingJobs'])
            assert not list((directory/'workbook').glob('batch-*/attempt-*'))
        assert len(list((directory/'regression'/'batch-0').glob('attempt-*')))==2
        report['workflows']['unmetBlocksConsumerAndReuse']={'fault':rejected['code'],'freshFailedProducerAttempts':2,'consumerAttempts':0}
        bad=copy.deepcopy(doc);bad['operations'][1]['document']['requirements'][0]['minimum']=-.1
        directory=root/'unmet-workbook'
        producer_directory=None
        for attempt in (1,2):
            rejected=fault(lambda:workflow.execute(bad,directory,locations=locations,timeout=args.timeout,resume=attempt==2),'REQUIREMENTS_UNMET')
            failed=json.loads((directory/'result.json').read_text());assert failed['status']=='failed' and not failed['verified']
            jobs={job['operation']:job for job in failed['jobs']};assert set(jobs)=={'regression','workbook'}
            assert jobs['regression']['status']=='succeeded' and jobs['workbook']['status']=='failed'
            producer_directory=Path(jobs['regression']['directory']);assert adaptor.verify(producer_directory)['verified']
            if attempt==2:assert jobs['regression']['reused'] and not jobs['workbook'].get('reused',False)
            consumer_attempts=sorted((directory/'workbook'/'batch-0').glob('attempt-*'))
            assert len(consumer_attempts)==attempt
            workbook_directory=consumer_attempts[-1];workbook_observations(workbook_directory)
            assessment=json.loads((workbook_directory/'requirements.json').read_text());assert not assessment['passed']
            for format_result in assessment['formats'].values():
                assert not format_result['passed']
                assert {check['name'] for check in format_result['checks'] if check['status']!='passed'}=={'residual_lower'}
            assert not (workbook_directory/'verification.json').exists()
        assert len(list((directory/'regression'/'batch-0').glob('attempt-*')))==1
        assert len(list((directory/'workbook'/'batch-0').glob('attempt-*')))==2
        report['workflows']['consumerAcceptanceIndependent']={'fault':rejected['code'],'producerVerified':True,
            'producerReusedOnRetry':True,'producerAttempts':1,'freshFailedConsumerAttempts':2,'unmetChecksPerFormat':['residual_lower']}
        assert source_digest('r')==report['sourceDigest'],'source changed during native acceptance'
        assert all(source_digest(name)==value for name,value in report['sourceDigests'].items()),'adaptor source changed during native handoff acceptance'
        report['verified']=True
    finally:atomic_json(root/'qualification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
