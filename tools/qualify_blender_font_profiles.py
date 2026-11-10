"""Imported builtin-font profile dependencies share bounded resource admission."""
import argparse,json,math
from pathlib import Path
from qualify_blender_mesh_data import native,production,close
from qualify_blender_geometry_resources import base
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.errors import SchemaxisError


def source(blender,path,count):
    coordinates=[[-.1,-.05],[.1,-.05],[.1,.05],[-.1,.05]][::-1] if count==4 else [[.1*math.cos(-2*math.pi*i/count),.05*math.sin(-2*math.pi*i/count)] for i in range(count)]
    code='import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n'+f'coordinates={coordinates!r}\n'+'''p=bpy.data.curves.new('Section','CURVE');p.dimensions='2D';p.fill_mode='NONE';s=p.splines.new('POLY');s.points.add(len(coordinates)-1)
for point,co in zip(s.points,coordinates):point.co=(*co,0,1)
s.use_cyclic_u=True;o=bpy.data.objects.new('Section',p);bpy.context.scene.collection.objects.link(o)
c=bpy.data.curves.new('Glyph','FONT');c.body='S';c.resolution_u=1;c.render_resolution_u=0;c.bevel_resolution=0;c.bevel_mode='OBJECT';c.bevel_object=o;c.use_fill_caps=True
g=bpy.data.objects.new('Glyph',c);bpy.context.scene.collection.objects.link(g)
'''+f'bpy.ops.wm.save_as_mainfile(filepath={str(path)!r})\n';native(blender,code)


def consumer(path):
    d=base();s=d['production'];s['objects']=s['objects'][1:];s['assets']=[{'id':'source','file':str(path),'format':'blend'}];s['geometryResources']=[{'id':'selected','kind':'object','object':'source','sourceObject':'Glyph'}];return d


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False);cases=[]
    small=out/'small.blend';source(a.blender,small,4);directory=out/'small-profile';r=run(consumer(small),directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];sample=production(directory)['samples'][0]['objects']['target'];close(sample['bounds'][4:],[-.05,.05]);assert sample['vertices']>0 and sample['faces']>0,sample;cases.append({'case':'small-font-object-profile','result':r,'literalSectionZ':[-.05,.05],'observation':sample,'conservativeVertexUpperBound':65536})
    large=out/'large.blend';source(a.blender,large,1024)
    try:run(consumer(large),out/'large-profile-refusal',executable=a.blender,timeout=180)
    except SchemaxisError as error:
        assert error.fault.code=='RESOURCE_BUDGET_EXCEEDED' and error.fault.observed['estimatedVertices']>2000000,error.fault.to_dict();cases.append({'case':'font-profile-expansion-refusal','fault':error.fault.to_dict()})
    else:raise AssertionError('large font profile escaped conservative expansion admission')
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':cases},indent=2)+'\n');print(json.dumps({'status':'passed','positive':1,'refusal':1}))

if __name__=='__main__':main()
