"""Qualify multi-Body history embedding, persistent references and native edits."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile

from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad.assembly_sources_saved import verify_saved
from schemaxis.adaptors.freecad.history_copy_verify import regenerate
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,runtime_archive
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner

ROOT=Path(__file__).resolve().parents[1]


def document(drilled=False,shelled=False):
    project=json.loads((ROOT/'examples/schemaxis/enclosure-manufacturing-rendering-workflow.json').read_text())
    result={key:copy.deepcopy(project[key]) for key in ('version','execution','definitions')}
    if drilled or shelled:
        model=json.loads((ROOT/'examples/schemaxis'/('freecad-shell-enclosure.json' if shelled else 'freecad-drilled-enclosure.json')).read_text())
        result['definitions']['partParameters']=model['parameters']
        result['definitions']['partHistory']=model['nodes']
    result['operations']=copy.deepcopy(project['operations'][:2])+[{'id':'assembly','document':{
        'version':'schemaxis.freecad.assembly/1',
        'parts':[{'id':'housingPart','source':{'$artifact':'housing','index':2},'mounts':{
            'base':{},'seam':{'position':[0,0,{'terms':{'height':1}}]},'spare':{'position':[80,0,0]}}},
            {'id':'lidPart','source':{'$artifact':'lid','index':2},'mounts':{'seam':{'position':[60,0,0]}}}],
        'components':[{'id':'housing','part':'housingPart'},{'id':'lid','part':'lidPart'},
                      {'id':'spareHousing','part':'housingPart'}],
        'grounded':'housing','joints':[
            {'id':'closure','type':'fixed','parent':{'component':'housing','mount':'seam'},
             'child':{'component':'lid','mount':'seam'}},
            {'id':'sparePlacement','type':'fixed','parent':{'component':'housing','mount':'spare'},
             'child':{'component':'spareHousing','mount':'base'}}]}}]
    return result


def near(actual,expected):
    assert math.isclose(actual,expected,rel_tol=1e-8,abs_tol=1e-7),(actual,expected)


def check_snapshot(snapshot,height):
    assert snapshot['badStates']=={} and snapshot['externalLinks']==[]
    components=snapshot['components'];volume=384*height+2448+60*math.pi
    for identity in ('housing','spareHousing'):near(components[identity]['shape']['volume'],volume)
    assert components['housing']['linked']==components['spareHousing']['linked']
    near(components['lid']['shape']['volume'],3*(1176-math.pi))
    for actual,expected in zip([components['lid']['matrix'][i] for i in (3,7,11)],[-60,0,height]):near(actual,expected)
    for actual,expected in zip([components['spareHousing']['matrix'][i] for i in (3,7,11)],[80,0,0]):near(actual,expected)


def native(directory,stage,request,executable):
    filename='edit-request.json' if stage=='edit_probe' else 'inspect-request.json'
    atomic_json(directory/filename,request)
    (directory/'trusted-runtime.zip').write_bytes(runtime_archive())
    script=('import sys\nsys.path.insert(0,'+repr(str(directory/'trusted-runtime.zip'))+')\n'
            'from schemaxis.adaptors.freecad.assembly_sources_native import '+stage+'\n'
            'from schemaxis.native_boundary import execute_guarded\n'
            'execute_guarded('+stage+','+repr(str(directory))+')\n')
    SubprocessRunner(Interpreter('freecad',executable),directory,timeout=120)(script)
    assert not (directory/'native-fault.json').exists()


def qualify(directory,executable,*,drilled=False,shelled=False):
    directory.mkdir(parents=True)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'drilled':drilled,'shelled':shelled,'checks':{}}
    try:
        result=workflow.execute(document(drilled,shelled),directory/'workflow',locations={'freecad':executable},timeout=300)
        assert workflow.verify(directory/'workflow')['verified']
        jobs={job['operation']:Path(job['directory']) for job in result['jobs']};assembly=jobs['assembly']
        prepared=json.loads((assembly/'plan.json').read_text());built=json.loads((assembly/'built.json').read_text())
        reopened=json.loads((assembly/'verification.json').read_text())
        check_snapshot(reopened['snapshots']['persisted'],20)
        assert len(prepared['parts'])==2 and all(sum(t=='PartDesign::Body' for t in p['source']['objects'].values())==2 for p in prepared['parts'])
        report['checks']['wholeMultiBodyHistoryAndSharedInstances']={'parts':2,'bodiesRetained':4,'instances':3,'housingVolumeMM3':10128+60*math.pi}
        checks=directory/'native-edits';checks.mkdir()
        for name in ('model.FCStd','built.json','plan.json'):shutil.copyfile(assembly/name,checks/name)
        edit_pids=[]
        for height in (22,24):
            native(checks,'edit_probe',{'part':'housingPart','parameter':'height','value':height,'output':'edited.FCStd'},executable)
            edit=json.loads((checks/'edit.json').read_text());edit_pids.append(edit['pid'])
            for stage in ('recomputed','solved','probed'):check_snapshot(edit['snapshots'][stage],height)
            native(checks,'inspect_copy',{'file':str(checks/'edited.FCStd'),'receipt':'reopened.json'},executable)
            inspected=json.loads((checks/'reopened.json').read_text());assert inspected['pid']!=edit['pid']
            for stage in ('persisted','solved'):check_snapshot(inspected['snapshots'][stage],height)
            shutil.copyfile(checks/'edited.FCStd',checks/'model.FCStd')
            atomic_json(checks/f'edit-{height}.json',edit);atomic_json(checks/f'reopen-{height}.json',inspected)
        assert len(set(edit_pids))==2
        report['checks']['parameterEditsAndFreshReopen']={'heightsMM':[22,24],'sharedHousingVolumesMM3':[10896+60*math.pi,11664+60*math.pi]}
        # Only the standalone assembly is opened with every producer/retained
        # input unavailable. Schemaxis provenance verification still requires
        # the original pinned producer artifacts.
        moved=directory/'standalone';moved.mkdir()
        for name in ('model.FCStd','built.json','plan.json'):shutil.copyfile(assembly/name,moved/name)
        hidden=directory/'workflow-hidden';(directory/'workflow').rename(hidden)
        try:
            native(moved,'inspect_copy',{'file':str(moved/'model.FCStd'),'receipt':'standalone.json'},executable)
        finally:hidden.rename(directory/'workflow')
        standalone=json.loads((moved/'standalone.json').read_text())
        for stage in ('persisted','solved'):check_snapshot(standalone['snapshots'][stage],20)
        report['checks']['nativeSourceRemoval']=True
        retained={p['id']:assembly/prepared['native']['retained'][p['id']] for p in prepared['parts']}
        original=(assembly/'model.FCStd').read_bytes();metadata=(assembly/'verification.json').read_bytes()
        with zipfile.ZipFile(assembly/'model.FCStd') as archive:members={n:archive.read(n) for n in archive.namelist()}
        table=members['StringHasher.Table.txt'];map_name=next(n for n in members if n.endswith('.Map.txt') and b'$#' in members[n])
        import re
        token=re.search(rb'\$#([0-9a-f]+)',members[map_name])[1]
        other=b'1' if token!=b'1' else b'2'
        mutations={
            'existingWrongName':{map_name:members[map_name].replace(b'$#'+token,b'$#'+other,1)},
            'nestedStringContent':{'StringHasher.Table.txt':table.replace(b'0:;SKT',b'0:;BAD',1)},
            'rootAlias':{map_name:re.sub(rb'v1\n\d+ PostfixCount',b'v1\n999999 PostfixCount',members[map_name],count=1)},
            'shadowExistingWrong':{'Document.xml':re.sub(rb'(shadow="[^\"]*?)#[0-9a-f]+',rb'\g<1>#1',members['Document.xml'],count=1)},
            'shadowAbsent':{'Document.xml':re.sub(rb'(shadow="[^\"]*?)#[0-9a-f]+',rb'\g<1>#fffffff',members['Document.xml'],count=1)},
            'shapePayload':{next(n for n in members if n.endswith('.brp') and members[n]):b''}}
        rejected={}
        try:
            with regenerate(assembly,prepared,retained,executable=executable) as oracle:
                for label,replacements in mutations.items():
                    assert all(members[n]!=value for n,value in replacements.items()),label
                    with zipfile.ZipFile(assembly/'model.FCStd','w',zipfile.ZIP_DEFLATED) as archive:
                        for name,value in members.items():archive.writestr(name,replacements.get(name,value))
                    changed=json.loads(metadata);digest=hashlib.sha256((assembly/'model.FCStd').read_bytes()).hexdigest()
                    changed['artifact']['sha256']=digest;changed['artifacts'][0]['sha256']=digest
                    atomic_json(assembly/'verification.json',changed)
                    try:verify_saved(prepared,assembly/'model.FCStd',built['renames'],retained,oracle)
                    except SchemaxisError as error:rejected[label]=error.fault.code
                    else:raise AssertionError('forged saved artifact accepted: '+label)
                # One full caller-facing verification also regenerates from
                # sources; refreshed digests cannot replace that evidence.
                replacement=mutations['existingWrongName']
                with zipfile.ZipFile(assembly/'model.FCStd','w',zipfile.ZIP_DEFLATED) as archive:
                    for name,value in members.items():archive.writestr(name,replacement.get(name,value))
                changed=json.loads(metadata);digest=hashlib.sha256((assembly/'model.FCStd').read_bytes()).hexdigest()
                changed['artifact']['sha256']=digest;changed['artifacts'][0]['sha256']=digest;atomic_json(assembly/'verification.json',changed)
                try:registry.verify(assembly)
                except SchemaxisError as error:rejected['fullRegistryExistingWrongName']=error.fault.code
                else:raise AssertionError('full verification accepted a wrong existing name')
        finally:
            (assembly/'model.FCStd').write_bytes(original);(assembly/'verification.json').write_bytes(metadata)
        assert registry.verify(assembly)['verified']
        report['checks']['refreshedDigestAttacks']=rejected
        resumed=workflow.execute(document(drilled,shelled),directory/'workflow',locations={'freecad':executable},timeout=300,resume=True)
        assert all(job['reused'] for job in resumed['jobs'])
        report['checks']['workflowReuse']=True
        assert source_digest('freecad')==report['sourceDigest'],'source changed during qualification'
        report['verified']=True
        return report
    finally:atomic_json(directory/'report.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True,type=Path)
    parser.add_argument('--executable',required=True);family=parser.add_mutually_exclusive_group()
    family.add_argument('--drilled',action='store_true');family.add_argument('--shelled',action='store_true');args=parser.parse_args()
    print(json.dumps(qualify(args.directory.absolute(),args.executable,drilled=args.drilled,shelled=args.shelled),indent=2))
