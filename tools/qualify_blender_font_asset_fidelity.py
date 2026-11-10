#!/usr/bin/env python3
"""Check Font asset source authority after native save and forged readbacks.

The source producer owns character formatting and text-box layout. Refreshing
consumer receipt hashes and readbacks must not authorize changes to that source.
"""
import argparse,copy,hashlib,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tools'))
from schemaxis.adaptors.blender.adaptor import run,verify,_verify
from schemaxis.assessments import source_fingerprint
from schemaxis.artifacts import runtime_archive
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from qualify_blender_material_assignments import fixture
from qualify_blender_mesh_data import native
p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False)
report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':hashlib.sha256(runtime_archive()).hexdigest(),'qualifierSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[]};summary=out/'summary.json'
try:
 d=fixture('workbench');d['prepareOnly']=True;d['production']['objects']=[{'id':'patch','kind':'text','body':'HH','size':.7}];d['production']['materialAssignments'][0]['regions'][0]['selection']={'kind':'characters','start':1,'end':2};source=out/'producer';run(d,source,executable=a.blender,timeout=240)
 consumer=out/'consumer';run({'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'assets':[{'id':'fontSource','file':str(source/'0000.blend'),'format':'blend'}]}},consumer,executable=a.blender,timeout=240)
 with location_context({'blender':a.blender}):assert verify(consumer)['verified']
 blend=consumer/'0000.blend';receipt=consumer/'verification.json';reopened=consumer/'reopened.json';saved={f:f.read_bytes() for f in (blend,receipt,reopened)}
 try:
  for label,mutation in [('unchangedSave',''),('characterMaterial',"text.data.body_format[0].material_index=1"),('characterStyle',"text.data.body_format[0].use_bold=True"),('textBoxLayout',"text.data.text_boxes[0].width=1.5")]:
   for path,data in saved.items():path.write_bytes(data)
   current=out/(label+'.json')
   code='import bpy,json,sys\n'+f'sys.path.insert(0,{str(consumer/"runtime.zip")!r})\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+"from schemaxis.adaptors.blender.production_native import observe\nroot=bpy.data.objects['fontSource'];text=next(o for o in root.instance_collection.all_objects if o.type=='FONT')\n"+f"spec=json.loads(open({str(consumer/'input.json')!r}).read())['scenes'][0]['production']\n"+"before=observe(spec);old=[f.material_index for f in text.data.body_format]\n"+mutation+'\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+"after=observe(spec);after['meshEditBaselines']=[];result={'oldIndices':old,'newIndices':[f.material_index for f in text.data.body_format],'fidelityUnchanged':before['assets'][0]['fidelity']==after['assets'][0]['fidelity'],'observed':after}\n"+f'open({str(current)!r},"w").write(json.dumps(result))\n'
   native(a.blender,code);actual=json.loads(current.read_text());r=json.loads(saved[receipt]);next(artifact for artifact in r['artifacts'] if artifact['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();r['states'][0]['production']=actual['observed'];receipt.write_text(json.dumps(r));r=json.loads(saved[reopened]);r['production'][0]=actual['observed'];reopened.write_text(json.dumps(r))
   fault=None
   with location_context({'blender':a.blender}):
    try:_verify(consumer)
    except SchemaxisError as exc:fault=exc.fault.to_dict()
   result={'label':label,'oldIndices':actual['oldIndices'],'newIndices':actual['newIndices'],'fidelityUnchanged':actual['fidelityUnchanged'],'providerAccepted':fault is None,'fault':fault,'refreshedNativeHash':True,'submittedReadbacksReplaced':True};report['checks'].append(result);summary.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(result),flush=True)
   if label=='unchangedSave':assert fault is None
   else:
    if label=='characterMaterial':assert actual['oldIndices']==[0,1] and actual['newIndices']==[1,1]
    (out/(label+'-mutated.blend')).write_bytes(blend.read_bytes())
    assert fault and fault['code']=='VERIFICATION_FAILED' and fault['message']=='native assets differ from trusted captured-source reconstruction' and not actual['fidelityUnchanged']
 finally:
  for path,data in saved.items():path.write_bytes(data)
 with location_context({'blender':a.blender}):assert verify(consumer)['verified']
 report['restoredOriginalPositive']=True;report['status']='passed'
finally:
 if report['status']=='running':report['status']='failed'
 summary.write_text(json.dumps(report,indent=2)+'\n')
