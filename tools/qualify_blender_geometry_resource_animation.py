"""Global native topology envelopes admit small motion and refuse future expansion."""
import argparse,copy,json
from pathlib import Path
from qualify_blender_geometry_resources import base
from qualify_blender_mesh_data import close,native,production
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.errors import SchemaxisError


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True)
    native(a.blender,"import bpy\n"+"bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)\nm=bpy.data.meshes.new('triangle');m.from_pydata([(0,0,0),(2,0,0),(0,1,0)],[],[(0,1,2)]);o=bpy.data.objects.new('prototype',m);bpy.context.scene.collection.objects.link(o);mod=o.modifiers.new('copies','ARRAY')\nmod.count=2;mod.keyframe_insert(data_path='count',frame=1);mod.count=3;mod.keyframe_insert(data_path='count',frame=3)\nad=o.animation_data;curve=ad.action.layers[0].strips[0].channelbag(ad.action_slot).fcurves[0]\nfor k in curve.keyframe_points:k.interpolation='LINEAR'\nbpy.context.scene.frame_set(1)\n"+f"bpy.ops.wm.save_as_mainfile(filepath={str(out/'small.blend')!r})\n"+"curve.keyframe_points[-1].co.y=400\nbpy.context.scene.frame_set(1)\n"+f"bpy.ops.wm.save_as_mainfile(filepath={str(out/'later.blend')!r})\n"+"curve.keyframe_points[-1].co.y=2\nfor k in curve.keyframe_points:k.interpolation='BEZIER';k.handle_left_type='FREE';k.handle_right_type='FREE'\ncurve.keyframe_points[0].handle_right=(1.5,400);curve.keyframe_points[-1].handle_left=(2.5,400)\nbpy.context.scene.frame_set(2);assert 300<=mod.count<=301,mod.count\nbpy.context.scene.frame_set(1)\n"+f"bpy.ops.wm.save_as_mainfile(filepath={str(out/'overshoot.blend')!r})\n"+"o.animation_data_clear();driver=mod.driver_add('count').driver;driver.type='SCRIPTED';driver.expression='frame+2'\n"+f"bpy.ops.wm.save_as_mainfile(filepath={str(out/'driven.blend')!r})\n"+f"bpy.ops.wm.open_mainfile(filepath={str(out/'small.blend')!r},use_scripts=False)\n"+"o=bpy.data.objects['prototype'];ad=o.animation_data;action=ad.action;slot=ad.action_slot;track=ad.nla_tracks.new();strip=track.strips.new('topology',1,action);strip.action_slot=slot;ad.action=None\n"+f"bpy.ops.wm.save_as_mainfile(filepath={str(out/'nla.blend')!r})\n")
    d=base();s=d['production'];s['objects']=s['objects'][1:];s['assets']=[{'id':'assembly','file':str(out/'small.blend'),'format':'blend'}];s['geometryResources']=[{'id':'selected','kind':'object','object':'assembly','sourceObject':'prototype'}];s.update(frameStart=1,frameEnd=3,currentFrame=3)
    result=run(d,out/'small',executable=a.blender,timeout=180);assert result['verified'] and verify(out/'small')['verified'];obs=production(out/'small')['samples'][0]['objects']['target'];assert obs['vertices']==9;close(obs['bounds'],[4,10,1,2,0,0]);results=[{'case':'boundedAnimatedArray','vertices':9,'literalBounds':[4,10,1,2,0,0],'result':result}]
    huge=copy.deepcopy(d);s=huge['production'];s['currentFrame']=1;g=s['geometryGraphs'][0];g['nodes'].insert(1,{'id':'points','kind':'grid','values':{'xVertices':100,'yVertices':100}});g['nodes'].insert(2,{'id':'copies','kind':'instanceOnPoints'});g['links']=[{'from':{'node':'points','socket':'geometry'},'to':{'node':'copies','socket':'points'}},{'from':{'node':'source','socket':'geometry'},'to':{'node':'copies','socket':'instance'}},{'from':{'node':'copies','socket':'instances'},'to':{'node':'realise','socket':'geometry'}},{'from':{'node':'realise','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]
    refusals=[]
    for name,code in [('later','RESOURCE_BUDGET_EXCEEDED'),('overshoot','RESOURCE_BUDGET_EXCEEDED'),('driven','UNSUPPORTED_RESOURCE_TOPOLOGY'),('nla','UNSUPPORTED_RESOURCE_TOPOLOGY')]:
        refusal=copy.deepcopy(huge);refusal['production']['assets'][0]['file']=str(out/(name+'.blend'))
        try:run(refusal,out/name,executable=a.blender,timeout=180)
        except SchemaxisError as e:
            assert code in str(e.fault.to_dict()),e.fault.to_dict();refusals.append({'case':name,'fault':e.fault.to_dict()});print(name+' REFUSED',flush=True)
        else:raise AssertionError(name+' unexpectedly accepted')
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results,'refusals':refusals},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results),'refusals':len(refusals)}))

if __name__=='__main__':main()
