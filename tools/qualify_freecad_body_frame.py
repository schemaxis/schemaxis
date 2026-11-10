#!/usr/bin/env python3
"""Qualify explicit unseeded Body world layout and local assembly composition.

All source projects and mutations belong to a NEW output directory. Uses public
examples and explicit installed CLI/GUI locations. No user FCStd input is accepted.
"""
import argparse
import copy
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
from freecad_body_frame_cases import BODY,CHANGED_BODY,OTHER_BODY,document,local,placed,matrix,flat,poses,assembly,apply
from freecad_body_frame_stl import inspect as inspect_stl
from freecad_body_history_guards import qualify_guards
from freecad_body_frame_guards import qualify as qualify_frame_guards
from qualify_freecad_body_history import near,check_shape,worker

EXAMPLES=Path(__file__).resolve().parents[1]/'examples/schemaxis'
TOOLS=Path(__file__).resolve().parent


def native(directory,stage,runtime,executable):
    script=('import sys\nsys.path.insert(0,'+repr(str(runtime))+')\n'
            'sys.path.insert(0,'+repr(str(TOOLS))+')\n'
            'from qualify_freecad_body_frame_native import '+stage+'\n'
            'from schemaxis.native_boundary import execute_guarded\n'
            'execute_guarded('+stage+','+repr(str(directory))+')\n')
    (directory/'native-fault.json').unlink(missing_ok=True)
    result=SubprocessRunner(Interpreter('freecad',str(executable)),directory,timeout=120)(script)
    atomic_json(directory/(stage+'-submission.json'),result.to_dict())
    if (directory/'native-fault.json').exists():
        raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))


def check_components(snapshot,thickness=7,body_frame=BODY):
    expected=poses(thickness)
    for name,observed in snapshot['components'].items():
        transform=expected[name];near(observed['matrix'],flat(transform))
        t=thickness if name in ('fixed','again') else 7
        check_shape(observed['shape'],placed(transform,t))
        assert observed['linkTransform'] is False
    for name,observed in snapshot.get('sourceBodies',{}).items():
        t=thickness if name=='parametered' else 7
        check_shape(observed['local'],local(t))
        near(observed['placement'],flat(matrix(body_frame if name=='parametered' else BODY)))
        check_shape(observed['world'],placed(matrix(body_frame if name=='parametered' else BODY),t))
    assert snapshot['badStates']=={} and snapshot['externalLinks']==[]


def qualify(root,executable,gui=None,*,examples=EXAMPLES):
    root=Path(root).absolute();root.mkdir(parents=True,exist_ok=False)
    executable=Path(executable).resolve(strict=True);gui=Path(gui).resolve(strict=True) if gui else None
    examples=Path(examples).absolute();locations={'freecad':str(executable)}
    if gui:locations['freecad_gui']=str(gui)
    pin=source_digest('freecad');runtime=root/'trusted-runtime.zip';runtime.write_bytes(runtime_archive())
    helpers=[Path(__file__),TOOLS/'freecad_body_frame_cases.py',TOOLS/'freecad_body_frame_stl.py',
             TOOLS/'freecad_body_frame_guards.py',TOOLS/'qualify_freecad_body_frame_native.py',
             TOOLS/'freecad_body_history_guards.py',TOOLS/'freecad_body_history_cases.py',TOOLS/'qualify_freecad_body_history.py']
    hashes={p.name:file_digest(p) for p in helpers};start=time.monotonic()
    report={'verified':False,'sourceDigest':pin,'runtimeSha256':file_digest(runtime),
            'toolSha256':hashes,'guiRequested':bool(gui),'checks':{},
            'scope':'explicit Body layouts; incomplete whole FreeCAD',
            'budgets':{'constructionDefaultSeconds':300,'aggregateStandaloneDefaultSeconds':120}}
    def checked(name,call):
        stamp=time.monotonic();report['activePhase']=name;atomic_json(root/'report.json',report)
        try:value=call()
        except BaseException as error:
            report['failure']={'phase':name,'type':type(error).__name__,'message':str(error)};raise
        report['checks'][name]={'verified':True,'seconds':time.monotonic()-stamp};report.pop('activePhase',None)
        atomic_json(root/'report.json',report);return value
    try:
        with location_context(locations):
            report['inputs']={name:file_digest(examples/name) for name in (
                'freecad-placed-body.json','freecad-placed-body-attached.json','freecad-placed-bodies.json',
                'freecad-body-stock-turned.json','freecad-body-stock.stl')}
            # Separate old seeded-route regression for the WORLD helper. The
            # original frame/carrier support is not counted as a new feature.
            asset=root/'seed-original.stl';shutil.copyfile(examples/'freecad-body-stock.stl',asset)
            seeded=json.loads((examples/'freecad-body-stock-turned.json').read_text())
            seeded['nodes'][0]['options']['file']=str(asset)
            seeded['measurements']=[{'id':'finalCentre','node':'cut','quantity':'centreOfMass'},
                                    {'id':'intermediateCentre','node':'seed','quantity':'centreOfMass'}]
            seedjob=root/'seeded-world-regression'
            checked('existing-seeded-WORLD-helper-regression',lambda:registry.run(seeded,seedjob,locations=locations))
            expected_local=[3+math.cos(math.radians(31))*10-math.sin(math.radians(31))*6,
                            4+math.sin(math.radians(31))*10+math.cos(math.radians(31))*6,7.5]
            seed_frame=seeded['nodes'][1]['options']['frame'];seed_expected=apply(matrix(seed_frame),expected_local)
            values=json.loads((seedjob/'measurements.json').read_text())['measurements']
            near(values['finalCentre']['value'],seed_expected);near(values['intermediateCentre']['value'],seed_expected)
            checked('existing-seeded-fresh-verify',lambda:registry.verify(seedjob))
            producers={};states={};report['sourceStates']=states;report['sourceProjects']={}
            for name,filename in [('parametered','freecad-placed-body.json'),('attached','freecad-placed-body-attached.json'),('multiple','freecad-placed-bodies.json')]:
                authored=json.loads((examples/filename).read_text());path=root/('producer-'+name)
                checked('build-'+name,lambda:registry.run(authored,path,locations=locations))
                checked('verify-'+name,lambda:registry.verify(path));producers[name]=path
                receipt=json.loads((path/'verification.json').read_text())
                report['sourceProjects'][name]={'authoredSha256':file_digest(path/'authored.json'),
                    'constructedNativeSha256':file_digest(path/'model.FCStd'),'runtime':receipt['runtime']}
                check_shape(receipt['bodyLocalExportEvidence']['shape'],local())
                for representation in ('native','step'):check_shape(receipt['exportEvidence'][representation],placed(matrix(BODY)))
                measured=json.loads((path/'measurements.json').read_text())['measurements']
                near(measured['featureCentre']['value'],placed(matrix(BODY))['centreOfMass'])
                near(measured['featureBounds']['value'],placed(matrix(BODY))['bounds'])
                near(measured['intermediateCentre']['value'],apply(matrix(BODY),[6.5,4,5]))
                near(measured['intermediateBounds']['value'],placed(matrix(BODY))['bounds'])
                assert measured['worldEdges']['value']==4
                near(measured['worldEdgeLength']['value'],28)
                report['checks'][name+'-world-STL']=inspect_stl(path/'model.stl',BODY)
                # Force a meaningful wrong-frame discriminator, with identical
                # bytes and volume: an inverse using a different Body must fail.
                try:inspect_stl(path/'model.stl',CHANGED_BODY)
                except AssertionError:pass
                else:raise AssertionError('Wrong STL frame was not detected')
                current=root/('saves-'+name);current.mkdir();baseline=None;states[name]=[]
                for member in ('plan.json','sources.json','model.FCStd'):shutil.copyfile(path/member,current/member)
                for step in range(1,4):
                    checked('save-'+name+'-'+str(step),lambda:worker(current,'part_reference_native','resave',runtime,executable,body=True))
                    candidate=current/'resaved';baseline=body_reference_lifecycle(candidate,baseline)
                    states[name].append({'step':step,'sha256':file_digest(candidate/'model.FCStd')})
                    if step<3:
                        for member in ('plan.json','sources.json'):shutil.copyfile(current/member,candidate/member)
                        current=candidate
                shutil.copyfile(candidate/'model.FCStd',path/'model.FCStd')
                receipt['artifacts'][2]['sha256']=file_digest(path/'model.FCStd')
                atomic_json(path/'verification.json',receipt);finalise(path)
                checked('third-save-public-'+name,lambda:registry.verify(path))
                report['sourceProjects'][name]['savedNativeSha256']=file_digest(path/'model.FCStd')
            alternate=root/'alternate';checked('different-valid-bore-producer',lambda:registry.run(document(bore_x=-3),alternate,locations=locations))
            alt=json.loads((alternate/'verification.json').read_text())['bodyLocalExportEvidence']['shape']
            for key in ('volume','area','bounds'):near(alt[key],local()[key])
            assert abs(alt['centreOfMass'][1]-local()['centreOfMass'][1])>.1
            request=[{'id':name,'file':str(path/'model.FCStd'),'sha256':file_digest(path/'model.FCStd'),'body':'N0',
                      'witnessPoints':[[6.5,7,7],[6.5,1,7]]} for name,path in {**producers,'alternate':alternate}.items()]
            atomic_json(root/'frame-sources.json',request);checked('actual-saved-source-observer',lambda:native(root,'inspect_parts',runtime,executable))
            observed=json.loads((root/'frame-sources-result.json').read_text())['parts']
            for name in producers:
                assert observed[name]['witnesses']==[False,True]
                for stage in ('before','after'):
                    bodies=observed[name][stage];assert set(bodies)==({'N0','N5'} if name=='multiple' else {'N0'})
                    check_shape(bodies['N0']['local'],local());check_shape(bodies['N0']['world'],placed(matrix(BODY)))
                    near(bodies['N0']['placement'],flat(matrix(BODY)))
                    if name=='multiple':
                        other=bodies['N5'];near(other['placement'],flat(matrix(OTHER_BODY)))
                        check_shape(other['local'],{'volume':45*math.pi,'area':48*math.pi,'centreOfMass':[2,3,6.5],'bounds':[-1,5,0,6,4,9]})
                        expected_centre=apply(matrix(OTHER_BODY),[2,3,6.5]);near(other['world']['centreOfMass'],expected_centre)
            assert observed['alternate']['witnesses']==[True,False]
            doc=assembly(producers);pure=copy.deepcopy(doc)
            pure['parts']=pure['parts'][:1];pure['components']=[c for c in pure['components'] if c['id'] in ('fixed','again')]
            pure['joints']=[j for j in pure['joints'] if j['id']=='duplicate']
            purejob=root/'pure';checked('pure-configured-private-GUI',lambda:registry.run(pure,purejob,locations=locations))
            checked('generic-ten-refreshed-guards',lambda:qualify_guards(purejob,root/'guards-generic',locations))
            checked('four-frame-authority-guards',lambda:qualify_frame_guards(purejob,alternate/'model.FCStd',root/'guards-frame'))
            envelope={'version':'schemaxis.workflow/1','execution':{'maxWorkers':1,'cpus':2,'memoryMB':3072,'gpus':0},
                      'operations':[{'id':'assembly','document':doc}]}
            atomic_json(root/'workflow-authored.json',envelope);wf=root/'workflow'
            result=checked('mixed-workflow-private-GUI',lambda:workflow.execute(envelope,wf,locations=locations))
            job=Path(result['jobs'][0]['directory']);report['assemblyJob']=str(job)
            receipt=json.loads((job/'verification.json').read_text())
            for value in receipt['snapshots'].values():check_components(value)
            checked('aggregate-standalone120',lambda:registry.verify(job));checked('workflow-public-verify',lambda:workflow.verify(wf))
            before=file_digest(job/'model.FCStd');private=root/'edited-copy';private.mkdir()
            for member in ('model.FCStd','plan.json','built.json'):shutil.copyfile(job/member,private/member)
            for i,request in enumerate([{'thickness':9},{'bodyFrame':CHANGED_BODY},{}],1):
                request['receipt']='frame-edit-'+str(i)+'.json';atomic_json(private/'frame-request.json',request)
                checked('copy-edit-fresh-process-'+str(i),lambda:native(private,'inspect_copy',runtime,executable))
                value=json.loads((private/request['receipt']).read_text())
                for key in ('recomputed','after'):check_components(value[key],9,BODY if i==1 else CHANGED_BODY)
                if i==3:check_components(value['before'],9,CHANGED_BODY)
            assert file_digest(job/'model.FCStd')==before
            newer=root/'updated-typed-frame';checked('updated-typed-layout-new-run',lambda:registry.run(document(thickness=9,body_frame=CHANGED_BODY),newer,locations=locations))
            value=json.loads((newer/'verification.json').read_text())
            for representation in ('native','step'):check_shape(value['exportEvidence'][representation],placed(matrix(CHANGED_BODY),9))
            moves=[]
            try:
                for path in producers.values():
                    hidden=path.with_name(path.name+'.retired');path.rename(hidden);moves.append((hidden,path))
                checked('whole-producer-retired-standalone',lambda:registry.verify(job))
                checked('whole-producer-retired-workflow',lambda:workflow.verify(wf))
                reused=checked('whole-producer-retired-resume',lambda:workflow.execute(envelope,wf,locations=locations,resume=True))
                assert reused['jobs'][0]['reused'] and file_digest(job/'model.FCStd')==before
            finally:
                for hidden,path in reversed(moves):hidden.rename(path)
            checked('all-restored-public',lambda:registry.verify(job))
            assert file_digest(job/'model.FCStd')==before and source_digest('freecad')==pin
            assert {p.name:file_digest(p) for p in helpers}==hashes
            report['verified']=True
    finally:
        report['elapsedSeconds']=time.monotonic()-start;atomic_json(root/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad',required=True,type=Path);parser.add_argument('--freecad-gui',type=Path)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--examples-directory',type=Path,default=EXAMPLES)
    args=parser.parse_args()
    print(json.dumps({'verified':qualify(args.output_directory,args.freecad,args.freecad_gui,examples=args.examples_directory)['verified']}))


if __name__=='__main__':main()
