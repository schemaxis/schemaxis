#!/usr/bin/env python3
"""Qualify native editable Draft profiles, independent geometry and saved binding."""
import argparse,json
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.adaptor_delivery import source_digest
from schemaxis.configuration import location_context
from schemaxis.core.runners import Interpreter
from schemaxis.adaptors.freecad.process import SubprocessRunner
from freecad_draft_profile_cases import document,oracle,outline,xz_case,maximum_case,loft_case
from qualify_freecad_mesh import refresh
from qualify_freecad_draft_profile_guards import alterations,first_open,linked_workflow,reference_lifecycle

ROOT=Path(__file__).resolve().parents[1]


def native(directory,executable,function,request_name,request):
    assert function in ('inspect','edit')
    directory.mkdir(parents=True,exist_ok=True);atomic_json(directory/request_name,request)
    (directory/'trusted-runtime.zip').write_bytes(runtime_archive())
    script=('import sys\nsys.path[:0]=['+repr(str(directory/'trusted-runtime.zip'))+','+repr(str(ROOT/'tools'))+']\n'
            'from qualify_freecad_draft_profiles_native import '+function+'\n'
            'from schemaxis.native_boundary import execute_guarded\n'
            'execute_guarded('+function+','+repr(str(directory))+')\n')
    SubprocessRunner(Interpreter('freecad',executable),directory,timeout=240)(script)
    assert not (directory/'native-fault.json').exists(),(directory/'native-fault.json').read_text()


def unchanged_save(directory,target,executable,kind):
    source=target/'model.FCStd';expected=oracle(kind);states=[]
    files=('model.FCStd','verification.json','model.FCStd.metadata.json','publication-metadata.json')
    original={name:(target/name).read_bytes() for name in files}
    # Repeated saves must stabilize under the same two fully regenerated
    # reference states. Returning to the initial state must still verify.
    for index in range(1,4):
        stage=directory/str(index);saved=stage/'model.FCStd'
        native(stage,executable,'edit','edit-request.json',{'id':'unchanged','source':str(source),'sha256':file_digest(source),
            'output':'bracket' if kind=='L' else 'stock','target':str(saved),'mode':'save','before':expected,'after':expected})
        try:
            (target/'model.FCStd').write_bytes(saved.read_bytes());refresh(target)
            assert registry.verify(target)['verified']
            states.append({'save':index,'sha256':file_digest(saved),'native':json.loads((stage/'unchanged.json').read_text())})
        finally:
            for name,payload in original.items():(target/name).write_bytes(payload)
        assert registry.verify(target)['verified'];source=saved
    return {'verified':True,'states':states}


def edits(directory,target,executable,kind):
    source=target/'model.FCStd';before=oracle(kind);records=[]
    for index,(mode,value,after) in enumerate([
            ('points',outline(kind,True),oracle(kind,edited=True)),
            ('placement',[2,0,0] if kind=='L' else [23,-12,7],oracle(kind,edited=True,moved=True))],1):
        destination=directory/(kind+'-stage'+str(index)+'.FCStd')
        request={'id':kind+'-edit'+str(index),'source':str(source),'sha256':file_digest(source),
                 'output':'bracket' if kind=='L' else 'stock','target':str(destination),'mode':mode,
                 'value':value,'before':before,'after':after}
        native(directory,executable,'edit','edit-request.json',request)
        result=json.loads((directory/(request['id']+'.json')).read_text());assert result['verified']
        request.update(id=request['id']+'-reopen',source=str(destination),sha256=file_digest(destination),mode='reopen',before=after)
        native(directory,executable,'edit','edit-request.json',request)
        reopened=json.loads((directory/(request['id']+'.json')).read_text());assert reopened['verified'] and reopened['pid']!=result['pid']
        records.append({'edit':result,'reopen':reopened});source=destination;before=after
    return records


def mesh_regression(directory,seed,executable):
    """Replay retained Mesh packets against the current full reconstruction.

    Their construction remains historical; public verification regenerates the
    complete graph now, and a separate native worker checks physical geometry.
    """
    from qualify_freecad_mesh import native as mesh_native,oracle as bracket_oracle
    from freecad_mesh_cases import cavity_oracle
    requests=[]
    for label in ('bracket','variant','cavity'):
        target=Path(seed)/label;assert registry.verify(target)['verified']
        requests.append({'id':label,'file':str(target/'model.FCStd'),'sha256':file_digest(target/'model.FCStd'),
            'step':str(target/'model.step'),'output':'casting' if label=='cavity' else 'bracket',
            'oracle':cavity_oracle() if label=='cavity' else bracket_oracle(label=='variant')})
    mesh_native(directory,executable,'inspect','inspect-request.json',{'cases':requests})
    result=json.loads((directory/'independent.json').read_text());assert result['verified']
    return {'historicalConstructionSeed':str(seed),'currentFullReconstruction':True,'independent':result}


def qualify(directory,executable,gui,mesh_seed=None):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'tools':{p.name:file_digest(p) for p in
        [Path(__file__),ROOT/'tools/qualify_freecad_draft_profile_guards.py',ROOT/'tools/qualify_freecad_draft_profiles_native.py',ROOT/'tools/freecad_draft_profile_cases.py']},'checks':{}}
    cases=[('bracket','L',False),('clockwise','L',True),('turned','U',False)]
    try:
        with location_context({'freecad':executable,'freecad_gui':gui}):
            # Admit every independent fixture before spending any native work.
            for doc in [document(),document(clockwise=True),document('U'),xz_case()[0],maximum_case()[0],loft_case()[0]]:
                registry.plan(doc)
            for label,kind,clockwise in cases:
                result=registry.run(document(kind,clockwise=clockwise),directory/label,locations={'freecad':executable},timeout=300)
                assert result['verified'];report['checks'][label]={'verified':True,'volume':result['volumeMM3']};atomic_json(directory/'report.json',report)
            requests=[{'id':label,'file':str(directory/label/'model.FCStd'),'sha256':file_digest(directory/label/'model.FCStd'),
                       'step':str(directory/label/'model.step'),'output':'bracket' if kind=='L' else 'stock','oracle':oracle(kind)} for label,kind,_ in cases]
            native(directory/'independent',executable,'inspect','inspect-request.json',{'cases':requests})
            report['checks']['independent']=json.loads((directory/'independent/independent.json').read_text())
            extra=[]
            for label,(doc,expected) in [('xz',xz_case()),('maximum',maximum_case()),('loft',loft_case())]:
                result=registry.run(doc,directory/label,locations={'freecad':executable},timeout=300);assert result['verified']
                report['checks'][label]={'verified':True,'volume':result['volumeMM3']}
                extra.append({'id':label,'file':str(directory/label/'model.FCStd'),'sha256':file_digest(directory/label/'model.FCStd'),
                    'step':str(directory/label/'model.step'),'output':'stock','oracle':expected})
            native(directory/'extra-independent',executable,'inspect','inspect-request.json',{'cases':extra})
            report['checks']['extraIndependent']=json.loads((directory/'extra-independent/independent.json').read_text())
            for label,kind,_ in (cases[0],cases[2]):
                report['checks'][label+'UnchangedSave']=unchanged_save(directory/(label+'-unchanged'),directory/label,executable,kind)
                report['checks'][label+'Edits']=edits(directory/'edits',directory/label,executable,kind)
                atomic_json(directory/'report.json',report)
            from zipfile import ZipFile
            with ZipFile(directory/'edits/L-stage1.FCStd') as archive:replacement=archive.read('N0.Shape.brp')
            report['checks']['savedGuards']=alterations(directory/'bracket',directory/'bracket-unchanged/1/model.FCStd',replacement)
            atomic_json(directory/'report.json',report)
            from qualify_freecad_mesh import lifecycle
            report['checks']['deadlineCancellation']=lifecycle(directory,directory/'bracket')
            atomic_json(directory/'report.json',report)
            report['checks']['referenceDeadlineCancellation']=reference_lifecycle(directory,directory/'bracket',directory/'bracket-unchanged/1/model.FCStd')
            atomic_json(directory/'report.json',report)
            report['checks']['firstOpen']=first_open(directory/'first-open',directory/'bracket',gui)
            atomic_json(directory/'report.json',report)
            report['checks']['workflow']=linked_workflow(directory,document(),{'freecad':executable,'freecad_gui':gui})
            if mesh_seed is not None:report['checks']['meshRegression']=mesh_regression(directory/'mesh-regression',mesh_seed,executable)
            assert report['sourceDigest']==source_digest('freecad'),'source changed during Draft qualification'
            report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True);parser.add_argument('--gui-executable',required=True);parser.add_argument('--mesh-regression-seed')
    args=parser.parse_args();print(json.dumps(qualify(args.directory,args.executable,args.gui_executable,args.mesh_regression_seed),indent=2))
