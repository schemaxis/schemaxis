"""Whole-carrier, selected-prototype and per-part modifier resource compositions."""
import argparse,copy,json,struct
from pathlib import Path
from qualify_blender_geometry_resources import base
from qualify_blender_mesh_data import close,native,production
from schemaxis.adaptors.blender.adaptor import run,verify


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--blender',required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cad',type=Path,required=True);a=ap.parse_args();out=a.output.absolute();out.mkdir(parents=True);results=[]
    # Independent input JSON accessor/index counts, never native readback counts.
    data=a.cad.read_bytes();length=struct.unpack_from('<I',data,12)[0];gltf=json.loads(data[20:20+length]);cad_counts={}
    for n in gltf['nodes']:
        if 'mesh' in n:
            primitives=gltf['meshes'][n['mesh']]['primitives'];cad_counts[n['name']]=(sum(gltf['accessors'][q['attributes']['POSITION']]['count'] for q in primitives),sum(gltf['accessors'][q['indices']]['count']//3 for q in primitives))
    fixture=out/'nested.blend'
    native(a.blender,"import bpy\n"+"bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)\n"+"s=bpy.context.scene;s.name='ResourceSource'\nparts=bpy.data.collections.new('Parts');parts.instance_offset=(1,0,0)\nm=bpy.data.meshes.new('Shared');m.from_pydata([(0,0,0),(2,0,0),(0,1,0)],[],[(0,1,2)])\no=bpy.data.objects.new('prototype',m);o.location=(2,1,0);parts.objects.link(o)\n"+"for name,location in [('first',(10,0,0)),('second',(0,5,0))]:\n o=bpy.data.objects.new(name,None);o.instance_type='COLLECTION';o.instance_collection=parts;o.location=location;s.collection.objects.link(o)\n"+f"bpy.ops.wm.save_as_mainfile(filepath={str(fixture)!r})\n")
    def execute(label,d,bounds,vertices=3):
        r=run(d,out/label,executable=a.blender,timeout=180);assert r['verified'];assert verify(out/label)['verified'];obs=production(out/label);item=obs['samples'][0]['objects']['target'];close(item['bounds'],bounds)
        if vertices is not None:assert item['vertices']==vertices,(label,item)
        results.append({'case':label,'literalBounds':bounds,'vertices':item['vertices'],'result':r});print(label+' PASS',flush=True);(out/'summary.json').write_text(json.dumps({'status':'implementing','cases':results},indent=2)+'\n');return obs
    d=base();s=d['production'];s['objects']=s['objects'][1:];s['assets']=[{'id':'assembly','file':str(fixture),'format':'blend','location':[20,0,0]}];s['geometryResources']=[{'id':'selected','kind':'object','object':'assembly','sourceObject':'prototype'}];execute('native-prototype-original',d,[4,6,1,2,0,0])
    d=copy.deepcopy(d);s=d['production'];s['geometryGraphs'][0]['nodes'][0]['properties']['space']='RELATIVE';execute('native-prototype-relative',d,[2,4,1,2,0,0])
    d=base('collectionInfo');s=d['production'];s['objects']=s['objects'][1:];s['assets']=[{'id':'assembly','file':str(fixture),'format':'blend','location':[20,0,0]}];s['geometryResources']=[{'id':'selected','kind':'asset','asset':'assembly'}];execute('native-whole-asset',d,[25,37,2,8,0,0],6)
    # Whole-asset relative placement preserves both nested occurrences and offset.
    d=copy.deepcopy(d);d['production']['geometryGraphs'][0]['nodes'][0]['properties']['space']='RELATIVE';execute('native-whole-relative',d,[21,33,1,7,0,0],6)
    # Apply one mesh-local lift to the selected prototype, affecting both occurrences.
    d=copy.deepcopy(d);s=d['production'];s['geometryGraphs'].append({'id':'lift','nodes':[{'id':'in','kind':'input'},{'id':'move','kind':'setPosition','values':{'offset':[0,0,3]}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'move','socket':'geometry'}},{'from':{'node':'move','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]});s['geometryBindings'].append({'object':'assembly','sourceObject':'prototype','graph':'lift'});execute('native-part-modifier',d,[21,33,1,7,3,3],6)
    # Historical accepted physical CAD bytes are inputs; literal dimensions come
    # from authored40x30mm footprint, height20mm, floor3mm, quarterturn
    # and lid placement27mm, not this readback.
    d=base('collectionInfo',space='RELATIVE');s=d['production'];s['units']='millimetres';s['objects']=s['objects'][1:];s['assets']=[{'id':'cad','file':str(a.cad.absolute()),'format':'glb'}];s['geometryResources']=[{'id':'selected','kind':'asset','asset':'cad'}];obs=execute('cad-whole-asset',d,[-15,15,-20,20,0,30],sum(n[0] for n in cad_counts.values()));assert obs['samples'][0]['objects']['target']['faces']==sum(n[1] for n in cad_counts.values())
    # Resource alias selects the same member as scientific fields and per-part GN.
    d=base(space='RELATIVE');s=d['production'];s['units']='millimetres';s['objects']=s['objects'][1:];s['assets']=[{'id':'cad','file':str(a.cad.absolute()),'format':'glb'}];s['geometryResources']=[{'id':'selected','kind':'object','object':'cad','sourceObject':'housingView-exchange'}];s['meshData']=[{'object':'cad','sourceObject':'housingView-exchange','attributes':[{'name':'region','kind':'integer','mode':'constant','value':27}]}];obs=execute('cad-selected-field',d,[-15,15,-20,20,0,20],cad_counts['housingView-exchange'][0]);assert obs['samples'][0]['objects']['target']['faces']==cad_counts['housingView-exchange'][1];assert set(obs['meshData'][0]['attributes'][0]['values'])=={27}
    # Both members can receive different modifiers under one public asset root.
    d=copy.deepcopy(d);s=d['production'];s['geometryGraphs'].append({'id':'lift','nodes':[{'id':'in','kind':'input'},{'id':'move','kind':'setPosition','values':{'offset':[0,0,.001]}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'move','socket':'geometry'}},{'from':{'node':'move','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]});s['geometryBindings'] += [{'object':'cad','sourceObject':'housingView-exchange','graph':'lift'},{'object':'cad','sourceObject':'lidView-exchange','graph':'lift'}];execute('cad-parts-modified',d,[-15,15,-20,20,1,21],cad_counts['housingView-exchange'][0])
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
