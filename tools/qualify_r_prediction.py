#!/usr/bin/env python3
"""Bounded native qualification of R new-row prediction intervals (stats::predict.lm) on a recorded Rscript."""
import argparse
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import random
import signal
import sys
import threading
import time
from unittest.mock import patch

from schemaxis.adaptor_delivery import source_digest
from schemaxis import dispatch
from schemaxis.adaptors.r import adaptor,reference
from schemaxis.adaptors.r.worker import WORKER
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise,verify as verify_metadata
from schemaxis.tabular import read_csv

ROOT=Path(__file__).resolve().parents[1]
SIGMA=math.sqrt(.05)


def example(name='prediction'):
    return json.loads((ROOT/f'examples/schemaxis/r-{name}.json').read_text())


def fault(callback,code):
    try:callback()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('expected '+code)


def critical(level):
    """Closed-form two-sided Student-t quantile for two degrees of freedom."""
    return level*math.sqrt(2/(1-level*level))


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
    return float(sum(x[i]*inverse[i][j]*x[j] for i in range(p) for j in range(p)))


def native_rows(directory):
    table=read_csv(directory/'reopen-prediction.csv');return [dict(zip(table['columns'],row)) for row in table['rows']]


T_975_DF7=2.364624251592785
HADAMARD_SIGMA=math.sqrt(16*.275/7)


def hadamard_document(interval='individual'):
    """Orthogonal 16-run, eight-predictor design: X'X=16I, h=(1+sum x^2)/16, RSS=16*.275, df=7 exactly."""
    sign=lambda i,j:-1 if bin(i&j).count('1')%2 else 1
    noise=[.3,-.2,.1,.25,-.15,.2,-.1]
    rows=[[sign(i,j) for j in range(1,9)]+[10+sum(.5*j*sign(i,j) for j in range(1,9))+sum(c*sign(i,8+k) for k,c in enumerate(noise,1))] for i in range(16)]
    return {'version':'schemaxis.r/1','operation':'linearRegression','predictors':[{'name':f'x{j}','unit':'m'} for j in range(1,9)],
        'response':{'name':'reading','unit':'V'},'training':rows,
        'prediction':{'interval':interval,'level':.95,'newdata':[[1,-1,1,-1,1,-1,1,-1],[0]*8,[2]*8]}}


def resolution_document(ratio,n=256,p=8,offset=9e8,leverage=1e4,level=.5):
    """Deterministic design with residual sigma = ratio*floor and one new row at the requested leverage (the review counterexample at ratio 1.05)."""
    rnd=random.Random(1);unit=[[rnd.uniform(-1,1) for _ in range(p)] for _ in range(n)]
    base=[offset+sum((j+1)*u for j,u in enumerate(row)) for row in unit];noise=[rnd.gauss(0,1) for _ in range(n)]
    for _ in range(5):
        rows=[u+[b+e] for u,b,e in zip(unit,base,noise)];independent=reference.decompose(rows,True)
        residuals=[row[-1]-sum(c*f for c,f in zip(independent['coefficients'],[1.0]+row[:-1])) for row in rows]
        sigma=math.hypot(*residuals)/math.sqrt(n-p-1);floor=reference.VARIANCE_RATIO*reference.response_tolerance(rows,independent['scaledInfinityCondition'])
        noise=[e*ratio*floor/sigma for e in noise]
    rows=[u+[b+e] for u,b,e in zip(unit,base,noise)];independent=reference.decompose(rows,True)
    def reached(c):
        row=[c]*p;prepared={'training':rows,'intercept':True,'predictors':[{'name':f'x{j}'} for j in range(p)]}
        try:return reference.leverage(prepared,independent,row,'$')[0]
        except SchemaxisError:return math.inf
    low,high=0.0,1.0
    while reached(high)<leverage:high*=2
    for _ in range(60):
        middle=(low+high)/2
        if reached(middle)<leverage:low=middle
        else:high=middle
    return {'version':'schemaxis.r/1','operation':'linearRegression','predictors':[{'name':f'x{j}','unit':'m'} for j in range(p)],'response':{'name':'reading','unit':'V'},
        'training':rows,'prediction':{'interval':'confidence','level':level,'newdata':[[low]*p]}}


def processes():
    """Live /proc snapshot: pid -> parent, process group, start tick and argument vector."""
    table={}
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields=stat.read_text().rsplit(')',1)[1].split()
            arguments=[a.decode(errors='replace') for a in (stat.parent/'cmdline').read_bytes().split(b'\0') if a]
            table[int(stat.parent.name)]={'ppid':int(fields[1]),'pgid':int(fields[2]),'start':int(fields[19]),'arguments':arguments}
        except (OSError,ValueError,IndexError):continue
    return table


def alive(pid,start):
    try:return int(Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19])==start
    except (OSError,ValueError,IndexError):return False


class StageClock:
    """Qualifier-owned clock for the runner: advances by the stage deadline once the R engine is live, and polls fast."""
    def __init__(self,advance):self.advance=advance;self.triggered=threading.Event()
    def monotonic(self):return time.monotonic()+(self.advance if self.triggered.is_set() else 0)
    def sleep(self,seconds):time.sleep(min(seconds,.01))
    def __getattr__(self,name):return getattr(time,name)


def live_reopen(root,name,mode,executable,timeout):
    """Run the prediction example and interrupt the reopen stage only after the genuine R engine process is observed live.

    The same trusted worker, native command and runner execute. The qualifier pauses the observed genuine R
    engine with SIGSTOP and confirms its stopped state before driving the runner's clock or cancel event.
    This race hold prevents natural completion before the runner can terminate the owned process group.
    No R result is faked; the hold is stage-bounded, not an instrumented position inside predict.lm.
    """
    directory=root/name;state={'engine':None,'seen':{},'groups':set(),'hold':None,'watchError':None};stop=threading.Event();cancel=threading.Event();real=adaptor.execute
    marker=str(directory/'worker.R')
    expected_engine=str((Path(executable).resolve().parents[1]/'lib/R/bin/exec/R').resolve())
    assert Path(expected_engine).is_file(),'the expected genuine R engine is absent'
    def watch(clock):
        try:
            while not stop.is_set():
                table=processes()
                for pid,info in table.items():
                    if marker in ' '.join(info['arguments']):
                        state['seen'][pid]={**info,'exe':os.path.realpath(f'/proc/{pid}/exe')};state['groups'].add(info['pgid'])
                        if (state['engine'] is None and '--file='+marker in info['arguments'] and 'reopen' in info['arguments']
                                and state['seen'][pid]['exe']==expected_engine):
                            if not alive(pid,info['start']):continue
                            try:os.kill(pid,signal.SIGSTOP)
                            except ProcessLookupError:continue
                            deadline=time.monotonic()+1
                            held=False
                            while time.monotonic()<deadline and alive(pid,info['start']):
                                status=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]
                                if status=='T':held=True;break
                                time.sleep(.001)
                            assert held,'genuine R engine was not held before timeout/cancellation'
                            state['engine']=pid;state['observedAt']=time.monotonic()
                            state['hold']={'method':'qualifier-owned SIGSTOP after genuine reopen engine observed',
                                'pid':pid,'pgid':info['pgid'],'start':info['start'],'confirmedState':'T',
                                'reopenPredictionCsvPresentAtHold':(directory/'reopen-prediction.csv').exists()}
                            (cancel.set if mode=='cancellation' else clock.triggered.set)()
                time.sleep(.002)
        except Exception as error:
            state['watchError']=repr(error);cancel.set()
    def execute(command,where,stage,limit,environment=None):
        if stage!='reopen':return real(command,where,stage,limit,environment)
        clock=StageClock(limit+.05);watcher=threading.Thread(target=watch,args=(clock,),daemon=True);watcher.start()
        state['stageTimeout']=limit
        try:
            with patch.object(dispatch,'time',clock):return real(command,where,stage,limit,environment)
        finally:stop.set();watcher.join(10)
    code={'timeout':'RUNNER_TIMED_OUT','cancellation':'RUNNER_CANCELLED'}[mode]
    with patch.object(adaptor,'execute',execute),dispatch.allocation({},cancel):
        failed=fault(lambda:adaptor.run(example(),directory,executable=executable,timeout=timeout),code)
    assert state['watchError'] is None,state['watchError']
    assert state['engine'] is not None and state['hold']['confirmedState']=='T','the genuine R engine was never held live'
    # Every owned PID and process group is waited for (bounded), never killed from here.
    deadline=time.monotonic()+10
    while time.monotonic()<deadline and (any(alive(pid,info['start']) for pid,info in state['seen'].items()) or any(info['pgid'] in state['groups'] for info in processes().values())):time.sleep(.05)
    survivors=[pid for pid,info in state['seen'].items() if alive(pid,info['start'])];assert not survivors,('owned processes survived',survivors)
    assert not [pid for pid,info in processes().items() if info['pgid'] in state['groups']],'owned process group still has members'
    engine=state['seen'][state['engine']];prepared=adaptor.plan(example())
    assert engine['arguments'][engine['arguments'].index('--args')+1:]==adaptor.commands(executable,directory,prepared)['reopen'][4:],engine['arguments']
    assert len(adaptor.commands(executable,directory,prepared)['reopen'])-4==6,'reopen takes six worker arguments with a prediction request'
    runtime_root=Path(executable).resolve().parents[1];assert Path(engine['exe']).is_relative_to(runtime_root),(engine['exe'],str(runtime_root))
    version=(directory/'fit-runtime.txt').read_text().splitlines()[0];assert version.startswith('R version 4.6.1'),version
    assert (directory/'worker.R').read_text()==WORKER,'reopen worker must be the unchanged trusted worker'
    assert (directory/'prediction-input.csv').is_file() and (directory/'model.rds').is_file() and (directory/'fit-prediction.csv').is_file()
    assert failed['location'].startswith(str(directory/'.dispatch'/'reopen'/'replay-')),failed['location']
    assert failed['message']=='native execution did not complete',failed['message']
    result=json.loads((directory/'result.json').read_text());assert result=={'status':'failed','verified':False,'fault':result['fault']} and result['fault']['code']==code
    for absent in ('verification.json','regression-summary.json','prediction.csv','coefficients.csv','training.csv','reopen-submission.json'):assert not (directory/absent).exists(),absent
    assert not list(directory.glob('*.metadata.json')),'no publication metadata may exist'
    metrics=json.loads(next((directory/'.dispatch'/'reopen').glob('replay-*.metrics.json')).read_text());assert metrics['fault']==code,metrics['fault']
    assert metrics['exitCode'] in (-15,-9), ('observed R engine exited naturally instead of being terminated', metrics)
    # The timeout fixture advances its own clock; metrics seconds are not real wall time.
    logs={suffix:(directory/('reopen.'+suffix)).stat().st_size for suffix in ('stdout','stderr')}
    refused=fault(lambda:adaptor.verify(directory),'VERIFICATION_FAILED')
    return {'fault':failed['code'],'location':failed['location'],'message':failed['message'],'stageTimeoutSeconds':state['stageTimeout'],'enginePid':state['engine'],
        'processGroups':sorted(state['groups']),'processes':{str(pid):{'ppid':info['ppid'],'pgid':info['pgid'],'start':info['start'],'exe':info['exe'],'arguments':info['arguments']} for pid,info in sorted(state['seen'].items())},
        'allGone':True,'raceHold':state['hold'],'nativeExitCode':metrics['exitCode'],'timeoutMetricsClock':'qualifier-owned clock; not real wall duration','rVersion':version,'reopenArguments':engine['arguments'][engine['arguments'].index('--args')+1:],'logBytes':logs,
        'reopenPredictionCsvPresent':(directory/'reopen-prediction.csv').exists(),'verifyAfterFailure':{'code':refused['code'],'message':refused['message']},
        'scope':'timeout/cancellation terminate a genuine reopen-stage R engine held by qualifier-owned SIGSTOP; stage-bounded hold and kill, predict.lm position not instrumented'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True);parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=120)
    args=parser.parse_args();root=args.output_directory.absolute();root.mkdir(parents=True,exist_ok=False)
    run=lambda name,doc:(adaptor.run(doc,root/name,executable=args.executable,timeout=args.timeout),root/name)[1]
    summary_of=lambda directory:json.loads((directory/'regression-summary.json').read_text())
    report={'version':'schemaxis.r.prediction.qualification/1','verified':False,'sourceDigest':source_digest('r'),'recipeSHA256':file_digest(__file__),
        'scope':'Exact recorded Rscript runtime; optional prediction request for declared predictor-only rows: native stats::predict.lm mean confidence and individual prediction intervals on the genuine fitted and fresh-process reopened lm, '
            'independent QR leverage/Student-t verification, closed-form and exact rational leverage, scale/translation/offset invariance, changed level/type/newdata/response scale, a true eight-predictor literal oracle, per-row interval-type resolution refusal and acceptance, hash-refreshed mutants and live timeout/SIGTERM cancellation of the genuine R reopen/predict.lm stage (stage-bounded kill; predict.lm position not instrumented), plus prelaunch/after-stage controls. '
            'Not model selection, causal, calibration certificate, coverage guarantee or generalisation; no Gnuplot or Calc workflow is qualified here.',
        'accepted':{},'negative':{},'lifecycle':{}}
    def refresh(directory,bindings=True):
        prepared=adaptor.plan(json.loads((directory/'authored.json').read_text()))
        receipt=json.loads((directory/'verification.json').read_text());receipt['artifacts']=adaptor.manifest(directory,prepared)
        receipt['evidence']={name:adaptor.digest(directory,name) for name in adaptor.evidence_names(prepared)}
        for stage in (('fit','reopen') if bindings else ()):atomic_json(directory/(stage+'-inputs.json'),{str(path):adaptor.digest(directory,path.name) for path in adaptor.stage_inputs(directory,prepared,stage)})
        atomic_json(directory/'verification.json',receipt);finalise(directory)
        assert verify_metadata(directory)['verified'],'publication metadata must pass before the semantic attack is asserted'
    try:
        # 1 Closed form: native se.fit, sigma and both interval widths equal the two-df closed forms.
        directory=run('individual',example());result=adaptor.verify(directory);assert result['runtime'].startswith('R version 4.6.1'),result['runtime']
        t=critical(.95);rows=native_rows(directory)
        for row,x in zip(rows,(0,1,3)):
            h=.25+x*x/10
            assert math.isclose(row['seFit'],SIGMA*math.sqrt(h),rel_tol=1e-12) and math.isclose(row['fit'],10+2*x,rel_tol=1e-12,abs_tol=1e-12)
            assert math.isclose(row['confidenceUpper']-row['confidenceLower'],2*t*SIGMA*math.sqrt(h),rel_tol=1e-12)
            assert math.isclose(row['individualUpper']-row['individualLower'],2*t*SIGMA*math.sqrt(1+h),rel_tol=1e-12)
        summary=summary_of(directory)['prediction'];assert summary['interval']=='individual' and summary['verifiedIntervalTypes']==['confidence','individual']
        assert [row['outsideTrainingRange'] for row in summary['rows']]==[[],[],['temperature']] and summary['residualDF']==2
        names=[Path(a['file']).name for a in json.loads((directory/'verification.json').read_text())['artifacts']]
        assert names==['coefficients.csv','training.csv','regression-summary.json','prediction.csv'],names
        report['accepted']['individual-closed-form']={'result':result,'artifacts':names,'rows':[{k:row[k] for k in ('fit','seFit','confidenceLower','confidenceUpper','individualLower','individualUpper')} for row in rows]}
        # 2 Both types are native-verified whichever is published; confidence is the narrower mean interval.
        variant=example('prediction-variant');directory=run('confidence-level-0.9',variant);result=adaptor.verify(directory)
        summary=summary_of(directory)['prediction'];assert summary['interval']=='confidence'
        for row,x in zip(summary['rows'],(-1.5,.5)):
            assert math.isclose(row['halfWidth'],critical(.9)*SIGMA*math.sqrt(.25+x*x/10),rel_tol=1e-9),row
        assert all(native['individualUpper']-native['individualLower']>native['confidenceUpper']-native['confidenceLower'] for native in native_rows(directory))
        report['accepted']['confidence-level-0.9']=result
        # 3 Changed new data, type, level and response scale all propagate to published bytes.
        base=read_csv(root/'individual'/'prediction.csv')
        changed={}
        for name,change in (('level-0.99',lambda d:d['prediction'].update(level=.99)),('type-confidence',lambda d:d['prediction'].update(interval='confidence')),
                            ('newdata',lambda d:d['prediction'].update(newdata=[[-2],[.5]])),('response-1000x',lambda d:d.update(training=[[x,y*1000] for x,y in d['training']]))):
            doc=example();change(doc);directory=run(name,doc);adaptor.verify(directory);changed[name]=read_csv(directory/'prediction.csv')
            assert changed[name]!=base,name
        assert math.isclose(changed['response-1000x']['rows'][0][5],base['rows'][0][5]*1000,rel_tol=1e-9)
        assert math.isclose(changed['level-0.99']['rows'][0][5],base['rows'][0][5]*critical(.99)/critical(.95),rel_tol=1e-9)
        assert changed['newdata']['rows'][0][1]==-2 and len(changed['newdata']['rows'])==2
        report['accepted']['changed-inputs']={name:table['rows'][0] for name,table in changed.items()}
        # 4 Scale/translation/offset invariance of leverage and widths against exact rational leverage.
        for name,factor,shift,offset in (('predictor-1e-6',1e-6,0,0),('predictor-1e6',1e6,0,0),('predictor-shift-20',1,20,0),('response-offset-1e6',1,0,1e6)):
            doc=example();doc['training']=[[x*factor+shift,y+offset] for x,y in doc['training']]
            doc['prediction']['newdata']=[[x*factor+shift] for [x] in doc['prediction']['newdata']];directory=run(name,doc);adaptor.verify(directory)
            for row,x in zip(summary_of(directory)['prediction']['rows'],(0,1,3)):
                assert math.isclose(row['leverage'],exact_leverage(doc['training'],True,[x*factor+shift]),rel_tol=1e-6),(name,row)
                assert math.isclose(row['halfWidth'],t*SIGMA*math.sqrt(1+.25+x*x/10),rel_tol=1e-6),(name,row)
            report['accepted'][name]=True
        # 5 Two predictors and a through-origin model against exact rational leverage.
        doc=example();doc['predictors']=[{'name':'a','unit':'m'},{'name':'b','unit':'s'}]
        doc['training']=[[1,.5,3.1],[2,1.5,5.2],[3,.5,6.9],[4,2.5,9.4],[5,1,11.1],[6,3,13.2]];doc['prediction']['newdata']=[[3,1],[7,.25]]
        for intercept in (True,False):
            doc['intercept']=intercept;directory=run(f'two-predictors-intercept-{intercept}',doc);adaptor.verify(directory)
            for row,new in zip(summary_of(directory)['prediction']['rows'],doc['prediction']['newdata']):
                assert math.isclose(row['leverage'],exact_leverage(doc['training'],intercept,new),rel_tol=1e-8)
            report['accepted'][f'two-predictors-intercept-{intercept}']=True
        # 5b True eight-predictor native case against an independent literal/closed-form oracle (orthogonal Hadamard design: h=(1+sum x^2)/16, df 7, literal t).
        for interval in ('individual','confidence'):
            doc=hadamard_document(interval);directory=run(f'eight-predictors-{interval}',doc);adaptor.verify(directory)
            for row,x in zip(native_rows(directory),doc['prediction']['newdata']):
                h=(1+sum(v*v for v in x))/16
                assert math.isclose(row['seFit'],HADAMARD_SIGMA*math.sqrt(h),rel_tol=1e-10) and math.isclose(row['fit'],10+sum(.5*j*v for j,v in enumerate(x,1)),rel_tol=1e-10,abs_tol=1e-10)
                assert math.isclose(row['confidenceUpper']-row['confidenceLower'],2*T_975_DF7*HADAMARD_SIGMA*math.sqrt(h),rel_tol=1e-10)
                assert math.isclose(row['individualUpper']-row['individualLower'],2*T_975_DF7*HADAMARD_SIGMA*math.sqrt(1+h),rel_tol=1e-10)
                assert math.isclose(exact_leverage(doc['training'],True,x),h,rel_tol=1e-12)
            table=read_csv(directory/'prediction.csv');assert len(table['columns'])==13 and summary_of(directory)['prediction']['residualDF']==7
            report['accepted'][f'eight-predictors-{interval}']={'publishedColumns':len(table['columns']),'note':'13 columns exceed the 12-column consumer limit of the Gnuplot adaptor; accepted disclosure, no Gnuplot handoff for eight predictors'}
        # 5c Per-row resolution on real native runs: the review counterexample is refused before any R process; more scatter at the same leverage is accepted and natively verified.
        directory=root/'resolution-counterexample';rejected=fault(lambda:adaptor.run(resolution_document(1.05),directory,executable=args.executable,timeout=args.timeout),'UNSUPPORTED_PREDICTION')
        assert not directory.exists() and rejected['location']=='$.prediction.newdata[0]' and 'swap of interval types' in rejected['message'],rejected
        assert rejected['observed']['halfWidthGap']<rejected['observed']['requiredHalfWidthGap'] and rejected['observed']['leverage']<reference.MAX_LEVERAGE
        report['negative']['resolution-counterexample']={'code':rejected['code'],'location':rejected['location'],'message':rejected['message'],
            'observed':{key:rejected['observed'][key] for key in ('leverage','halfWidthGap','requiredHalfWidthGap','comparisonAllowance','relativeComponent','resolutionFactor')}}
        doc=resolution_document(50);directory=run('resolution-accepted',doc);result=adaptor.verify(directory);row=summary_of(directory)['prediction']['rows'][0]
        assert result['runtime'].startswith('R version 4.6.1') and math.isclose(row['leverage'],1e4,rel_tol=1e-3)
        native=native_rows(directory)[0];assert native['individualUpper']-native['individualLower']>native['confidenceUpper']-native['confidenceLower']
        report['accepted']['resolution-accepted-h1e4-sigma50x-floor']={'leverage':row['leverage'],'halfWidth':row['halfWidth']}
        # 6 Existing inference/held-out paths and artifact indices are unchanged by an appended request.
        legacy=example('inference');directory=run('inference-legacy',legacy);adaptor.verify(directory)
        legacy_names=[Path(a['file']).name for a in json.loads((directory/'verification.json').read_text())['artifacts']]
        both=example('inference');both['prediction']=example()['prediction'];directory=run('inference-and-prediction',both);result=adaptor.verify(directory)
        names=[Path(a['file']).name for a in json.loads((directory/'verification.json').read_text())['artifacts']]
        assert names==legacy_names+['prediction.csv'] and 'inference' in result and 'prediction' in result
        assert summary_of(directory)['inference']['level']==.95 and summary_of(directory)['prediction']['interval']=='individual'
        assert summary_of(root/'inference-legacy')['inference']==summary_of(directory)['inference']
        report['accepted']['inference-held-out-preserved']={'legacyArtifacts':legacy_names,'withPrediction':names}
        # 7 Pre-native refusals leave no execution directory.
        for name,code in (('prediction-exact-invalid','NO_RESIDUAL_VARIANCE'),('prediction-response-invalid','INVALID_TABLE')):
            directory=root/name;rejected=fault(lambda:adaptor.run(example(name),directory,executable=args.executable,timeout=args.timeout),code)
            assert not directory.exists();report['negative'][name]={'code':code,'location':rejected['location']}
        # 8 Hash-refreshed mutants on real native evidence: ordinary sidecars, digests and readbacks, then separate integrity controls.
        directory=root/'individual';saved={path:path.read_bytes() for path in directory.iterdir() if path.is_file()}
        def restore():
            for path,data in saved.items():path.write_bytes(data)
            finalise(directory)
        def table_edit(name,row,column,change):
            path=directory/name;lines=path.read_text().splitlines();header=lines[0].split(',');cells=lines[row].split(',');index=header.index(column)
            cells[index]=change(cells[index]);lines[row]=','.join(cells);path.write_text('\n'.join(lines)+'\n')
        def both_stages(name,row,column,change):
            for stage in ('fit','reopen'):table_edit(f'{stage}-{name}.csv',row,column,change)
        def swap_types():
            for stage in ('fit','reopen'):
                path=directory/f'{stage}-prediction.csv';lines=path.read_text().splitlines();rows=[line.split(',') for line in lines[1:]]
                for cells in rows:cells[3],cells[5]=cells[5],cells[3];cells[4],cells[6]=cells[6],cells[4]
                path.write_text('\n'.join([lines[0]]+[','.join(cells) for cells in rows])+'\n')
        def reverse_rows():
            for stage in ('fit','reopen'):
                path=directory/f'{stage}-prediction.csv';lines=path.read_text().splitlines();path.write_text('\n'.join([lines[0],*reversed(lines[1:])])+'\n')
        def edit_summary(change):
            data=summary_of(directory);change(data);atomic_json(directory/'regression-summary.json',data)
        half=lambda v:repr(float(v)+1e-3);times=lambda v:repr(float(v)*1.01)
        assert report['accepted']['individual-closed-form']['rows'][0]['fit']!=0,'a zero forgery must contradict a nonzero expected fit'
        native=lambda quantity:f'native prediction {quantity} differs from independent QR leverage intervals'
        mutants=(('shiftedFit1e-3',lambda:both_stages('prediction',1,'fit',half),native('fit[0]'),'fit-prediction'),
            ('wrongZeroFit',lambda:both_stages('prediction',1,'fit',lambda v:'0.0'),native('fit[0]'),'fit-prediction'),
            ('shiftedLowerBound',lambda:both_stages('prediction',2,'individualLower',half),native('individualLower[1]'),'fit-prediction'),
            ('shiftedUpperBound',lambda:both_stages('prediction',3,'confidenceUpper',half),native('confidenceUpper[2]'),'fit-prediction'),
            ('swappedIntervalTypes',swap_types,native('confidenceLower[0]'),'fit-prediction'),('outOfOrderRows',reverse_rows,native('sample[0]'),'fit-prediction'),
            ('wrongSeFit',lambda:both_stages('prediction',1,'seFit',times),native('seFit[0]'),'fit-prediction'),
            ('wrongSigma',lambda:both_stages('prediction-statistics',1,'sigma',times),native('sigma'),'fit-prediction'),
            ('wrongLevel',lambda:both_stages('prediction-statistics',1,'level',lambda v:'0.9'),native('level'),'fit-prediction'),
            ('wrongDF',lambda:both_stages('prediction-statistics',1,'residualDF',lambda v:'3'),native('residualDF'),'fit-prediction'),
            ('wrongCritical',lambda:both_stages('prediction-statistics',1,'criticalValue',times),native('criticalValue'),'fit-prediction'),
            ('changedNewData',lambda:table_edit('prediction-input.csv',3,'x1',lambda v:repr(float(v)+.1)),'captured input differs from declared new predictor rows','prediction'),
            ('reopenOnlyDrift',lambda:table_edit('reopen-prediction.csv',2,'seFit',lambda v:repr(float(v)*(1+1e-6))),'fresh native model reopen prediction differs','$'),
            ('forgedPublishedBound',lambda:table_edit('prediction.csv',2,'upper',lambda v:repr(float(v)+1e-3)),'published prediction table differs','$'),
            ('forgedSummaryLeverage',lambda:edit_summary(lambda d:d['prediction']['rows'][0].update(leverage=.3)),'summary differs from independently checked native model','$'),
            ('forgedSummaryInterval',lambda:edit_summary(lambda d:d['prediction'].update(interval='confidence')),'summary differs from independently checked native model','$'))
        for name,forge,message,location in mutants:
            try:
                forge();refresh(directory);rejected=fault(lambda:adaptor.verify(directory),'VERIFICATION_FAILED')
                assert rejected['message']==message and rejected['location']==location,(name,rejected['message'],rejected['location'])
                report['negative'][name]={'refreshedHashes':True,'metadataVerified':True,'fault':rejected['code'],'message':rejected['message'],'location':rejected['location']}
            finally:restore()
        assert adaptor.verify(directory)['verified']
        # The model bytes are bound by the stage-input sidecar: a hash-refreshed receipt alone does not hide a changed model.
        try:
            (directory/'model.rds').write_bytes(b'\0'*(directory/'model.rds').stat().st_size);refresh(directory,bindings=False)
            rejected=fault(lambda:adaptor.verify(directory),'VERIFICATION_FAILED')
            report['negative']['integrity-changedModel']={'receiptRefreshed':True,'stageBindingsRefreshed':False,'fault':rejected['code'],'message':rejected['message'],'location':rejected['location']}
        finally:restore()
        for name in ('prediction.csv','fit-prediction.csv','reopen-prediction-statistics.csv','prediction-input.csv','regression-summary.json'):
            try:
                path=directory/name;path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'));rejected=fault(lambda:adaptor.verify(directory),'VERIFICATION_FAILED')
                report['negative']['integrity-'+name]={'refreshedHashes':False,'fault':rejected['code'],'message':rejected['message']}
            finally:restore()
        # 9 Lifecycle. Controls: a total deadline spent before any R process exists, and cancellation observed only after both native stages.
        report['lifecycle']['prelaunchTimeoutControl']=fault(lambda:adaptor.run(example(),root/'timeout',executable=args.executable,timeout=1e-6),'RUNNER_TIMED_OUT')['code']
        with patch.object(adaptor,'cancellation_requested',return_value=True):
            report['lifecycle']['afterStageCancellationControl']=fault(lambda:adaptor.run(example(),root/'cancelled',executable=args.executable,timeout=args.timeout),'RUNNER_CANCELLED')['code']
        failed=json.loads((root/'cancelled'/'result.json').read_text());assert failed['status']=='failed' and not failed['verified']
        assert (root/'cancelled'/'reopen-prediction.csv').is_file(),'the after-stage control cancels once the native prediction stage has finished'
        # Live: the genuine R engine of the reopen/predict.lm stage is running when the runner times out or is cancelled.
        report['lifecycle']['liveReopenTimeout']=live_reopen(root,'live-timeout','timeout',args.executable,args.timeout)
        report['lifecycle']['liveReopenCancellation']=live_reopen(root,'live-cancellation','cancellation',args.executable,args.timeout)
        assert source_digest('r')==report['sourceDigest'],'source changed during native acceptance'
        report['verified']=True
    finally:atomic_json(root/'qualification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
