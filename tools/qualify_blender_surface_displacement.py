"""Projected geometry distinguishes shader displacement space and bump-only."""
import argparse,copy,hashlib,json,math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.png import read
from qualify_blender_render_policy import document
from blender_surface_evidence import identity,verify_identity


def constant(value):return {'kind':'constant','value':value}


def silhouette(directory):
    receipt=json.loads((directory/'verification.json').read_text())
    path=next(Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='image')
    width,height,pixels=read(path)
    points=[(i%width,i//width) for i in range(width*height) if min(pixels[4*i:4*i+3])>200]
    assert points
    bounds=[min(p[k] for p in points) for k in (0,1)]+[max(p[k] for p in points)+1 for k in (0,1)]
    return {'pixelBounds':bounds,'pixelCentre':[(bounds[k]+bounds[k+2])/2 for k in (0,1)],
            'pixelSpan':[bounds[k+2]-bounds[k] for k in (0,1)],'whitePixels':len(points)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    digest=hashlib.sha256(runtime_archive()).hexdigest()
    report={'status':'running','sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':digest,'checks':[],
       'oracle':'Known XY unit quad, view direction (0,-.6,.8), screen up (0,.8,.6), orthographic width4 at128x128. Constant height1, midlevel0, distance.5. Projected centre y=64-32*.6*worldZ; spans64x51.2. Predetermined 2pixel boundary tolerance accounts only for raster coverage/filtering. Shader displacement changes rendered geometry; stored/exported mesh vertices remain the authored base.'}
    target=out/'summary.json';base=document();base['size']=[128,128]
    report.update(identity(out,args.blender))
    base['cameras'][0].update(direction=[0,-.6,.8],up=[0,0,1],focalPoint=[0,0,0],scale=4)
    base['render'].update(samples=8,lightEnergy=0,worldStrength=0)
    p=base['production'];p['materialGraphs']=[];p['surfaceMaterials']=[{'id':'surface',
       'baseColour':constant([0,0,0]),'ior':constant(1),'emission':{'colour':constant([1,1,1]),'strength':constant(1)}}]
    try:
        for label,kind,space,scale,z in [('object-identity','geometry','object',1,.5),
            ('object-scaled','geometry','object',2,1),('world-scaled','geometry','world',2,.5),
            ('bump-only','bump','object',1,0),('explicitly-translated-reference','none','object',1,.5)]:
            report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n')
            d=copy.deepcopy(base);p=d['production'];obj=p['objects'][0];obj['scale']=[1,1,scale]
            if kind!='none':p['surfaceMaterials'][0]['displacement']={'kind':kind,'space':space,'height':constant(1),'midlevel':0,'distance':.5}
            else:obj['vertices']=[[x,y,z] for x,y,_ in obj['vertices']]
            run(d,out/label,executable=args.blender,timeout=180)
            with location_context({'blender':args.blender}):assert verify(out/label)['verified']
            actual=silhouette(out/label);centre=[64,64-32*.6*z];span=[64,51.2]
            result={'label':label,'independentWorldZ':z,'predictedCentre':centre,'predictedSpan':span,**actual}
            report['checks'].append(result);target.write_text(json.dumps(report,indent=2)+'\n')
            assert all(abs(a-b)<=2 for a,b in zip(actual['pixelCentre'],centre)),result
            assert all(abs(a-b)<=2 for a,b in zip(actual['pixelSpan'],span)),result
            print(label+' PASS',flush=True)
        first=report['checks'][0];reference=report['checks'][-1]
        assert all(abs(a-b)<=1 for a,b in zip(first['pixelBounds'],reference['pixelBounds']))
        assert hashlib.sha256(runtime_archive()).hexdigest()==digest
        verify_identity(report,args.blender)
        report['status']='passed';report.pop('activeCase',None)
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
