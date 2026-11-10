"""Current saved-render input authority, native pixels and unchanged-save controls."""
import argparse,ast,sys,json,hashlib,copy
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tools'))
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from schemaxis.publication_metadata import finalise,MANIFEST
from qualify_blender_imported_materials import native as unchecked_native
def native(executable,source):
 ast.parse(source,filename="generated-native.py",mode="exec")
 return unchecked_native(executable,source)
from qualify_blender_render_policy import document,settings
from schemaxis.png import read
from blender_surface_evidence import identity,verify_identity
parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
base=Path(__file__).resolve().parents[1];out=args.output.absolute();out.mkdir(parents=True,exist_ok=False);(out/'recipe.py').write_bytes(Path(__file__).read_bytes());exe=args.blender;report={'status':'running',**identity(out,exe),'checks':[]};trusted=out/'trusted-runtime.zip';trusted.write_bytes(runtime_archive())
def record(case,**v):
 report['checks'].append({'case':case,**v});(out/'report.json').write_text(json.dumps(report,indent=2));print(case,flush=True)
def public(packet):
 try:
  with location_context({'blender':exe}):return {'accepted':True,'value':verify(packet)}
 except SchemaxisError as e:return {'accepted':False,'fault':e.fault.to_dict()}
def case(label,d,mutation,rerender_suffix='',message='render context differs'):
 folder=out/label;folder.mkdir();packet=folder/'packet';run(d,packet,executable=exe,timeout=300);assert public(packet)['accepted']
 receipt=packet/'verification.json';blend=packet/'0000.blend';reopened=packet/'reopened.json';r=json.loads(receipt.read_text());png=Path(next(a['file'] for a in r['artifacts'] if a.get('kind')=='image'));w,h,before=read(png)
 saved={p:p.read_bytes() for p in [blend,receipt,reopened,packet/MANIFEST,*packet.glob('*.metadata.json')]}
 record(label+'-original',verified=True)
 if label=='latent-scene-gravity':
  samples=r['states'][0]['production']['samples'];z=next(v for v in samples if v['frame']==20)['objects']['box']['matrix'][2][3]
  analytic=5-.5*9.81*(19/24)**2;assert abs(z-analytic)<.08,(z,analytic)
  record('gravity-ballistic-reference',actualZ=z,analyticZ=analytic,maximumError=.08)
 code=f'import bpy\nbpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\nbpy.context.preferences.filepaths.save_version=0\nbpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'
 native(exe,code);value=json.loads(saved[receipt]);next(a for a in value['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();receipt.write_text(json.dumps(value));finalise(packet)
 unchanged=public(packet);record(label+'-unchanged-save',public=unchanged);assert unchanged['accepted']
 for p,raw in saved.items():p.write_bytes(raw)

 if rerender_suffix:
  baseline_image=folder/'original-future.png'
  code=f'import bpy\nbpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\nscene=bpy.context.scene\n'+rerender_suffix+'\n'+f'scene.render.filepath={str(baseline_image)!r}\nbpy.ops.render.render(write_still=True)\n'
  (folder/'original-future.py').write_text(code);native(exe,code);w,h,before=read(baseline_image)

 try:
  witness=folder/'observed.json'
  code=f'import bpy,json,sys\nsys.path.insert(0,{str(trusted)!r})\nbpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\nbpy.context.preferences.filepaths.save_version=0\nscene=bpy.context.scene\n'+mutation+'\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+\
   'from schemaxis.adaptors.blender.adaptor import plan\nfrom schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+\
   f'master,selection,_=plan(json.loads(open({str(packet/"input.json")!r}).read()))\np=master.document["scenes"][0].get("production")\nproduction=observe(p) if p is not None else None\nstate=snapshot(selection.order)\nopen({str(witness)!r},"w").write(json.dumps(dict(state=state,production=production)))\n'
  (folder/'mutator.py').write_text(code);native(exe,code);observed=json.loads(witness.read_text());v=json.loads(saved[receipt]);v['states'][0]['snapshot']=observed['state']
  if observed['production'] is not None:
   observed['production']['meshEditBaselines']=v['states'][0]['production']['meshEditBaselines'];v['states'][0]['production']=observed['production']
  next(a for a in v['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();receipt.write_text(json.dumps(v));v=json.loads(saved[reopened]);v['states'][0]=observed['state']
  if observed['production'] is not None:v['production'][0]=observed['production']
  reopened.write_text(json.dumps(v));finalise(packet);public_result=public(packet)
  direct=folder/'direct-fault.json';code=f'import sys,json\nsys.path.insert(0,{str(trusted)!r})\nfrom schemaxis.adaptors.blender.native import reopen\nfrom schemaxis.errors import SchemaxisError\nfault=None\ntry:reopen({str(packet)!r},{str(folder/"direct-reopened.json")!r})\nexcept SchemaxisError as e:fault=e.fault.to_dict()\nopen({str(direct)!r},"w").write(json.dumps(fault))\n';(folder/'direct.py').write_text(code);native(exe,code)
  image=folder/'rerender.png';details=folder/'native-details.json'
  code=f'import bpy,json\nbpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\nscene=bpy.context.scene\n'+rerender_suffix+'\n'+f'open({str(details)!r},"w").write(json.dumps(dict(frame=scene.frame_current,subframe=scene.frame_subframe,camera=scene.camera.name,gravityEnabled=scene.use_gravity,workingSpace=bpy.data.colorspace.working_space,boxPosition=list(bpy.data.objects["box"].matrix_world.translation) if "box" in bpy.data.objects else None,markers=[dict(frame=m.frame,camera=m.camera.name if m.camera else None) for m in scene.timeline_markers])))\nscene.render.filepath={str(image)!r}\nbpy.ops.render.render(write_still=True)\n';(folder/'rerender.py').write_text(code);native(exe,code);rw,rh,after=read(image);assert (w,h)==(rw,rh)
  mutant=folder/'mutant';mutant.mkdir()
  for p in saved:(mutant/p.name).write_bytes(p.read_bytes())
  fresh=json.loads(direct.read_text());assert not public_result['accepted'] and fresh and public_result['fault']['code']==fresh['code']=='VERIFICATION_FAILED' and message in public_result['fault']['message'] and message in fresh['message'],(label,public_result,fresh)
  assert before!=after,(label,'mutation did not change native pixels')
  record(label,public=public_result,directFault=json.loads(direct.read_text()),changedPixelCount=sum(before[i:i+4]!=after[i:i+4] for i in range(0,len(before),4)),maximumByteDifference=max(abs(a-b) for a,b in zip(before,after)),originalCentre=list(before[4*((h//2)*w+w//2):4*((h//2)*w+w//2)+4]),mutantCentre=list(after[4*((h//2)*w+w//2):4*((h//2)*w+w//2)+4]),nativeDetails=json.loads(details.read_text()),nativeMutantSha256=hashlib.sha256(blend.read_bytes()).hexdigest(),bothReadbacksNativeHashPublicationRefreshed=True)
 finally:
  for p,raw in saved.items():p.write_bytes(raw)
  assert public(packet)['accepted'] and all(p.read_bytes()==raw for p,raw in saved.items());record(label+'-restored')

def link(a,socket,b,target):return {'from':{'node':a,'socket':socket},'to':{'node':b,'socket':target}}
d=document();d['render'].update(worldStrength=0,lightEnergy=0);d['production'].update(frameEnd=2,renderFrames=[2]);d['production']['objects'].append({'id':'alternate','kind':'camera','location':[100,0,5]});case('camera-markers',d,"a=scene.timeline_markers.new('original',frame=1);a.camera=scene.camera;b=scene.timeline_markers.new('switch',frame=2);b.camera=bpy.data.objects['alternate']",'scene.frame_set(2)')
d=document();d['size']=[128,128];d['render'].update(worldStrength=0,lightEnergy=0);d['production']['objects']=[{'id':'letter','kind':'text','body':'O','size':2,'material':'surface'}];case('font-render-tessellation',d,"bpy.data.objects['letter'].data.render_resolution_u=1",message='shader state differs')
d=document();d['render'].update(worldStrength=0,lightEnergy=0);d['production']['frameEnd']=2
nodes=[{'id':'in','kind':'input'},{'id':'clock','kind':'sceneTime'},{'id':'subtract','kind':'math','properties':{'operation':'SUBTRACT'},'values':{'b':1}},{'id':'scale','kind':'math','properties':{'operation':'MULTIPLY'},'values':{'b':10}},{'id':'offset','kind':'combineXYZ'},{'id':'move','kind':'transform'},{'id':'out','kind':'output'}]
links=[link(*v) for v in [('in','geometry','move','geometry'),('clock','frame','subtract','a'),('subtract','value','scale','a'),('scale','value','offset','x'),('offset','vector','move','translation'),('move','geometry','out','geometry')]]
d['production'].update(geometryGraphs=[{'id':'clockMotion','nodes':nodes,'links':links}],geometryBindings=[{'object':'patch','graph':'clockMotion'}]);case('geometry-subframe',d,'scene.frame_set(1,subframe=.5)')
d=settings(document(),'workbench');d['size']=[128,128];d['cameras']=[{'direction':[1,-2,3],'up':[0,0,1]}];d['render']['renderer'].update(lighting={'kind':'studio'},shadows={'kind':'on','direction':[1,1,1]});d['production']['objects'][0]['vertices']=[[-3,-3,0],[3,-3,0],[3,3,0],[-3,3,0]];d['production']['objects'].append({'id':'caster','kind':'mesh','vertices':[[-.4,-.4,.1],[.4,-.4,.1],[.4,.4,.1],[-.4,.4,.1],[-.4,-.4,1.5],[.4,-.4,1.5],[.4,.4,1.5],[-.4,.4,1.5]],'faces':[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]],'material':'surface'});case('workbench-object-shadow',d,"bpy.data.objects['caster'].display.show_shadows=False")
d=document();d['render'].update(worldStrength=0,lightEnergy=0);case('file-working-colour-space',d,"bpy.ops.wm.set_working_color_space(convert_colors=False,working_space='ACEScg')")
d=json.loads((base/'examples/schemaxis/blender-production.json').read_text());p=d['scenes'][0];p['prepareOnly']=False;s=p['production'];s.update(objects=[],collections=[],hierarchy=[],tracks=[],renderFrames=[],exports=[],rigidBodies=[{'object':'box','mass':2,'shape':'BOX'}],simulationFrames=[1,20],currentFrame=1,frameEnd=24);d['nodes'][1]['options']['centre']=[0,0,5];d['nodes'].append({'id':'anchor','filter':'cube','inputs':{'material':'paint'},'options':{'centre':[5,0,0]}});p['visible']=['box','anchor'];case('latent-scene-gravity',d,'scene.use_gravity=False',"for frame in range(1,21):scene.frame_set(frame)\nbpy.context.view_layer.update()")
source=out/'curve-keys.blend'
code="import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\nd=bpy.data.curves.new('curve','CURVE');d.dimensions='3D';d.bevel_depth=.1;s=d.splines.new('POLY');s.points.add(1);s.points[0].co=(0,0,0,1);s.points[1].co=(0,0,2,1);o=bpy.data.objects.new('curve',d);bpy.context.scene.collection.objects.link(o);o.shape_key_add(name='Basis');o.shape_key_add(name='Variant')\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n'
(out/'curve-keys-recipe.py').write_text(code);native(exe,code)
fault=None
try:run({'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'assets':[{'id':'curve','format':'blend','file':str(source)}]}},out/'curve-key-refusal',executable=exe,timeout=180)
except SchemaxisError as error:fault=error.fault.to_dict()
assert fault and fault['code']=='UNSUPPORTED_ASSET_DEPENDENCY' and 'curve shape-key' in fault['message'],fault
record('curve-key-needs-reviewed-mapping',fault=fault,sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest())
verify_identity(report,exe);report['status']='passed';(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
