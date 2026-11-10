"""Captured-source reconstruction and display selector integrity acceptance."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tools'))
from qualify_blender_mesh_data import native
from blender_tamper import qualify
from schemaxis.adaptors.blender.adaptor import run,verify,_verify as verify_native
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output.absolute();out.mkdir(parents=True,exist_ok=False);source=out/'source.blend';blender=args.blender
def verified(directory):
    with location_context({'blender':blender}):return verify(directory)['verified']

code='import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n'+'''m=bpy.data.meshes.new('patch');m.from_pydata([[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],[],[[0,1,2,3]])
for name,colour in [('first',[.04,.09,.25,1]),('second',[.3,.05,.1,1])]:
 a=m.color_attributes.new(name,'FLOAT_COLOR','POINT')
 for point in a.data:point.color=colour
for name in ['firstUV','secondUV']:m.uv_layers.new(name=name)
m.uv_layers.active_index=0;m.uv_layers[1].active_render=True
m.color_attributes.active_color_index=0;m.color_attributes.render_color_index=1
o=bpy.data.objects.new('patch',m);bpy.context.scene.collection.objects.link(o)
o['partCode']=1000000;o['measurement']=1000000.125
'''+f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n';native(blender,code)
d={'version':'schemaxis.blender.production/1','size':[32,32],'cameras':[{'direction':[0,0,1],'up':[0,1,0]}],'render':{'threads':2,'renderer':{'kind':'workbench','lighting':{'kind':'flat'},'colourSource':{'kind':'attribute'},'antiAliasing':'OFF'},'colourManagement':{'view':{'kind':'standard'}}},'production':{'assets':[{'id':'asset','file':str(source),'format':'blend'}]}}
directory=out/'consumer';run(d,directory,executable=blender,timeout=360);assert verified(directory)
preamble="root=bpy.data.objects['asset'];mesh=next(o for o in root.instance_collection.all_objects if o.type=='MESH').data\n"
checks=qualify(blender,[('selectors-and-output',directory)],{'activeColour':'mesh.color_attributes.active_color_index=1','renderColour':'mesh.color_attributes.render_color_index=0','activeUV':'mesh.uv_layers.active_index=1','outputOverride':"s=bpy.context.scene.render.image_settings;s.color_management='OVERRIDE';s.view_settings.view_transform='Standard';s.view_settings.exposure=1",'surfaceMode':"bpy.context.scene.display.shading.type='WIREFRAME'"},preamble)
# Submitted asset signatures must not replace captured-source authority. Custom
# identifiers and metadata retain exact values/types even at large magnitudes.
blend=directory/'0000.blend';receipt=directory/'verification.json';reopened=directory/'reopened.json'
original={p:p.read_bytes() for p in [blend,receipt,reopened]};replacements=[]
for label,change in [('colour-payload',"for point in mesh.color_attributes['first'].data:point.color=(.6,.1,.2,1)"),
                     ('integer-value',"member['partCode']=1000001"),
                     ('integer-type',"member['partCode']=1000000.0"),
                     ('custom-float',"member['measurement']=1000000.126")]:
 current=out/(label+'-fidelity.json')
 try:
  code='import bpy,json,sys\n'+f'sys.path.insert(0,{str(directory/"runtime.zip")!r})\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+preamble+"member=next(o for o in root.instance_collection.all_objects if o.type=='MESH')\n"+change+'\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+'from schemaxis.adaptors.blender.production_asset_snapshot import snapshot_asset_members\n'+f'open({str(current)!r},"w").write(json.dumps(snapshot_asset_members(root)))\n';native(blender,code)
  fidelity=json.loads(current.read_text());r=json.loads(original[receipt]);next(a for a in r['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();r['states'][0]['production']['assets'][0]['fidelity']=fidelity;receipt.write_text(json.dumps(r,indent=2)+'\n');old=json.loads(original[reopened]);old['production'][0]['assets'][0]['fidelity']=fidelity;reopened.write_text(json.dumps(old,indent=2)+'\n')
  with location_context({'blender':blender}):
   try:verify_native(directory)
   except SchemaxisError as error:
    assert error.fault.code=='VERIFICATION_FAILED' and error.fault.message=='fresh native production readback refused current project',error.fault.to_dict();replacements.append({'label':label,'refusal':error.fault.to_dict()})
   else:raise AssertionError('changed data plus replacement signatures were accepted: '+label)
 finally:
  for p,data in original.items():p.write_bytes(data)
assert verified(directory)
import copy
compositions=[]
for edited in (False,True):
 variant=copy.deepcopy(d);variant['production']['meshData']=[{'object':'asset','sourceObject':'patch','sharing':'copy','activeColour':'first','renderColour':'first','attributes':[{'name':'first','kind':'colour','mode':'constant','value':[.2,.4,.1,1]}]}]
 if edited:variant['production']['meshEdits']=[{'object':'asset','sourceObject':'patch','sharing':'copy','dataPolicy':'discard','steps':[{'id':'move','kind':'transform','selection':{'kind':'all'},'translation':[.25,0,0]}]}]
 target=out/('authored-edits-and-fields' if edited else 'authored-fields');run(variant,target,executable=blender,timeout=360);assert verified(target);compositions.append({'case':target.name,'verified':True})
report={'status':'passed','nativeControls':checks,'replacedSignatureRefusals':replacements,'authoredCompositions':compositions};(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','mutations':len(checks['cases'])+len(replacements),'unchangedControls':len(checks['controls'])}))
