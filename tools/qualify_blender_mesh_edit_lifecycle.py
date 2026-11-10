"""Enclosure physical handoff, post-edit morphs and native edit/adopt lifecycle."""
import argparse
import copy
import json
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.adaptors.blender.production_outputs import file_geometry
from schemaxis.errors import SchemaxisError
from qualify_blender_mesh_data import close,native,production
from qualify_blender_mesh_edits import document,panel,stage,signed_volume


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[1];results=[]
    enclosure=json.loads((root/'examples/schemaxis/blender-mesh-editing.json').read_text())
    directory=out/'enclosure';result=run(enclosure,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];observed=production(directory);objects=observed['samples'][0]['objects'];close(objects['housing']['bounds'],[-20,20,-15,15,0,20]);close(objects['lid']['bounds'],[-20,20,-15,15,27,30]);close([signed_volume(g['geometry']) for g in observed['meshEdits']],[8088,3600]);assert [(len(g['geometry']['vertices']),len(g['geometry']['faces'])) for g in observed['meshEdits']]==[(16,14),(8,6)]
    metrics=file_geometry(directory/'0000-export-enclosure.glb','glb');close(metrics['bounds'],[-.02,.02,-.015,.015,0,.03]);assert abs(metrics['signedVolume']-0.000011688)<1e-10,metrics
    results.append({'case':'enclosure-scientific-field-physical-GLB','result':result,'literalVolumesMM3':[8088,3600],'literalPhysicalBoundsMetres':[-.02,.02,-.015,.015,0,.03],'parsedGeometry':metrics})
    d=document(panel(),[stage('extrudeFaces',offset=[0,0,2],keepBase=True)]);s=d['production'];s.update(frameStart=1,frameEnd=11,currentFrame=6,shapeKeys=[{'object':'part','keys':[{'id':'lift','offsets':[{'vertices':[4,5,6,7],'offset':[0,0,2]}]}]}],clips=[{'id':'lift','tracks':[{'target':'surface','channel':'shapeValue','shape':'lift','keys':[{'frame':1,'value':0},{'frame':11,'value':1}]}]}],layers=[{'id':'lift','clip':'lift','bindings':[{'target':'surface','object':'part'}]}])
    directory=out/'post-edit-morph';result=run(d,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];samples={s['frame']:s for s in production(directory)['samples']}
    for frame,z in ((1,2),(6,3),(11,4)):close(samples[frame]['objects']['part']['bounds'],[0,2,0,2,0,z])
    results.append({'case':'morph-counts-use-extruded-topology','result':result,'literalFrameTopZ':[[1,2],[6,3],[11,4]]})
    # Native edits are adopted as new inputs. Existing original-run artifacts
    # stay intact; the editable copy has independently known changed bounds.
    source=out/'hand-edited.blend';native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"enclosure"/"0000.blend")!r},use_scripts=False)\n'+"m=bpy.data.objects['housing'].data;m.vertices[0].co.x-=1;m.update()\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n')
    d={'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'units':'millimetres','assets':[{'id':'adopted','file':str(source),'format':'blend','sourceUnits':'millimetres'}]}}
    directory=out/'adopted';result=run(d,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];sample=production(directory)['samples'][0]['objects']['adopted'];close(sample['bounds'],[-21,20,-15,15,0,30]);results.append({'case':'manual-native-edit-adopted-new-source','result':result,'literalBoundsMM':[-21,20,-15,15,0,30]})
    missing=source.with_suffix('.held');source.rename(missing)
    try:
        native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(directory/"0000.blend")!r},use_scripts=False)\n'+"assert bpy.data.objects['adopted--housing'].data.attributes.get('temperature') is not None\nassert bpy.data.objects['adopted--housing'].data.uv_layers.get('Label') is not None\nassert min(v.co.x for v in bpy.data.objects['adopted--housing'].data.vertices)==-21\n")
        try:verify(directory)
        except SchemaxisError as error:refusal=error.fault.to_dict();assert error.fault.code in ('VERIFICATION_FAILED','RESOURCE_NOT_FOUND'),refusal
        else:raise AssertionError('receipt accepted a missing original source')
    finally:missing.rename(source)
    assert verify(directory)['verified'];results.append({'case':'packed-reopen-original-absence-receipt-refusal-restoration','packedFieldsAndUVRetained':True,'originalAbsenceFault':refusal,'restoredReceiptVerified':True})
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
