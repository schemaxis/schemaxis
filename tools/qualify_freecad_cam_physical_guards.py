"""Finite synthetic physical-CAM native guards; no submitted restore to inspect."""
import base64,copy,json,re,shutil,sys
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import cam_publication,cam_reduced
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.adaptors.freecad.process import SubprocessRunner
FILES=('authored.json','plan.json','source.FCStd','source.brep','machining.FCStd','program.ngc','built.json','reopened.json','material.json','replay.json','result.json','schema.snapshot.json','remaining.brep','residual.brep','gouge.brep')
def mutations(members):
 def prop(r,obj,key):
  p=r.find("./ObjectData/Object[@name='"+obj+"']/Properties/Property[@name='"+key+"']");assert p is not None,(obj,key);return p
 def attr(obj,key,field,value):return lambda r:prop(r,obj,key)[0].set(field,value)
 def proxy(r):prop(r,'DrillTool0','Proxy')[0].set('value',base64.b64encode(b'{"version":2}').decode())
 changes=[('physical-shank',attr('DrillTool0','ShankDiameter','value','.9')),
 ('cutting-height',attr('DrillTool0','CuttingEdgeHeight','value','3.1')),
 ('declared-reach',attr('DrillTool0','SchemaxisCuttingReach','value','3.1')),
 ('attribute-shank',attr('Attributes','ShankDiameter','value','.9')),
 ('module-identity',attr('DrillTool0','Proxy','module','foreign.extension')),
 ('proxy-state',proxy),('shape-identity',attr('DrillTool0','ShapeID','value','drill')),
 ('holder-radius',attr('Holder0Step0','Radius','value','2.001')),
 ('controller-number',attr('Cutter0','ToolNumber','value','2')),
 ('profile-revolution',attr('Revolution','Angle','value','180'))]
 for label,change in changes:
  data=dict(members);r=E.fromstring(members['Document.xml']);change(r);data['Document.xml']=E.tostring(r);yield label,data
 lines=members['Clone.Shape.Map.txt'].decode().splitlines();m=re.fullmatch(r'(\d+) PostfixCount (\d+)',lines[1]);assert m
 n=int(m[2]);lines[1]=m[1]+' PostfixCount '+str(n+1);lines.insert(2+n,';:H7fffffff,F')
 yield 'unused-postfix',dict(members,**{'Clone.Shape.Map.txt':('\n'.join(lines)+'\n').encode()})
 yield 'extra-resource',dict(members,**{'foreign.py':b'raise RuntimeError()'})

def native_guards(root):
 import FreeCAD as A
 from schemaxis.adaptors.freecad.cam_native3 import reopen
 root=Path(root);target=root/'packet';model=target/'machining.FCStd';original=model.read_bytes();opened=[];open_native=A.openDocument
 with ZipFile(model) as archive:members={n:archive.read(n) for n in archive.namelist()}
 def tracked(path,*args,**kwargs):
  if Path(path).name=='machining.FCStd':opened.append(str(path))
  return open_native(path,*args,**kwargs)
 A.openDocument=tracked;records=[]
 try:
  for label,changed in mutations(members):
   try:
    with ZipFile(model,'w') as archive:
     for name,data in changed.items():archive.writestr(name,data)
    (root/'mutations').mkdir(exist_ok=True);(root/'mutations'/(label+'.FCStd')).write_bytes(model.read_bytes())
    opened.clear()
    try:reopen(target)
    except Exception as error:
     assert not opened,(label,opened);records.append({'case':label,'fault':str(error),'submittedOpens':0})
    else:raise AssertionError(label+' native mutation accepted')
   finally:model.write_bytes(original)
  opened.clear();reopen(target);assert len(opened)==1 and file_digest(model)==__import__('hashlib').sha256(original).hexdigest()
  atomic_json(root/'native-guards.json',{'verified':True,'attacks':records,'restoredPrivateCopyOpens':len(opened)})
 finally:A.openDocument=open_native


def hostile(target):
 """Refreshed PUBLIC companions reach provider authority, not stale hashes."""
 from schemaxis.publication_metadata import finalise
 target=Path(target);p=json.loads((target/'plan.json').read_text())
 retained={n:(target/n).read_bytes() for n in FILES}
 extra=('cam-project.zip','verification.json','preferences.cfg','publication-metadata.json')
 retained.update({n:(target/n).read_bytes() for n in extra})
 retained.update({p.name:p.read_bytes() for p in target.glob('*.metadata.json')})
 report={}
 with ZipFile(target/'machining.FCStd') as archive:members={n:archive.read(n) for n in archive.namelist()}
 def refresh():
  m=json.loads((target/'material.json').read_text());m['nativeSha256']=file_digest(target/'machining.FCStd');m['programSha256']=file_digest(target/'program.ngc');atomic_json(target/'material.json',m)
  cam_publication.publish(target,'1.1.4',p)
  result=json.loads((target/'result.json').read_text());result['artifacts']=cam_publication.artifacts(target);atomic_json(target/'result.json',result);finalise(target)
 def restore():
  for n,data in retained.items():(target/n).write_bytes(data)
 def reject(label,required=None):
  try:registry.verify(target)
  except SchemaxisError as error:
   assert error.fault.code!='INVALID_SCHEMA_SNAPSHOT' and 'metadata' not in error.fault.message.lower(),error.fault
   if required:assert required in error.fault.message,error.fault
   report[label]=error.fault.to_dict();atomic_json(target.parent/'hostile.json',report)
  else:raise AssertionError(label+' public mutation accepted')
 try:
  for label,changed in mutations(members):
   try:
    with ZipFile(target/'machining.FCStd','w') as archive:
     for name,data in changed.items():archive.writestr(name,data)
    refresh();reject(label)
   finally:restore()
  for filename in (cam_reduced.FILENAME,cam_reduced.LAUNCHER_NAME):
   for action in ('replace','missing'):
    try:
     with ZipFile(target/'cam-project.zip') as archive:data={n:archive.read(n) for n in archive.namelist()}
     if action=='replace':data[filename]+=b'\nraise RuntimeError("foreign")\n'
     else:del data[filename]
     with ZipFile(target/'cam-project.zip','w') as archive:
      for name,value in data.items():archive.writestr(name,value)
     artifacts=cam_publication.artifacts(target);atomic_json(target/'verification.json',{'runtime':'1.1.4','artifacts':artifacts})
     result=json.loads((target/'result.json').read_text());result['artifacts']=artifacts;atomic_json(target/'result.json',result);finalise(target)
     reject(action+'-'+filename,'Editable CAM bundle')
    finally:restore()
  for key,value in [('minimumObservedGuardGap',.501),('temporalCredits',1.0)]:
   try:
    m=json.loads((target/'material.json').read_text());assert type(m[key]) is not type(value) or m[key]!=value
    m[key]=value;atomic_json(target/'material.json',m);reject('forged-'+key)
   finally:restore()
 finally:restore()
 assert registry.verify(target)['verified'];report['unchanged-restored-public-control']=True
 return report


def necessary_credit(root):
 """Literal public fixture and private one-line counterfactual, no route escape."""
 import inspect,hashlib,math
 import FreeCAD as A
 from schemaxis.adaptors.freecad import cam_ordered_native as engine
 from schemaxis.adaptors.freecad.cam_state2 import reference
 from schemaxis.adaptors.freecad.cam_code2 import parse
 root=Path(root);packet=root/'packet';p=json.loads((packet/'plan.json').read_text());records=[]
 with reference(packet,p) as canonical:
  doc=A.openDocument(str(canonical/'machining.FCStd'))
  try:
   replay=parse((canonical/'program.ngc').read_text(),p['tools'],p['setup']['safe'],ordered=True)
   desired=doc.getObject('Source').Shape
   g=engine.OrderedGeometry();fresh=engine.profiles(doc,p,g);m,_=engine.replay_geometry(p,replay,desired,fresh,g)
   assert abs(m['removedVolume']-22*math.pi/3)<1e-7 and abs(m['removedCentreOfMass'][2]+323/88)<1e-7
   assert m['temporalCredits']>0 and m['minimumObservedGuardGap']>=.25
   records.append({'case':'current-literal-needed-credit','verified':True,'material':m})
   original=inspect.getsource(engine.replay_geometry);assert original.count('state=after_credit')==1
   altered=original.replace('state=after_credit','state=remaining');space=dict(engine.__dict__)
   exec(compile(altered,'<controlled-disable-current-motion-credit>','exec'),space)
   g=engine.OrderedGeometry();fresh=engine.profiles(doc,p,g)
   try:space['replay_geometry'](p,replay,desired,fresh,g)
   except SchemaxisError as error:
    assert error.fault.code=='TOOL_COLLISION';records.append({'case':'credit-disabled','fault':error.fault.to_dict(),'originalFunctionSha256':hashlib.sha256(original.encode()).hexdigest(),'variantFunctionSha256':hashlib.sha256(altered.encode()).hexdigest(),'delta':'state=after_credit -> state=remaining'})
   else:raise AssertionError('Public fixture did not require current-motion credit')
   # Change the real parametric native shank, then re-prove full B/C/H coverage.
   bad=copy.deepcopy(p);bad['tools'][0]['shankDiameter']=1.6
   doc.getObject(p['tools'][0]['nativeTool']).ShankDiameter=1.6;doc.recompute()
   g=engine.OrderedGeometry();fresh=engine.profiles(doc,bad,g)
   try:engine.replay_geometry(bad,replay,desired,fresh,g)
   except SchemaxisError as error:
    assert error.fault.code=='TOOL_CLEARANCE';records.append({'case':'actual-native-shank-gap-.2-less-than-.25','fault':error.fault.to_dict()})
   else:raise AssertionError('Actual larger shank violated the gap without refusal')
  finally:A.closeDocument(doc.Name)
 atomic_json(root/'necessary-credit.json',{'verified':True,'checks':records})
