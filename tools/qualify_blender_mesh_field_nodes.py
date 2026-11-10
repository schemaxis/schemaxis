"""Typed mask and quaternion fields have independent procedural geometry effects."""
import argparse
import copy
import json
import math
from pathlib import Path
from qualify_blender_mesh_data import close,native,production
from schemaxis.adaptors.blender.adaptor import run


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output).absolute();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];baseline=json.loads((root/'examples/schemaxis/blender-mesh-fields.json').read_text());results=[]
    d=copy.deepcopy(baseline);d['production']['exports']=[];s=d['production'];s['meshData'][0]['attributes'].append({'name':'liftMask','kind':'boolean','domain':'POINT','mode':'sparse','default':False,'entries':[{'index':2,'value':True}]})
    g=s['geometryGraphs'][0];g['nodes'].append({'id':'mask','kind':'namedAttribute','properties':{'dataType':'BOOLEAN'},'values':{'name':'liftMask'}});g['links'].append({'from':{'node':'mask','socket':'attribute'},'to':{'node':'move','socket':'selection'}})
    r=run(d,out/'mask',executable=a.blender,timeout=180)
    # Independent native evaluated points: only the selected third vertex lifts.
    native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"mask"/"0000.blend")!r},use_scripts=False)\n'+"o=bpy.data.objects['panel'].evaluated_get(bpy.context.evaluated_depsgraph_get());m=o.to_mesh()\ntry:\n assert [tuple(v.co) for v in m.vertices]==[(0.,0.,0.),(40.,0.,0.),(40.,30.,4.),(0.,30.,0.)]\nfinally:o.to_mesh_clear()\n")
    results.append({'case':'booleanMaskGeometryEffect','result':r})
    d=copy.deepcopy(baseline);s=d['production'];s['exports']=[];s['meshData'][0]['attributes']=[{'name':'orientation','kind':'quaternion','domain':'POINT','mode':'constant','value':[math.sqrt(.5),0,0,math.sqrt(.5)]}]
    s['geometryGraphs']=[{'id':'deform','nodes':[{'id':'in','kind':'input'},{'id':'cube','kind':'cube','values':{'size':[4,2,1]}},{'id':'rotation','kind':'namedAttribute','properties':{'dataType':'QUATERNION'},'values':{'name':'orientation'}},{'id':'instances','kind':'instanceOnPoints'},{'id':'realise','kind':'realiseInstances'},{'id':'out','kind':'output'}],
        'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'instances','socket':'points'}},{'from':{'node':'cube','socket':'geometry'},'to':{'node':'instances','socket':'instance'}},{'from':{'node':'rotation','socket':'attribute'},'to':{'node':'instances','socket':'rotation'}},{'from':{'node':'instances','socket':'instances'},'to':{'node':'realise','socket':'geometry'}},{'from':{'node':'realise','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]}]
    r=run(d,out/'quaternion',executable=a.blender,timeout=180);obs=production(out/'quaternion');close(obs['samples'][0]['objects']['panel']['bounds'],[-1,41,-2,32,-.5,.5]);assert obs['samples'][0]['objects']['panel']['vertices']==32
    results.append({'case':'quaternionInstancesGeometryEffect','result':r,'literalBounds':[-1,41,-2,32,-.5,.5]})
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
