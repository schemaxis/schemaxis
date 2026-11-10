#!/usr/bin/env python3
"""Public-route qualification of the three finite Blender simulation-cache modes.

Creates only NEW qualifier-owned projects. All original packets are restored
following attacks. Native qualification requires the actual integrated hooks;
this tool cannot turn isolated kernel success into public feature acceptance.
"""
import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import threading
import textwrap
import sys
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import SubprocessRunner
from schemaxis.publication_metadata import finalise
from qualify_blender_caches_native import PROBE, literal_geometry

ORDER=[10,1,7,3,9,2,8,4,6,5]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(executable, runtime, scene, out, kind, *, edit=False):
    config={'scene':str(scene),'output':str(out),'kind':kind,'frames':ORDER,
            'objects':['Faller','Floor'] if kind=='rigidBody' else ['Sheet'],'edit':edit}
    code='import sys\nsys.path.insert(0,'+repr(str(runtime))+')\nCONFIG='+repr(config)+'\n'+PROBE
    script=out.with_suffix('.py');ast.parse(code,filename=str(script));compile(code,str(script),'exec');script.write_text(code)
    result=subprocess.run([str(executable),'--background','--factory-startup','--disable-autoexec','--threads','1',
                           '--python-exit-code','1','--python',str(script)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
    out.with_suffix('.log').write_bytes(result.stdout)
    if result.returncode:raise RuntimeError('native cache probe failed: '+str(out.with_suffix('.log')))
    return json.loads(out.read_text())


def _replace(value, old, new):
    if isinstance(value,dict):return {k:_replace(v,old,new) for k,v in value.items()}
    if isinstance(value,list):return [_replace(v,old,new) for v in value]
    return new if value==old else value


def _mass(value):
    if isinstance(value,dict):return {k:(2 if k=='mass' and type(v) in (int,float) else _mass(v)) for k,v in value.items()}
    if isinstance(value,list):return [_mass(v) for v in value]
    return value


def packet_snapshot(directory):
    return {p.relative_to(directory):p.read_bytes() for p in directory.rglob('*') if p.is_file() and '__pycache__'not in p.parts}


def restore(directory, original):
    # Do not rewrite immutable runtime archives unless bytes actually changed.
    for relative,data in original.items():
        target=directory/relative
        if not target.exists() or target.read_bytes()!=data:
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    for target in directory.rglob('*'):
        if target.is_file() and target.relative_to(directory) not in original and target.suffix in ('.blend1','.blend2'):
            target.unlink()
    if any((directory/name).read_bytes()!=data for name,data in original.items()):raise ValueError('owned packet restoration failed')


WITNESS_FILES=('built.json','verification.json','reopened.json')


def retained_pair_consistent(receipt,reopened):
    if reopened.get('states')!=[state['snapshot'] for state in receipt['states']]:
        raise AssertionError('qualifier created inconsistent retained state witnesses')
    if reopened.get('production')!=[state.get('production') for state in receipt['states']]:
        raise AssertionError('qualifier created inconsistent retained production witnesses')
    expected=[a['after'] for a in receipt['artifacts'] if a.get('productionOutput')]
    if reopened.get('productionOutputs')!=expected:
        raise AssertionError('qualifier created inconsistent retained output witnesses')


def rewrite_witnesses(directory,transform):
    for name in WITNESS_FILES:
        path=directory/name
        if path.exists():atomic_json(path,transform(json.loads(path.read_text())))
    retained_pair_consistent(json.loads((directory/'verification.json').read_text()),
                             json.loads((directory/'reopened.json').read_text()))


def refresh(directory, changes):
    def transform(value):
        for old,new in changes:value=_replace(value,old,new)
        return value
    rewrite_witnesses(directory,transform)
    finalise(directory)


def drop_missing_member(value, missing, relative):
    """Reforge only saved companion membership; typed authored intent stays fixed."""
    if isinstance(value,list):
        return [drop_missing_member(item,missing,relative) for item in value
                if not isinstance(item,dict) or not (item.get('file')==missing or item.get('relativePath')==relative)]
    if isinstance(value,dict):return {k:drop_missing_member(v,missing,relative) for k,v in value.items() if k not in (Path(missing).name,relative)}
    return value


def guarded_attacks(target, out, executable, runtime, kind, storage):
    out.mkdir();scene=target/'0000.blend';original=packet_snapshot(target);baseline_sha=digest(scene)
    log=out/'native-opens.jsonl';report={'verified':False,'attacks':{},'opens':{}};original_popen=subprocess.Popen
    def audited(command,*args,**kwargs):
        audit=('import bpy as _a,json as _j,hashlib as _h\nfrom pathlib import Path as _P\n'
               '_had_wm="wm" in vars(_a.ops)\n_old_wm=vars(_a.ops).get("wm")\n_wm=_a.ops.wm\n_open=_wm.open_mainfile\ndef _audit(*args,**kwargs):\n'
               ' p=str(kwargs.get("filepath",args[0] if args else ""))\n'
               ' with open('+repr(str(log))+',"a") as stream:stream.write(_j.dumps({"path":p,"sha256":_h.sha256(_P(p).read_bytes()).hexdigest()})+"\\n")\n'
               ' return _open(*args,**kwargs)\n_wm.open_mainfile=_audit\n_a.ops.wm=_wm\n')
        if isinstance(command,(list,tuple)) and command and Path(command[0]).resolve()==executable.resolve() and '--python' in command:
            script=Path(command[command.index('--python')+1]);code=script.read_text()
            if 'from schemaxis.adaptors.blender.native import reopen' in code:
                combined=audit+'try:\n'+textwrap.indent(code,'    ')+'finally:\n    if _had_wm:_a.ops.wm=_old_wm\n    else:delattr(_a.ops,"wm")\n';ast.parse(combined,filename=str(script));compile(combined,str(script),'exec')
                report.setdefault('auditedScripts',[]).append({'path':str(script),'originalSha256':digest(script),
                    'auditedSha256':hashlib.sha256(combined.encode()).hexdigest()})
                script.write_text(combined)
        return original_popen(command,*args,**kwargs)
    def reject(label, native_mutant=False):
        log.unlink(missing_ok=True)
        try:registry.verify(target)
        except SchemaxisError as error:
            fault=error.fault.to_dict()
            report.setdefault('observedFaults',{})[label]=fault;atomic_json(out/'report.json',report)
            triple=(error.fault.code,error.fault.message,error.fault.location)
            native_faults={('INPUT_CHANGED','saved cache physics inputs differ from fresh constructor','$'),
                           ('VERIFICATION_FAILED','saved cache owner/range/storage/bake state differs','$')}
            if label=='native-parameter-edit':accepted=triple in native_faults
            elif label=='coforged-parameter-evidence':
                field='rigidBodies' if kind=='rigidBody' else 'cloth'
                accepted=triple==('VERIFICATION_FAILED','production native value differs','production.'+field)
            elif label in ('disk-edited','disk-corrupt'):
                accepted=triple==('VERIFICATION_FAILED','whole managed cache payload differs from fresh construction','$')
            elif label=='disk-missing':
                accepted=triple in {('VERIFICATION_FAILED','Blender publication count differs','$'),
                                   ('VERIFICATION_FAILED','simulation cache frame membership differs','$')}
            else:accepted=False
            if not accepted:raise
            report['attacks'][label]=error.fault.to_dict()
        else:raise AssertionError('unsafe public cache acceptance: '+label)
        values=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        forbidden=[v for v in values if Path(v['path'])==scene or native_mutant and v['sha256']==digest(scene)]
        if forbidden and not native_mutant:raise AssertionError(('submitted cache payload opened before file-authority refusal',label,forbidden))
        report.setdefault('admissionStages',{})[label]='native physics/packed checks after admitted open' if native_mutant else 'whole disk payload before submitted open'
        report['opens'][label]=values;atomic_json(out/'report.json',report)
    try:
        baseline=probe(executable,runtime,scene,out/'baseline.json',kind)
        with patch.object(subprocess,'Popen',audited):
            registry.verify(target)
            positive=[json.loads(line)for line in log.read_text().splitlines()]if log.exists()else[]
            if not positive:raise AssertionError('native-open audit lacks a positive control')
            report['positiveOpens']=positive
            edited=probe(executable,runtime,scene,out/'edited.json',kind,edit=True)
            refresh(target,[(baseline_sha,digest(scene))]);reject('native-parameter-edit',True)
            # Reforge both observation companions, input witnesses and outer hashes;
            # authored constructor intent remains original and must stay authority.
            rewrite_witnesses(target,lambda value:_mass(_replace(value,baseline['inputFingerprint'],edited['inputFingerprint'])))
            finalise(target);reject('coforged-parameter-evidence',True)
            restore(target,original)
            if storage=='disk':
                files=sorted(target.glob('blendcache_0000/*.bphys'))
                if not files:raise AssertionError('public disk cache artifacts absent')
                file=files[0];old=file.read_bytes();old_sha=digest(file)
                for label,content in [('disk-edited',old[:-1]+bytes([old[-1]^1])),('disk-corrupt',b'corrupt')]:
                    file.write_bytes(content);refresh(target,[(old_sha,digest(file))]);reject(label);restore(target,original)
                file.unlink();file.with_name(file.name+'.metadata.json').unlink(missing_ok=True)
                rewrite_witnesses(target,lambda value:drop_missing_member(value,str(file),str(file.relative_to(target))))
                finalise(target);reject('disk-missing');restore(target,original)
            result=registry.verify(target)
            if not result['verified']:raise AssertionError('restored public cache failed')
        report['verified']=True
    finally:
        restore(target,original);report['restoredExact']=all((target/n).read_bytes()==b for n,b in original.items());atomic_json(out/'report.json',report)
    return report



def render_input_retirement(output, executable, examples):
    """Retire a real captured colour input; do not imply physics depends on it."""
    from schemaxis.captured_inputs import adopt
    from schemaxis.workflow import execute, verify
    root=output/'render-input-retirement';root.mkdir()
    producer=root/'colour-producer';producer.mkdir();source=producer/'colour.png'
    source.write_bytes((examples/'blender-image-preview.png').read_bytes())
    adopted=adopt(source,root/'colour-snapshot')
    document=json.loads((examples/'blender-simulation-cache-cloth-packed.json').read_text())
    production=document['production']
    production['images']=[{'id':'capturedColour','file':adopted['reference'],'pack':True}]
    production['objects'][0]['material']='capturedSurface'
    production['materialGraphs']=[{'id':'capturedSurface','nodes':[
        {'id':'colour','kind':'image','properties':{'image':'capturedColour'}},
        {'id':'light','kind':'emission'}, {'id':'finish','kind':'output'}],
        'links':[{'from':{'node':'colour','socket':'colour'},'to':{'node':'light','socket':'colour'}},
                 {'from':{'node':'light','socket':'shader'},'to':{'node':'finish','socket':'surface'}}]}]
    workflow={'version':'schemaxis.workflow/1','operations':[{'id':'cachedCloth','document':document}]}
    target=root/'workflow'
    atomic_json(root/'request.json',workflow)
    execute(workflow,target,blender=str(executable),timeout=300)
    if not verify(target)['verified']:raise AssertionError('captured-input baseline failed')
    retained={str(p.relative_to(root/'colour-snapshot')):digest(p) for p in (root/'colour-snapshot').rglob('*') if p.is_file()}
    retired=root/'colour-producer.retired';producer.rename(retired)
    receipt={'verified':False,'scope':'captured render-input retirement with cache project; physics-independent colour input',
             'snapshotDigest':adopted['digest'],'retainedFiles':retained,'originalSha256':digest(retired/'colour.png')}
    try:
        if producer.exists() or source.exists():raise AssertionError('original colour source still present')
        if not verify(target)['verified']:raise AssertionError('retired render-input verification failed')
        execute(workflow,target,blender=str(executable),timeout=300,resume=True)
        if not verify(target)['verified']:raise AssertionError('retired render-input resume failed')
        if any(digest(root/'colour-snapshot'/p)!=sha for p,sha in retained.items()):raise AssertionError('retained snapshot changed')
        receipt['verified']=True;return receipt
    except BaseException as error:
        receipt['failure']={'type':type(error).__name__,'message':str(error)};raise
    finally:
        active=sys.exc_info()[0] is not None
        try:
            if producer.exists():raise AssertionError('unknown original producer blocks restoration')
            retired.rename(producer)
            receipt['originalRestoredExact']=digest(source)==receipt['originalSha256']
            if not receipt['originalRestoredExact']:raise AssertionError('original colour bytes changed')
        except BaseException as error:
            receipt['verified']=False;receipt['restorationFailure']={'type':type(error).__name__,'message':str(error)}
            if not active:raise
        finally:atomic_json(root/'report.json',receipt)


def public_cancel_recovery(output, executable, examples):
    """Cancel only after a native-owned actual bake-start event, then recover."""
    from schemaxis.dispatch import allocation
    root=output/'cancel-recovery';root.mkdir();target=root/'interrupted'
    document=json.loads((examples/'blender-simulation-cache-cloth-packed.json').read_text())
    production=document['production'];production['frameEnd']=1000
    production['simulationFrames']=[1,1000]
    production['simulationCaches'][0]['frameEnd']=1000
    # Same supported cloth consumer, enlarged finite mesh/range to keep bake active.
    n=30;sheet=production['objects'][0]
    sheet['vertices']=[[x/(n-1)*2-1,y/(n-1)*2-1,2]for y in range(n)for x in range(n)]
    sheet['faces']=[[y*n+x,y*n+x+1,(y+1)*n+x+1,(y+1)*n+x]for y in range(n-1)for x in range(n-1)]
    production['cloth'][0]['pinVertices']=[0,n-1,n*(n-1),n*n-1]
    cancel=threading.Event();done=threading.Event();observed={'verified':False};cancel_started=time.monotonic()
    def monitor():
        observed['monitorStartedMonotonic']=time.monotonic()
        deadline=time.monotonic()+120
        while not done.wait(.025) and time.monotonic()<deadline:
            for path in target.rglob('cache-events.json') if target.exists() else []:
                try:value=json.loads(path.read_text())
                except (OSError,ValueError):continue
                events=value if isinstance(value,list) else value.get('events',[])
                if any(event.get('event')=='bake-start' for event in events):
                    observed['eventFile']=str(path);observed['events']=value;observed['bakeStartSeconds']=time.monotonic()-cancel_started;observed['bakeStartPublicSeconds']=time.monotonic()-observed['publicRunStartedMonotonic']
                    if not done.wait(.25):
                        try:latest=json.loads(path.read_text())
                        except (OSError,ValueError):latest=value
                        latest_events=latest if isinstance(latest,list) else latest.get('events',[])
                        observed['eventsAtCancellation']=latest
                        observed['completedBeforeCancellation']=any(e.get('event')=='bake-complete' for e in latest_events)
                        observed['cancelRequested']=True;cancel.set()
                    return
    watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
    try:
        with allocation({},cancel):
            observed['publicRunStartedMonotonic']=time.monotonic()
            try:registry.run(document,target,locations={'blender':str(executable)},timeout=300)
            except SchemaxisError as error:
                if error.fault.code!='RUNNER_CANCELLED':raise
                observed['fault']=error.fault.to_dict()
            else:raise AssertionError('public cache cancellation completed unexpectedly')
    finally:done.set();watcher.join(timeout=1);atomic_json(root/'report.json',observed)
    if not observed.get('cancelRequested') or observed.get('completedBeforeCancellation'):raise AssertionError('cancellation did not interrupt an active actual bake')
    deadline_target=root/'deadline'
    deadline_budget=min(20,max(5,observed['bakeStartPublicSeconds']+2));observed['deadlineBudgetSeconds']=deadline_budget;atomic_json(root/'report.json',observed)
    try:registry.run(document,deadline_target,locations={'blender':str(executable)},timeout=deadline_budget)
    except SchemaxisError as error:
        if error.fault.code!='RUNNER_TIMED_OUT':raise
        observed['deadlineFault']=error.fault.to_dict()
    else:raise AssertionError('public cache deadline completed unexpectedly')
    event_paths=list(deadline_target.rglob('cache-events.json'))
    deadline_events=[]
    for path in event_paths:
        value=json.loads(path.read_text());deadline_events.extend(value if isinstance(value,list) else value.get('events',[]))
    if not any(e.get('event')=='bake-start' for e in deadline_events) or any(e.get('event')=='bake-complete' for e in deadline_events):
        raise AssertionError('deadline did not interrupt an actual active native bake')
    observed['deadlineEvents']=deadline_events
    small=json.loads((examples/'blender-simulation-cache-cloth-packed.json').read_text())
    registry.run(small,root/'recovered',locations={'blender':str(executable)},timeout=300)
    if not registry.verify(root/'recovered')['verified']:raise AssertionError('fresh cache recovery failed')
    observed['verified']=True;atomic_json(root/'report.json',observed);return observed


def qualify(output, executable, examples, *, baseline_only=False):
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    executable=Path(executable).resolve(strict=True);examples=Path(examples)
    before=source_digest('blender');runtime=output/'trusted-runtime.zip';runtime.write_bytes(runtime_archive())
    report={'verified':False,'scope':'Public finite rigid-packed/cloth-packed/cloth-disk cache workflows ONLY',
            'baselineOnly':baseline_only,'sourceDigest':before,'runtimeSha256':digest(runtime),'toolSha256':digest(Path(__file__)),
            'helperSha256':digest(Path(__file__).with_name('qualify_blender_caches_native.py')),'checks':{},
            'requiredUnsupported':['rigid-body disk native conversion crash; no joints/motors/soft-body/GN/fluid claims']}
    started=time.monotonic()
    def checked(label,call):
        report['activePhase']=label;atomic_json(output/'report.json',report);stamp=time.monotonic();value=call()
        if isinstance(value,dict) and value.get('verified') is False:raise AssertionError('phase returned false: '+label)
        report['checks'][label]={'verified':True,'seconds':time.monotonic()-stamp};report.pop('activePhase',None);atomic_json(output/'report.json',report);return value
    try:
        with location_context({'blender':str(executable)}):
            for suffix,kind,storage in [('rigid-packed','rigidBody','packed'),('cloth-packed','cloth','packed'),('cloth-disk','cloth','disk')]:
                path=examples/('blender-simulation-cache-'+suffix+'.json');document=json.loads(path.read_text());target=output/suffix
                checked(suffix+'-public-run',lambda:registry.run(document,target,locations={'blender':str(executable)},timeout=300))
                checked(suffix+'-public-verify',lambda:registry.verify(target))
                geometry=checked(suffix+'-scrambled-reopen',lambda:probe(executable,runtime,target/'0000.blend',output/(suffix+'-geometry.json'),kind))
                literal_geometry(geometry['geometry'],kind)
                if baseline_only:continue
                checked(suffix+'-guards',lambda:guarded_attacks(target,output/(suffix+'-guards'),executable,runtime,kind,storage))
            if not baseline_only:checked('captured-render-input-retirement',lambda:render_input_retirement(output,executable,examples))
            if not baseline_only:checked('public-bake-cancel-recovery',lambda:public_cancel_recovery(output,executable,examples))
            if source_digest('blender')!=before or digest(Path(__file__))!=report['toolSha256'] or digest(Path(__file__).with_name('qualify_blender_caches_native.py'))!=report['helperSha256']:raise AssertionError('source or qualifier changed during qualification')
            report['verified']=True
    except BaseException as error:
        report['failure']={'type':type(error).__name__,'message':str(error)}
        if isinstance(error,SchemaxisError):report['failure']['fault']=error.fault.to_dict()
        raise
    finally:report['elapsedSeconds']=time.monotonic()-started;atomic_json(output/'report.json',report)
    return report



def qualify_tail(baseline,output,executable,examples):
    """Reuse only an exact source-bound closed baseline; preserve its receipt."""
    baseline=Path(baseline).absolute();output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    executable=Path(executable).resolve(strict=True);examples=Path(examples)
    old=json.loads((baseline/'report.json').read_text());before=source_digest('blender')
    runtime=baseline/'trusted-runtime.zip'
    if not old.get('verified') or not old.get('baselineOnly') or len(old.get('checks',{}))!=9:
        raise AssertionError('tail requires the exact closed nine-check baseline')
    if old['sourceDigest']!=before or digest(runtime)!=old['runtimeSha256']:
        raise AssertionError('baseline source/runtime no longer matches current provider')
    def pins():
        result={}
        for path in baseline.rglob('*'):
            if path.is_symlink():raise AssertionError('baseline contains unexpected symlink')
            if path.is_file():result[str(path.relative_to(baseline))]=digest(path)
        return result
    original=pins();started=time.monotonic()
    report={'verified':False,'scope':'Remaining public cache lifecycle; initial nine baseline checks carried, not rerun',
            'sourceDigest':before,'runtimeSha256':digest(runtime),'baselineDirectory':str(baseline),
            'baselineReportSha256':digest(baseline/'report.json'),'baselinePins':original,
            'toolSha256':digest(Path(__file__)),'helperSha256':digest(Path(__file__).with_name('qualify_blender_caches_native.py')),
            'checks':{}}
    def checked(label,call):
        report['activePhase']=label;atomic_json(output/'report.json',report);stamp=time.monotonic();value=call()
        if isinstance(value,dict) and value.get('verified') is False:raise AssertionError('phase returned false: '+label)
        report['checks'][label]={'verified':True,'seconds':time.monotonic()-stamp};report.pop('activePhase',None);atomic_json(output/'report.json',report)
    try:
        with location_context({'blender':str(executable)}):
            for suffix,kind,storage in [('rigid-packed','rigidBody','packed'),('cloth-packed','cloth','packed'),('cloth-disk','cloth','disk')]:
                checked(suffix+'-guards',lambda:guarded_attacks(baseline/suffix,output/(suffix+'-guards'),executable,runtime,kind,storage))
            checked('captured-render-input-retirement',lambda:render_input_retirement(output,executable,examples))
            checked('public-bake-cancel-deadline-recovery',lambda:public_cancel_recovery(output,executable,examples))
        if pins()!=original or source_digest('blender')!=before or digest(runtime)!=old['runtimeSha256']:
            raise AssertionError('baseline bytes or source/runtime changed')
        if digest(Path(__file__))!=report['toolSha256'] or digest(Path(__file__).with_name('qualify_blender_caches_native.py'))!=report['helperSha256']:
            raise AssertionError('qualifier changed during tail')
        report['verified']=True
    except BaseException as error:
        report['failure']={'type':type(error).__name__,'message':str(error)}
        if isinstance(error,SchemaxisError):report['failure']['fault']=error.fault.to_dict()
        raise
    finally:
        report['elapsedSeconds']=time.monotonic()-started;report['baselineRestoredExact']=pins()==original;atomic_json(output/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline-only',action='store_true');parser.add_argument('--baseline',type=Path);parser.add_argument('--blender',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);parser.add_argument('--examples',type=Path,default=Path(__file__).resolve().parents[1]/'examples/schemaxis');args=parser.parse_args()
    result=qualify_tail(args.baseline,args.output,args.blender,args.examples) if args.baseline else qualify(args.output,args.blender,args.examples,baseline_only=args.baseline_only)
    print(json.dumps({'verified':result['verified']}))

if __name__=='__main__':main()
