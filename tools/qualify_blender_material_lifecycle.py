"""Edited linked-palette adoption, source authority and material lifecycle controls."""
import argparse,copy,hashlib,json,subprocess,threading
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify,_verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.captured_inputs import adopt
from schemaxis.dispatch import allocation
from schemaxis.errors import SchemaxisError
from schemaxis.workflow import execute
from schemaxis.studio_library import load_library,instantiate_item
from qualify_blender_material_assignments import fixture,COLOURS
from qualify_blender_render_policy import expected
from qualify_blender_image_preview import rgba
from qualify_blender_mesh_data import native


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--suite',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False);baseline=args.suite.absolute()/'linked-per-face-captured-images';blender=args.blender
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':hashlib.sha256(runtime_archive()).hexdigest(),'qualifierSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[]};target=out/'summary.json'
    def record(label,**values):report['checks'].append({'label':label,**values});target.write_text(json.dumps(report,indent=2)+'\n');print(label+' PASS',flush=True)
    def refused(call,codes):
        try:call()
        except SchemaxisError as exc:
            assert exc.fault.code in codes,exc.fault.to_dict();return exc.fault.to_dict()
        raise AssertionError('expected refusal')
    def pixels(directory,colours,points=[(11,16),(21,16),(43,16),(53,16)]):
        actual=rgba(directory,points);wanted=[expected(c,0) for c in colours]
        assert all(abs(a-b)<=1 for row,ref in zip(actual,wanted) for a,b in zip(row,ref)),(actual,wanted)
        return {'encodedRGBA':actual,'independentExpectedRGBA':wanted,'maximumByteError':1}
    try:
        with location_context({'blender':blender}):assert verify(baseline)['verified']
        edited=out/'edited-palette.blend'
        native(blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(baseline/"0000.blend")!r},use_scripts=False)\n'+"patch=bpy.data.objects['patch'];other=bpy.data.objects['other'];assert patch.data==other.data\nother.material_slots[0].material=bpy.data.materials['blue']\nassert [p.material_index for p in patch.data.polygons]==[0,1]\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(edited)!r})\n')
        pinned=adopt(edited,out/'adopted-input');report['adoption']=pinned
        d=copy.deepcopy(json.loads((baseline/'authored.json').read_text()));d['production']={'assets':[{'id':'editionSource','file':pinned['reference'],'format':'blend'}]}
        workflow={'version':'schemaxis.workflow/1','operations':[{'id':'edition','document':d}]};directory=out/'adopted-workflow'
        result=execute(workflow,directory,blender=blender,timeout=360);assert result['verified'];consumer=Path(result['jobs'][0]['directory'])
        record('native-object-palette-edit-adopted',**pixels(consumer,[COLOURS[n] for n in ('red','blue','blue','yellow')]))
        resumed=execute(workflow,directory,blender=blender,timeout=360,resume=True);assert resumed['verified'] and any(j.get('reused') for j in resumed['jobs'])
        record('unchanged-adopted-workflow-reused',result=resumed)
        # Explicit remap of one captured native part, without trusting source slot
        # names/order. The other linked owner is isolated by sharing:copy.
        remap=copy.deepcopy(d);p=remap['production'];p['materialGraphs']=copy.deepcopy(fixture()['production']['materialGraphs'])
        p['materialAssignments']=[{'id':'remap','kind':'layout','object':'editionSource','sourceObject':'patch','sharing':'copy',
            'slots':[{'id':'body','material':'green'},{'id':'label','material':'red'}],'defaultSlot':'body','regions':[{'slot':'label','selection':{'kind':'faceIndices','indices':[1]}}]}]
        remapped=execute({'version':'schemaxis.workflow/1','operations':[{'id':'remap','document':remap}]},out/'captured-part-explicit-remap',blender=blender,timeout=360)
        assert remapped['verified'];mapped=Path(remapped['jobs'][0]['directory'])
        with location_context({'blender':blender}):assert verify(mapped)['verified']
        record('captured-part-copy-explicit-remap',**pixels(mapped,[COLOURS[n] for n in ('green','red','blue','yellow')]))
        blend=consumer/'0000.blend';receipt=consumer/'verification.json';reopened=consumer/'reopened.json';saved={p:p.read_bytes() for p in (blend,receipt,reopened)};witness=out/'forged-source-fidelity.json'
        try:
            code='import bpy,json,sys\n'+f'sys.path.insert(0,{str(consumer/"runtime.zip")!r})\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+"root=bpy.data.objects['editionSource'];records=json.loads(root['schemaxisAssetMembers']);member=bpy.data.objects[next(r['name'] for r in records if r['sourceName']=='other')]\nmember.material_slots[0].material=member.material_slots[1].material\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+"from schemaxis.adaptors.blender.production_asset_snapshot import snapshot_asset_members\n"+f'open({str(witness)!r},"w").write(json.dumps(snapshot_asset_members(root)))\n'
            native(blender,code);fidelity=json.loads(witness.read_text());r=json.loads(saved[receipt]);next(a for a in r['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();r['states'][0]['production']['assets'][0]['fidelity']=fidelity;receipt.write_text(json.dumps(r));r=json.loads(saved[reopened]);r['production'][0]['assets'][0]['fidelity']=fidelity;reopened.write_text(json.dumps(r))
            with location_context({'blender':blender}):fault=refused(lambda:_verify(consumer),{'VERIFICATION_FAILED'})
            assert fault['message']=='fresh native production readback refused current project',fault
            record('coforged-palette-source-witness-refused',fault=fault)
        finally:
            for path,data in saved.items():path.write_bytes(data)
        with location_context({'blender':blender}):assert verify(consumer)['verified']
        record('restored-source-authority-positive')
        # Cancellation/deadline failures remain incomplete, with a fresh-run
        # recovery using the same finite material intent.
        recovery=fixture('workbench',True);cancel=threading.Event();cancel.set()
        with allocation({},cancel):fault=refused(lambda:run(recovery,out/'cancelled',executable=blender),{'RUNNER_CANCELLED'})
        assert json.loads((out/'cancelled/result.json').read_text())['verified'] is False;record('cancelled-material-run-incomplete',fault=fault)
        fault=refused(lambda:run(recovery,out/'timedout',executable=blender,timeout=.001),{'RUNNER_TIMED_OUT'})
        assert json.loads((out/'timedout/result.json').read_text())['verified'] is False;record('short-material-deadline-incomplete',fault=fault)
        recovered=out/'recovered';run(recovery,recovered,executable=blender,timeout=360)
        with location_context({'blender':blender}):assert verify(recovered)['verified']
        record('fresh-material-run-recovers',**pixels(recovered,list(COLOURS.values())))
        library=load_library('blender');starter=next(t for t in library['templates'] if t['id']=='material-assignments');value=instantiate_item(library,starter)
        run(value,out/'studio-starter',executable=blender,timeout=360)
        with location_context({'blender':blender}):assert verify(out/'studio-starter')['verified']
        colours=[g['viewportColour'] for g in value['production']['materialGraphs']]
        record('actual-studio-material-starter',**pixels(out/'studio-starter',colours,[(55,80),(105,80),(215,80),(265,80)]))
        report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
