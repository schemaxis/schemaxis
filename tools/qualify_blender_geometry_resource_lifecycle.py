"""Literal rotated/scaled frames and edited native resource-project adoption."""
import argparse,json,math,shutil
from schemaxis.errors import SchemaxisError
from pathlib import Path
from qualify_blender_geometry_resources import base
from qualify_blender_mesh_data import close,native,production
from schemaxis.adaptors.blender.adaptor import run,verify


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True);results=[]
    def execute(label,d,bounds):
        r=run(d,out/label,executable=a.blender,timeout=180);assert r['verified'] and verify(out/label)['verified'];obs=production(out/label);close(obs['samples'][0]['objects']['target']['bounds'],bounds);assert obs['samples'][0]['objects']['target']['vertices']==3;results.append({'case':label,'literalBounds':bounds,'result':r});print(label+' PASS',flush=True)
    for space in ('ORIGINAL','RELATIVE'):
        for kind,reset in (('objectInfo',False),('collectionInfo',False),('collectionInfo',True)):
            d=base(kind,space,separate=reset,reset=reset);s=d['production'];s['objects'][0].update(rotation=[0,0,math.pi/2],scale=[2,3,1]);s['objects'][1].update(rotation=[0,0,math.pi/2],scale=[2,1,1]);
            # S*p={(10,3),(10,7),(7,3)}. C*p={(4,1),(4,5),(3,1)}.
            # C*S*p={(1,21),(-3,21),(1,15)}; RELATIVE cancels C.
            bounds=[3,4,1,5,0,0] if reset or kind=='objectInfo' and space=='ORIGINAL' else ([7,10,3,7,0,0] if space=='RELATIVE' else [-3,1,15,21,0,0])
            execute(kind+'-'+space+'-'+str(reset),d,bounds)
    source=out/'resource-source.blend';shutil.copy2(a.suite/'object-RELATIVE-False/0000.blend',source)
    def adopt(label,file):
        d={'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'assets':[{'id':'adopted','file':str(file),'format':'blend','location':[20,0,0]}]}}
        r=run(d,out/label,executable=a.blender,timeout=180);assert r['verified'] and verify(out/label)['verified'];results.append({'case':label,'result':r});return production(out/label)
    obs=adopt('adopted-relative',source);close(obs['samples'][0]['objects']['adopted']['bounds'],[30,32,3,4,0,0]);hidden=out/'original-source-hidden.blend';source.rename(hidden)
    # Public receipts guard original AND retained bytes. The editable native
    # project must still reopen when the original source is unavailable.
    try:
        try:verify(out/'adopted-relative')
        except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED'
        else:raise AssertionError('Missing original must invalidate its receipt')
        native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"adopted-relative/0000.blend")!r},use_scripts=False)\n'+"n=bpy.data.objects['adopted--target'].modifiers['schemaxis-geometry-copy'].node_group.nodes['source'];assert n.transform_space=='RELATIVE';assert n.inputs['Object'].default_value==bpy.data.objects['adopted--source'];assert len(bpy.data.objects['adopted--target'].evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices)==3\n")
    finally:hidden.rename(source)
    assert verify(out/'adopted-relative')['verified']
    edited=out/'edited-resource.blend'
    native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(a.suite/"object-RELATIVE-False/0000.blend")!r},use_scripts=False)\n'+"bpy.data.node_groups['copy'].nodes['source'].transform_space='ORIGINAL'\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(edited)!r})\n')
    obs=adopt('adopted-edited',edited);target=next(m for m in obs['assets'][0]['members'] if m['name']=='adopted--target');close(target['geometry']['bounds'],[4,6,1,2,0,0])
    native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"adopted-edited/0000.blend")!r},use_scripts=False)\n'+"n=bpy.data.objects['adopted--target'].modifiers['schemaxis-geometry-copy'].node_group.nodes['source'];assert n.transform_space=='ORIGINAL';assert n.inputs['Object'].default_value==bpy.data.objects['adopted--source']\n")
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results,'nativeReopenWithoutOriginalSource':True,'receiptRequiresOriginalSource':True},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
