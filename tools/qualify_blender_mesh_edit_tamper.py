"""Native mesh edits reject geometry/ownership attacks and forged base witnesses."""
import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from blender_tamper import qualify,NATIVE_GUARDS
from schemaxis.adaptors.blender.adaptor import _verify,plan,verify
from schemaxis.adaptors.blender.production import verify_snapshot
from schemaxis.adaptors.blender.production_verify import fresh_reopen
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError


def forged_source_witness(blender,directory):
    """Refresh every observed geometry companion, then forge only the old base.

    The attack deliberately passes deterministic host replay: moved original and
    extruded vertices agree with the forged source. The actual original/retained
    native source bytes stay unchanged. Only fresh trusted source reconstruction
    distinguishes that forgery from an admissible edited source.
    """
    directory=directory.absolute();paths=[directory/name for name in ('0000.blend','verification.json','reopened.json')];original={p:p.read_bytes() for p in paths};outcomes=[]
    with location_context({'blender':blender}):assert verify(directory)['verified']
    try:
        for attack in (False,True):
            for p,data in original.items():p.write_bytes(data)
            with tempfile.TemporaryDirectory(prefix='schemaxis-mesh-base-forgery-') as tmp:
                script=Path(tmp)/'mutate.py'
                script.write_text('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(paths[0])!r},use_scripts=False)\n'+("m=bpy.data.objects['adopted--plate'].data\nm.vertices[0].co.x+=.25\nm.vertices[4].co.x+=.25\nm.update()\n" if attack else '')+f'bpy.ops.wm.save_as_mainfile(filepath={str(paths[0])!r})\n')
                completed=subprocess.run([blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script)],capture_output=True,text=True,timeout=60)
                assert completed.returncode==0,(completed.stdout,completed.stderr)
            with location_context({'blender':blender}):observed=fresh_reopen(directory)
            if attack:
                observed['production'][0]['meshEditBaselines'][0]['geometry']['vertices'][0][0]+=.25
            receipt=json.loads(original[paths[1]])
            for state,snapshot,production in zip(receipt['states'],observed['states'],observed['production']):state.update(snapshot=snapshot,production=production)
            for artifact in receipt['artifacts']:
                if artifact['file']==str(paths[0]):artifact['sha256']=hashlib.sha256(paths[0].read_bytes()).hexdigest()
            paths[1].write_text(json.dumps(receipt,indent=2)+'\n');paths[2].write_text(json.dumps(observed,indent=2)+'\n')
            master,_,_=plan(json.loads((directory/'authored.json').read_text()))
            verify_snapshot(master.document['scenes'][0]['production'],receipt['states'][0]['production'],directory)
            fault=None
            with location_context({'blender':blender}):
                try:_verify(directory,require_result=True)
                except SchemaxisError as error:fault=error.fault
            if attack:
                assert fault and fault.code=='VERIFICATION_FAILED' and fault.message in NATIVE_GUARDS,fault
                outcomes.append({'case':'forged-original-source-witness','hostReplayAccepted':True,'allObservedCompanionsRefreshed':True,'originalAndRetainedInputsUnchanged':True,'fault':fault.to_dict()})
            else:
                assert fault is None,fault
                outcomes.append({'case':'unchanged-save-with-all-observed-companions-refreshed','verified':True,'hostReplayAccepted':True})
    finally:
        for p,data in original.items():p.write_bytes(data)
    return outcomes


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();reports=[]
    reports.append(qualify(a.blender,[('enclosure',a.suite/'enclosure-fields-uv')],{
        'editedVertex':"m=bpy.data.objects['part'].data;m.vertices[0].co.x+=.125;m.update()",
        'editedWinding':"m=bpy.data.objects['part'].data;b=bmesh.new();b.from_mesh(m);b.faces.ensure_lookup_table();b.faces[0].normal_flip();b.to_mesh(m);b.free()",
        'editedFaceShading':"m=bpy.data.objects['part'].data;m.polygons[0].use_smooth=True",
        'undeclaredField':"bpy.data.objects['part'].data.attributes.new('unrequested','FLOAT','POINT')",
        'undeclaredEdgeFlag':"bpy.data.objects['part'].data.edges[0].use_edge_sharp=True",
        'postEditUV':"bpy.data.objects['part'].data.uv_layers['Paint'].data[0].uv.x+=.125"},preamble='import bmesh'))
    reports.append(qualify(a.blender,[('bridge',a.suite/'bridge-oriented-loops')],{
        'missingBridgeFace':"m=bpy.data.objects['part'].data;b=bmesh.new();b.from_mesh(m);b.faces.ensure_lookup_table();bmesh.ops.delete(b,geom=[b.faces[-1]],context='FACES_ONLY');b.to_mesh(m);b.free()"},preamble='import bmesh'))
    reports.append(qualify(a.blender,[('cut',a.suite/'plane-cut-positive')],{
        'capPlaneVertex':"m=bpy.data.objects['part'].data;v=next(v for v in m.vertices if abs(v.co.z-1)<1e-5);v.co.z+=.2;m.update()"}))
    reports.append(qualify(a.blender,[('copy',a.suite/'instance-copy')],{'copyOwnership':"bpy.data.objects['replica'].data=bpy.data.objects['part'].data"}))
    reports.append(qualify(a.blender,[('shared',a.suite/'instance-shared')],{'sharedOwnership':"bpy.data.objects['replica'].data=bpy.data.objects['replica'].data.copy()"}))
    reports.append(qualify(a.blender,[('native-source',a.suite/'native-source-material-selection')],{'faceMaterial':"bpy.data.objects['adopted--plate'].data.polygons[0].material_index=0"}))
    result={'status':'passed','cases':[c for r in reports for c in r['cases']],'controls':[c for r in reports for c in r['controls']],'sourceWitnessAttack':forged_source_witness(a.blender,a.suite/'native-source-material-selection')}
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':'passed','mutations':len(result['cases']),'controls':len(result['controls']),'sourceWitnessControls':len(result['sourceWitnessAttack'])}))

if __name__=='__main__':main()
