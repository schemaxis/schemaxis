"""Literal tangent normal / stored UV transform rendered acceptance."""
import argparse
import copy,hashlib,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tools'))
from qualify_blender_render_policy import document,pixel,expected
from qualify_blender_image_preview import png
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.configuration import location_context
from schemaxis.assessments import source_fingerprint
from blender_surface_evidence import identity,verify_identity

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    exe=args.blender
    digest=hashlib.sha256(runtime_archive()).hexdigest();report={'status':'running','sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':digest,'checks':[],
     'oracle':'Unit-irradiance directional light; IOR1 neutralizes dielectric reflection. White Lambert BRDF 1/pi. Encoded PNG normal decoded as normalize(2*RGB/255-1). Stored affine UV Jacobian defines normalized tangent and signed bitangent. Standard sRGB output, maximum2byte error declared before execution.'}
    target=out/'report.json'
    report.update(identity(out,args.blender))
    try:
     image=out/'normal.png';rgb=[128,204,230];png(image,[rgb+[255]]*4)
     base=document();base['render'].update(samples=8,worldStrength=0,lightEnergy=0)
     p=base['production'];p['materialGraphs']=[]
     p['images']=[{'id':'normal','file':str(image),'colourSpace':'Non-Color'}]
     p['objects'].append({'id':'sun','kind':'light','type':'SUN','energy':1,'rotation':[-math.atan2(.6,.8),0,0],'angle':.000001})
     surface={'id':'surface','baseColour':{'kind':'constant','value':[1,1,1]},'ior':{'kind':'constant','value':1},
      'samplers':[{'id':'map','image':'normal','filter':'nearest','coordinates':{'kind':'uv','set':{'kind':'named','name':'Finish'}}}]}
     p['surfaceMaterials']=[surface]
     cases=[(label,angle,scale,convention,normal,'tangent',0,[1,1,1]) for label,angle,scale,convention,normal in [('geometric',0,[1,1],'openGL',False),('tangent',0,[1,1],'openGL',True),
      ('directX',0,[1,1],'directX',True),('stored-rotate90',90,[1,1],'openGL',True),
      ('stored-mirrorV',0,[1,-1],'openGL',True),('stored-rotate-mirror-nonuniform',45,[-2,3],'openGL',True)]]
     cases += [('object-rotate90',0,[1,1],'openGL',True,'object',math.pi/2,[1,1,1]),
               ('world-rotate90',0,[1,1],'openGL',True,'world',math.pi/2,[1,1,1]),
               ('object-nonuniform',0,[1,1],'openGL',True,'object',0,[1,2,1]),
               ('world-nonuniform',0,[1,1],'openGL',True,'world',0,[1,2,1])]
     for label,angle,scale,convention,normal,space,object_angle,object_scale in cases:
      report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n')
      d=copy.deepcopy(base);p=d['production'];s=p['surfaceMaterials'][0]
      if normal:s['normal']={'kind':'normalMap','map':{'sampler':'map','convention':convention,'space':{'kind':space}}}
      p['objects'][0].update(rotation=[0,0,object_angle],scale=object_scale)
      p['meshData']=[{'object':'patch','uvMaps':[{'name':'Original','method':'planar','origin':[-1,-1,0],'size':[2,2]},
       {'name':'Finish','method':'copy','source':'Original','transform':{'rotationDegrees':angle,'scale':scale}}]}]
      radians=math.radians(angle);tx,ty=math.cos(radians)/scale[0],-math.sin(radians)/scale[1];length=math.hypot(tx,ty);tx/=length;ty/=length
      sign=1 if scale[0]*scale[1]>0 else -1;bx,by=-ty*sign,tx*sign
      encoded=[2*x/255-1 for x in rgb];length=math.sqrt(sum(x*x for x in encoded));nx,ny,nz=[x/length for x in encoded]
      if convention=='directX':ny=-ny
      world=[nx*tx+ny*bx,nx*ty+ny*by,nz] if normal else [0,0,1]
      if space in ('object','world'):world=[nx,ny,nz]
      if space=='object':
       world=[v/s for v,s in zip(world,object_scale)];length=math.sqrt(sum(v*v for v in world));world=[v/length for v in world]
       x,y,z=world;world=[math.cos(object_angle)*x-math.sin(object_angle)*y,math.sin(object_angle)*x+math.cos(object_angle)*y,z]
      radiance=max(0,.6*world[1]+.8*world[2])/math.pi;wanted=expected([radiance]*3,0)
      run(d,out/label,executable=exe,timeout=180)
      with location_context({'blender':exe}):assert verify(out/label)['verified']
      actual=pixel(out/label);report['checks'].append({'label':label,'worldNormal':world,'linearRadiance':radiance,'expectedRGBA':wanted,'actualRGBA':actual});target.write_text(json.dumps(report,indent=2)+'\n')
      assert all(abs(a-b)<=2 for a,b in zip(actual,wanted)),report['checks'][-1]
      print(label+' PASS',flush=True)
     assert hashlib.sha256(runtime_archive()).hexdigest()==digest
     verify_identity(report,args.blender)
     report['status']='passed';report.pop('activeCase',None)
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
