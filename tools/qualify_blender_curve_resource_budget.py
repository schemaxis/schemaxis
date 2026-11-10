"""Render-context curve sampling is bounded before procedural attachment."""
import argparse,json
from pathlib import Path
from qualify_blender_geometry_resources import base
from qualify_blender_mesh_data import close,native,production
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.errors import SchemaxisError
from blender_tamper import qualify


def fixture(blender,path,count,preview,render,font=False,animated=False):
    setup="c=bpy.data.curves.new('Sample','FONT');c.body='S'*"+str(count)+"\n" if font else "c=bpy.data.curves.new('Sample','CURVE');c.dimensions='3D';s=c.splines.new('BEZIER');s.bezier_points.add("+str(count-1)+")\nfor i,p in enumerate(s.bezier_points):\n p.co=(2*i,0,0);p.handle_left_type='FREE';p.handle_right_type='FREE';p.handle_left=(2*i,2,0);p.handle_right=(2*i,2,0)\n"
    animation=f"c.render_resolution_u=1;c.keyframe_insert(data_path='render_resolution_u',frame=1)\nc.render_resolution_u={render};c.keyframe_insert(data_path='render_resolution_u',frame=20)\nbpy.context.scene.frame_set(1)\n" if animated else ''
    capture="record={'currentRenderResolution':c.render_resolution_u,'previewResolution':c.resolution_u,'keys':[]}\n"
    if animated:capture="bpy.context.scene.frame_set(1);c.render_resolution_u=1\n"+capture+"record['keys']=[p.co.y for layer in c.animation_data.action.layers for strip in layer.strips for bag in strip.channelbags for f in bag.fcurves if f.data_path=='render_resolution_u' for p in f.keyframe_points]\nassert sorted(record['keys'])==[1,1024]\nassert record['currentRenderResolution']==1\n"
    native(blender,"import bpy,json\nfrom pathlib import Path\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"+setup+f"c.resolution_u={preview};c.render_resolution_u={render};c.bevel_depth=.1;c.bevel_resolution=0;c.use_fill_caps=True\n"+animation+"o=bpy.data.objects.new('Sample',c);bpy.context.scene.collection.objects.link(o)\n"+capture+f"bpy.ops.wm.save_as_mainfile(filepath={str(path)!r})\nPath({str(path.with_suffix('.json'))!r}).write_text(json.dumps(record))\n")
    return json.loads(path.with_suffix('.json').read_text())


def consumer(source):
    d=base('collectionInfo');s=d['production'];s['objects']=s['objects'][1:];s['assets']=[{'id':'library','file':str(source),'format':'blend'}];s['geometryResources']=[{'id':'selected','kind':'asset','asset':'library'}];return d


def render_counts(blender,project,output):
    # A fixed trusted diagnostic engine receives a real RENDER depsgraph. It
    # measures actual evaluated geometry without expensive image shading and
    # never saves or alters the accepted project bytes.
    code='import bpy,json\nfrom pathlib import Path\n'+f'bpy.ops.wm.open_mainfile(filepath={str(project)!r},use_scripts=False)\n'+'''record={}
o=bpy.data.objects['target'];d=bpy.context.evaluated_depsgraph_get();e=o.evaluated_get(d);m=e.to_mesh();record.update(viewportMode=d.mode,viewportVertices=len(m.vertices));e.to_mesh_clear()
class CountEngine(bpy.types.RenderEngine):
 bl_idname='SCHEMAXIS_CURVE_COUNT';bl_label='Trusted curve count diagnostic';bl_use_preview=False
 def render(self,depsgraph):
  e=o.evaluated_get(depsgraph);m=e.to_mesh();record.update(renderMode=depsgraph.mode,renderVertices=len(m.vertices),renderFaces=len(m.polygons));e.to_mesh_clear()
  result=self.begin_result(0,0,4,4);result.layers[0].passes['Combined'].rect=[[0,0,0,1]]*16;self.end_result(result)
bpy.utils.register_class(CountEngine);s=bpy.context.scene;s.render.engine=CountEngine.bl_idname;s.render.resolution_x=4;s.render.resolution_y=4;s.render.resolution_percentage=100
bpy.ops.render.render()
'''+f'Path({str(output)!r}).write_text(json.dumps(record))\n'
    native(blender,code);return json.loads(output.read_text())


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False);cases=[];refusals=[]
    small=out/'small.blend';fixture(a.blender,small,2,8,128)
    result=run(consumer(small),out/'small-render-resolution',executable=a.blender,timeout=180);assert verify(out/'small-render-resolution')['verified'];sample=production(out/'small-render-resolution')['samples'][0]['objects']['target'];close(sample['bounds'],[3.9,6.1,1,2.6,-.1,.1]);assert sample['vertices']==44,sample
    counts=render_counts(a.blender,out/'small-render-resolution/0000.blend',out/'render-counts.json');assert counts['viewportMode']=='VIEWPORT' and counts['renderMode']=='RENDER' and counts['viewportVertices']==44 and 516<=counts['renderVertices']<=4096,counts
    assert verify(out/'small-render-resolution')['verified']
    cases.append({'case':'small-curved-native-source-render128','result':result,'literalViewportBounds':[3.9,6.1,1,2.6,-.1,.1],'literalViewportVertices':44,'renderCountMinimum':516,'conservativeCountMaximum':4096,'actualNativeCounts':counts})
    smallfont=out/'small-font.blend';fixture(a.blender,smallfont,1,1,8,font=True)
    result=run(consumer(smallfont),out/'small-font-render-resolution',executable=a.blender,timeout=180);assert verify(out/'small-font-render-resolution')['verified'];sample=production(out/'small-font-render-resolution')['samples'][0]['objects']['target'];close(sample['bounds'][4:],[-.1,.1])
    counts=render_counts(a.blender,out/'small-font-render-resolution/0000.blend',out/'font-render-counts.json');assert counts['viewportMode']=='VIEWPORT' and counts['renderMode']=='RENDER' and counts['viewportVertices']<counts['renderVertices']<=65536,counts
    cases.append({'case':'small-curved-builtin-font-render8','result':result,'literalBevelZ':[-.1,.1],'actualNativeCounts':counts,'conservativeCountMaximum':65536})
    for label,count,preview,render,font,animated in [('curve-render-over-budget',1024,1,1024,False,False),('curve-later-render-key-over-budget',1024,1,1024,False,True),('font-render-over-budget',100,1,1024,True,False)]:
        source=out/(label+'.blend');source_values=fixture(a.blender,source,count,preview,render,font,animated)
        try:run(consumer(source),out/label,executable=a.blender,timeout=180)
        except SchemaxisError as error:
            assert error.fault.code=='RESOURCE_BUDGET_EXCEEDED',error.fault.to_dict();assert error.fault.observed['estimatedVertices']>2000000,error.fault.to_dict();refusals.append({'case':label,'sourceValues':source_values,'fault':error.fault.to_dict()})
        else:raise AssertionError(label+' unexpectedly admitted unbounded render tessellation')
    attacks=qualify(a.blender,[('curve',out/'small-render-resolution'),('font',out/'small-font-render-resolution')],{'unsampledRenderResolution':"bpy.data.objects['library--Sample'].data.render_resolution_u=64"})
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':cases,'refusals':refusals,'nativeTamper':attacks},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(cases),'refusals':len(refusals),'mutations':len(attacks['cases']),'unchangedSaves':len(attacks['controls'])}))

if __name__=='__main__':main()
