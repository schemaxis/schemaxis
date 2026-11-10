"""Snell slab lateral shift distinguishes thick refraction and thin sheets."""
import argparse,copy,hashlib,json,math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from qualify_blender_render_policy import document,pixel
from qualify_blender_material_assignments import graph
from blender_surface_evidence import identity,verify_identity


def constant(value):return {'kind':'constant','value':value}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--engine',choices=['cycles','eevee'],default='cycles');args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    digest=hashlib.sha256(runtime_archive()).hexdigest()
    # Camera-right basis (.8,0,-.6); the centre pixel is offset by half
    # a pixel. Divide its screen offset by .8 for entry x at z=0.
    # The emitter at z=-1.2
    # has a colour boundary -.7 strictly between the predicted intersections.
    resolution=128 if args.engine=='eevee' else 32
    entry=1.25/resolution;theta=math.asin(.6);refracted=math.asin(.6/1.5)
    positions={'neutral':entry-1.2*math.tan(theta),'solid':entry-math.tan(refracted)-.2*math.tan(theta),
               'thin':entry-1.2*math.tan(theta)}
    assert positions['neutral']<-.7<positions['solid'] and positions['thin']<-.7
    report={'status':'running','sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':digest,'engine':args.engine,
            'independentSnellIntersectionsX':positions,'emitterBoundaryX':-.7,'checks':[],
            'oracle':'Snell law sin(theta_t)=sin(theta_i)/n for a unit-thickness parallel slab. Literal red/green emitter classification at centre ray; no exact stochastic transmission-intensity claim. Predetermined dominant channel >=150 and other RGB channels <=2.'}
    target=out/'summary.json'
    report.update(identity(out,args.blender))
    base=document();base['render'].update(samples=256,lightEnergy=0,worldStrength=0)
    if args.engine=='eevee':
        base['size']=[resolution,resolution]
        base['render'].pop('samples')
        base['render']['renderer']={'kind':'eevee','samples':64,'rayTracing':{'kind':'screen','resolution':'1','quality':1,'denoise':{'kind':'none'}}}
    base['cameras'][0].update(direction=[.6,0,.8],up=[0,1,0],focalPoint=[0,0,0],scale=2)
    p=base['production'];p['materialGraphs']=[graph('red'),graph('green')]
    p['objects']=[{'id':'slab','kind':'mesh','material':'glass',
        'vertices':[[-5,-5,0],[5,-5,0],[5,5,0],[-5,5,0],[-5,-5,-1],[5,-5,-1],[5,5,-1],[-5,5,-1]],
        'faces':[[0,1,2,3],[7,6,5,4],[4,5,1,0],[5,6,2,1],[6,7,3,2],[7,4,0,3]]},
        {'id':'reference','kind':'mesh','material':'red',
         'vertices':[[-5,-5,-1.2],[-.7,-5,-1.2],[-.7,5,-1.2],[-5,5,-1.2],[5,-5,-1.2],[5,5,-1.2]],
         'faces':[[0,1,2,3],[1,4,5,2]]}]
    p['materialAssignments']=[{'id':'colours','kind':'layout','object':'reference','slots':[{'id':'left','material':'red'},{'id':'right','material':'green'}],
        'defaultSlot':'left','regions':[{'slot':'right','selection':{'kind':'faceIndices','indices':[1]}}]}]
    p['surfaceMaterials']=[{'id':'glass','baseColour':constant([1,1,1]),'roughness':constant(0),'transmission':constant(1)}]
    try:
        for label,ior,wall,index in [('neutral',1,'solid',0),('solid',1.5,'solid',1),('thin',1.5,'thin',0)]:
            report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n')
            d=copy.deepcopy(base);d['production']['surfaceMaterials'][0].update(ior=constant(ior),wall=wall)
            if args.engine=='eevee':
                d['production']['surfaceMaterials'][0]['realtime']={'transmission':'screen',
                    'thickness':{'kind':'slab','distance':constant(1)} if wall=='solid' else {'kind':'automatic'}}
            run(d,out/label,executable=args.blender,timeout=180)
            with location_context({'blender':args.blender}):assert verify(out/label)['verified']
            actual=pixel(out/label);result={'label':label,'predictedEmitterX':positions[label],'expectedDominantRGBChannel':index,'actualRGBA':actual}
            report['checks'].append(result);target.write_text(json.dumps(report,indent=2)+'\n')
            assert actual[index]>=150 and all(v<=2 for i,v in enumerate(actual[:3]) if i!=index),result
            print(label+' PASS',flush=True)
        assert hashlib.sha256(runtime_archive()).hexdigest()==digest
        verify_identity(report,args.blender)
        report['status']='passed';report.pop('activeCase',None)
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
