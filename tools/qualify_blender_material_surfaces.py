"""Independent filled/swept Curve and text material image effects."""
import argparse,copy,hashlib,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tools'))
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.png import read
from qualify_blender_material_assignments import fixture,COLOURS
from qualify_blender_render_policy import expected
from qualify_blender_image_preview import rgba

def main():
 p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False)
 digest=hashlib.sha256(runtime_archive()).hexdigest();tool=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':digest,'qualifierSha256':tool,'checks':[]};target=out/'summary.json'
 def execute(label,d,points=None,colours=None,text=False):
  report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n');assert hashlib.sha256(runtime_archive()).hexdigest()==digest
  directory=out/label;run(d,directory,executable=a.blender,timeout=240)
  with location_context({'blender':a.blender}):assert verify(directory)['verified']
  result={'label':label}
  if points:
   pixels=rgba(directory,points);wanted=[expected(c,0) for c in colours];assert all(abs(x-y)<=1 for row,ref in zip(pixels,wanted) for x,y in zip(row,ref)),(label,pixels,wanted)
   result.update(points=points,encodedRGBA=pixels,independentExpectedRGBA=wanted,maximumByteError=1)
  if text:
   receipt=json.loads((directory/'verification.json').read_text());image=next(Path(r['file']) for r in receipt['artifacts'] if r.get('kind')=='image');w,h,data=read(image)
   columns=[];counts=[]
   for colour in [COLOURS['red'],COLOURS['blue']]:
    wanted=expected(colour,0);samples=[i for i in range(w*h) if all(abs(data[4*i+k]-v)<=1 for k,v in enumerate(wanted))];assert len(samples)>3,(label,wanted,len(samples));columns.append(sorted({i%w for i in samples}));counts.append(len(samples))
   assert max(columns[0])<min(columns[1]),(label,columns)
   result.update(independentOracle='Both authored characters render their distinct literal material colours, in declared left-to-right order; no claim of exact font outline or glyph metrics.',pureColourPixelCounts=counts,colourColumns=columns)
  report['checks'].append(result);target.write_text(json.dumps(report,indent=2)+'\n');print(label+' PASS',flush=True)
 try:
  for engine in ('cycles','workbench'):
   d=fixture(engine);p=d['production'];p['objects']=[{'id':'patch','kind':'spline','dimensions':'2D','fillSolver':'CDT','splines':[{'id':'left','kind':'POLY','closed':True,'points':[{'position':[x,y,0]} for x,y in [(-.8,-.4),(-.1,-.4),(-.1,.4),(-.8,.4)]]},{'id':'right','kind':'POLY','closed':True,'points':[{'position':[x,y,0]} for x,y in [(.1,-.4),(.8,-.4),(.8,.4),(.1,.4)]]}]}]
   p['materialAssignments'][0]['regions'][0]['selection']={'kind':'splines','names':['right']};execute('filled-contours-'+engine,d,[(16,16),(48,16)],[COLOURS['red'],COLOURS['blue']])
   d=fixture(engine);p=d['production'];p['objects']=[{'id':'patch','kind':'spline','bevel':{'kind':'round','depth':.08,'resolution':1},'splines':[{'id':'lower','kind':'POLY','points':[{'position':[-.8,-.3,0]},{'position':[.8,-.3,0]}]},{'id':'upper','kind':'POLY','points':[{'position':[-.8,.3,0]},{'position':[.8,.3,0]}]}]}]
   p['materialAssignments'][0]['regions'][0]['selection']={'kind':'splines','names':['upper']};execute('swept-paths-'+engine,d,[(32,6),(32,25)],[COLOURS['blue'],COLOURS['red']])
   d=fixture(engine);p=d['production'];p['objects']=[{'id':'patch','kind':'text','body':'HH','size':.7,'align':'CENTER','location':[0,-.25,0]}];p['materialAssignments'][0]['regions'][0]['selection']={'kind':'characters','start':1,'end':2};execute('two-character-colours-'+engine,d,text=True)
  assert hashlib.sha256(runtime_archive()).hexdigest()==digest and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==tool;report['status']='passed';report.pop('activeCase',None)
 finally:
  if report['status']=='running':report['status']='failed'
  target.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
