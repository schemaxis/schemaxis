#!/usr/bin/env python3
"""Qualify typed pure/seeded Body capture, SDK saves and retired-source reuse.

Run from a source checkout, or use an installed Schemaxis environment with an
explicit public examples directory. All native projects and mutated packets are
created beneath a NEW output directory. This is a focused qualification, not
whole-FreeCAD acceptance. No submitted user project is restored by this tool.
"""
import argparse
import json
import math
from pathlib import Path
import shutil
import time

from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.core.runners import Interpreter
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.adaptors.freecad.part_reconstruction import body_reference_lifecycle
from schemaxis.publication_metadata import finalise
from freecad_body_history_cases import documents,expectations,assembly_document,world_centres,world_expectations,plate_oracle
from freecad_body_history_guards import qualify_guards

EXAMPLES=Path(__file__).resolve().parents[1]/'examples'/'schemaxis'


def near(actual,expected):
    if isinstance(expected,list):
        assert isinstance(actual,list) and len(actual)==len(expected),(actual,expected)
        for a,b in zip(actual,expected):near(a,b)
    else:assert math.isclose(actual,expected,rel_tol=1e-7,abs_tol=1e-6),(actual,expected)


def check_shape(observed,expected):
    for key,value in expected.items():near(observed[key],value)


def worker(work,module,stage,runtime,executable,*,body=False):
    # Finite installed workers receive only this tool's freshly built projects.
    script='import sys\nsys.path.insert(0,'+repr(str(runtime))+')\n'
    script+='from schemaxis.adaptors.freecad.'+module+' import '+stage+'\n'
    script+='from schemaxis.native_boundary import execute_guarded\n'
    if body:
        script+='from functools import partial\nexecute_guarded(partial('+stage+',body_local=True),'+repr(str(work))+')\n'
    else:script+='execute_guarded('+stage+','+repr(str(work))+')\n'
    for name in ('native-fault.json',): (work/name).unlink(missing_ok=True)
    result=SubprocessRunner(Interpreter('freecad',str(executable)),work,timeout=120)(script)
    atomic_json(work/(stage+'-submission.json'),result.to_dict())
    if (work/'native-fault.json').exists():
        raise SchemaxisError(Fault(**json.loads((work/'native-fault.json').read_text())))


def qualify(root,executable,gui=None,*,examples=EXAMPLES,save_count=3):
    if type(save_count) is not int or not 0<=save_count<=8:
        raise ValueError('save_count must be an integer from 0 through 8')
    root=Path(root).absolute();examples=Path(examples).absolute()
    executable=Path(executable).resolve(strict=True)
    if gui:gui=Path(gui).resolve(strict=True)
    root.mkdir(parents=True,exist_ok=False)
    locations={'freecad':str(executable)}
    if gui:locations['freecad_gui']=str(gui)
    pin=source_digest('freecad');runtime=root/'trusted-runtime.zip';runtime.write_bytes(runtime_archive())
    report={'verified':False,'sourceDigest':pin,'runtimeSha256':file_digest(runtime),
            'recipeSha256':file_digest(Path(__file__)),
            'helperSha256':{p.name:file_digest(p) for p in (
                Path(__file__).with_name('freecad_body_history_cases.py'),
                Path(__file__).with_name('freecad_body_history_guards.py'))},
            'guiRequested':bool(gui),'savedStatesPerSource':save_count,'checks':{},
            'scope':'finite typed Body source/copy authority and lifecycle; not full FreeCAD',
            'contracts':{'constructionDefaultSeconds':300,'standaloneDefaultSeconds':120}}
    start=time.monotonic()
    def checked(label,call):
        stamp=time.monotonic();report['activePhase']=label;atomic_json(root/'report.json',report)
        try:value=call()
        except BaseException as error:
            report['failure']={'phase':label,'type':type(error).__name__,'message':str(error)}
            raise
        report.pop('activePhase',None)
        report['checks'][label]={'verified':True,'seconds':time.monotonic()-stamp}
        atomic_json(root/'report.json',report);return value
    try:
        with location_context(locations):
            asset=root/'original.stl';shutil.copyfile(examples/'freecad-body-stock.stl',asset)
            recipes=documents(examples,asset)
            report['inputs']={'originalSTLSha256':file_digest(asset),
                'examples':{name:file_digest(examples/name) for name in (
                    'freecad-part-design.json','freecad-parametric-enclosure.json',
                    'freecad-drilled-enclosure.json','freecad-body-stock-turned.json')}}
            producers={};states={}
            report['sourceStates']={'constructionSourceDigest':pin,'states':states}
            for name,document in recipes.items():
                producer=root/('producer-'+name)
                checked('build-'+name,lambda:registry.run(document,producer,locations=locations))
                checked('initial-public-'+name,lambda:registry.verify(producer));producers[name]=producer
                initial=json.loads((producer/'verification.json').read_text())
                check_shape(initial['bodyLocalExportEvidence']['shape'],expectations()[name])
                for representation in ('native','step'):
                    check_shape(initial['exportEvidence'][representation],world_expectations()[name])
                current=root/('saves-'+name);current.mkdir();baseline=None;states[name]=[]
                for member in ('plan.json','sources.json','model.FCStd'):shutil.copyfile(producer/member,current/member)
                for step in range(1,save_count+1):
                    checked('trusted-save-'+name+'-'+str(step),
                        lambda:worker(current,'part_reference_native','resave',runtime,executable,body=True))
                    candidate=current/'resaved';baseline=body_reference_lifecycle(candidate,baseline)
                    states[name].append({'step':step,'file':str(candidate/'model.FCStd'),
                                         'sha256':file_digest(candidate/'model.FCStd')})
                    if step<save_count:
                        for member in ('plan.json','sources.json'):shutil.copyfile(current/member,candidate/member)
                        current=candidate
                if save_count:
                    shutil.copyfile(candidate/'model.FCStd',producer/'model.FCStd')
                    receipt=json.loads((producer/'verification.json').read_text())
                    receipt['artifacts'][2]['sha256']=file_digest(producer/'model.FCStd')
                    atomic_json(producer/'verification.json',receipt);finalise(producer)
                checked('saved-public-'+name,lambda:registry.verify(producer))
            report['sourceStates']={'constructionSourceDigest':pin,'states':states}
            doc=assembly_document(producers)
            pure={'version':'schemaxis.freecad.assembly/1','parts':[doc['parts'][0]],
                  'components':[{'id':'fixed','part':'parametered'},{'id':'copy','part':'parametered'}],
                  'grounded':'fixed','joints':[{'id':'join','type':'fixed',
                      'parent':{'component':'fixed','mount':'o'},
                      'child':{'component':'copy','mount':'o'},'offset':[90,0,0]}]}
            purejob=root/'pure-gen1'
            checked('pure-gen1-configured-run',lambda:registry.run(pure,purejob,locations=locations))
            checked('pure-gen1-standalone',lambda:registry.verify(purejob))
            check_shape(json.loads((purejob/'capture.json').read_text())['parts']['parametered']['shape'],plate_oracle())
            guards=checked('refreshed-before-open-guards',lambda:qualify_guards(purejob,root/'guards',locations))
            report['guardReportSha256']=file_digest(root/'guards/report.json')
            assert guards['verified']
            envelope={'version':'schemaxis.workflow/1',
                'execution':{'maxWorkers':1,'cpus':2,'memoryMB':3072,'gpus':0},
                'operations':[{'id':'assembly','document':doc}]}
            atomic_json(root/'workflow-authored.json',envelope);wf=root/'workflow'
            result=checked('mixed-workflow',lambda:workflow.execute(envelope,wf,locations=locations))
            job=Path(result['jobs'][0]['directory']);report['assemblyJob']=str(job)
            checked('mixed-standalone',lambda:registry.verify(job));checked('mixed-workflow-verify',lambda:workflow.verify(wf))
            captured=json.loads((job/'capture.json').read_text())
            for name,expected in expectations().items():check_shape(captured['parts'][name]['shape'],expected)
            components=json.loads((job/'verification.json').read_text())['snapshots']['solved']['components']
            for name,centre in world_centres().items():near(components[name]['shape']['centreOfMass'],centre)
            report['checks']['literalLocalWorldGeometry']={'verified':True,'parts':6,'instances':7}
            before=file_digest(job/'model.FCStd');moves=[]
            try:
                for producer in producers.values():
                    retired=producer.with_name(producer.name+'.retired');producer.rename(retired);moves.append((retired,producer))
                retired=asset.with_suffix('.retired');asset.rename(retired);moves.append((retired,asset))
                checked('retired-standalone',lambda:registry.verify(job))
                checked('retired-workflow-verify',lambda:workflow.verify(wf))
                replaced=producers['parametered'];replaced.mkdir();(replaced/'model.FCStd').write_bytes(b'changed old path')
                try:
                    checked('changed-old-path-standalone',lambda:registry.verify(job))
                    try:workflow.execute(envelope,wf,locations=locations,resume=True)
                    except SchemaxisError as error:
                        assert error.fault.code in ('INPUT_CHANGED','UNSUPPORTED_SOURCE'),error.fault
                        report['checks']['changedPresentOriginalRefused']=error.fault.to_dict()
                    else:raise AssertionError('Changed present original reused')
                finally:(replaced/'model.FCStd').unlink();replaced.rmdir()
                reused=checked('fully-retired-resume',lambda:workflow.execute(envelope,wf,locations=locations,resume=True))
                assert reused['jobs'][0]['reused'] and file_digest(job/'model.FCStd')==before
                private=root/'native-copy';private.mkdir()
                for name in ('plan.json','built.json','model.FCStd'):shutil.copyfile(job/name,private/name)
                atomic_json(private/'edit-request.json',{'part':'parametered','parameter':'thickness','value':7,'output':'edited.FCStd'})
                checked('copied-parameter-edit',lambda:worker(private,'assembly_sources_native','edit_probe',runtime,executable))
                edited=json.loads((private/'edit.json').read_text())
                for name in ('parametered','parameteredAgain'):
                    near(edited['snapshots']['probed']['components'][name]['shape']['volume'],plate_oracle(7)['volume'])
                near(edited['snapshots']['probed']['components']['parameteredAgain']['matrix'][11],24)
                near(edited['snapshots']['probed']['components']['parameteredAgain']['shape']['centreOfMass'][2],27.5)
                atomic_json(private/'inspect-request.json',{'file':str(private/'edited.FCStd'),'receipt':'edited-reopen.json'})
                checked('copied-edit-fresh-reopen',lambda:worker(private,'assembly_sources_native','inspect_copy',runtime,executable))
                reopened=json.loads((private/'edited-reopen.json').read_text());assert reopened['pid']!=edited['pid']
                for name in ('parametered','parameteredAgain'):
                    near(reopened['snapshots']['persisted']['components'][name]['shape']['volume'],plate_oracle(7)['volume'])
                near(reopened['snapshots']['persisted']['components']['parameteredAgain']['matrix'][11],24)
                near(reopened['snapshots']['persisted']['components']['parameteredAgain']['shape']['centreOfMass'][2],27.5)
                assert file_digest(job/'model.FCStd')==before
            finally:
                for retired,original in reversed(moves):retired.rename(original)
            checked('all-restored-public',lambda:registry.verify(job))
            assert file_digest(job/'model.FCStd')==before and source_digest('freecad')==pin
            report['verified']=True
    finally:
        report['elapsedSeconds']=time.monotonic()-start;atomic_json(root/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad',required=True,type=Path)
    parser.add_argument('--freecad-gui',type=Path)
    parser.add_argument('--examples-directory',type=Path,default=EXAMPLES)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--save-count',type=int,default=3,choices=range(0,9),
                        help='trusted saves per new source (default 3); zero omits save-state coverage')
    args=parser.parse_args()
    print(json.dumps({'verified':qualify(args.output_directory,args.freecad,args.freecad_gui,
        examples=args.examples_directory,save_count=args.save_count)['verified']}))


if __name__=='__main__':main()
