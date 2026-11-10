"""Fractional alpha remains separate from straight/premultiplied image colour."""
import argparse,hashlib,json
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.png import read
from qualify_blender_render_policy import document,expected
from qualify_blender_image_preview import png
from blender_surface_evidence import identity,verify_identity


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--engine',choices=['cycles','eevee'],default='cycles');args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    digest=hashlib.sha256(runtime_archive()).hexdigest();report={'status':'running','sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':digest,'engine':args.engine,'checks':[],
        'oracle':'Literal source RGBA(64,32,16,128). Fixed Cycles treats Non-Color RGB as independent numeric data (RGB/255), including an image tagged premultiplied; unlike Workbench it does not unassociate data colour. sRGB straight colour must round-trip literal encoded RGB independently of constant versus image-sampled coverage. Coverage is alpha128/255. Mean of256 interior pixels at256samples; RGB mean within2bytes and alpha mean within3bytes declared before execution. This is a bounded statistical reference, not exact per-pixel Monte Carlo identity.',
        'fixedPrimarySource':'https://github.com/blender/blender/blob/v5.2.3/intern/cycles/scene/shader_nodes.cpp#L417-L424'}
    target=out/'summary.json';image=out/'fractional.png';png(image,[[64,32,16,128]]*4)
    report.update(identity(out,args.blender))
    try:
        for mode,space,shared in [('straight','Non-Color',True),('channelPacked','Non-Color',True),('premultiplied','Non-Color',True),
                                  ('straight','sRGB',False),('straight','sRGB',True)]:
            label=mode+'-'+space+('-sampled-coverage' if shared else '-constant-coverage')
            report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n')
            d=document();d['size']=[64,64];d['render'].update(samples=256,transparent=True,lightEnergy=0,worldStrength=0)
            if args.engine=='eevee':
                d['render'].pop('samples');d['render']['renderer']={'kind':'eevee','samples':256}
            d['cameras'][0].update(scale=2,focalPoint=[0,0,0]);p=d['production'];p['materialGraphs']=[]
            p['images']=[{'id':'image','file':str(image),'colourSpace':space,'alphaMode':mode}]
            p['surfaceMaterials']=[{'id':'surface','baseColour':{'kind':'constant','value':[0,0,0]},'ior':{'kind':'constant','value':1},
                'samplers':[{'id':'image','image':'image','filter':'nearest'}],
                'coverage':{'kind':'sample','sampler':'image','channel':'alpha'},
                'emission':{'colour':{'kind':'sample','sampler':'image'},'strength':{'kind':'constant','value':1}}}]
            if not shared:p['surfaceMaterials'][0]['coverage']={'kind':'constant','value':128/255}
            p['meshData']=[{'object':'patch','uvMaps':[{'name':'UV','method':'planar','origin':[-1,-1,0],'size':[2,2]}]}]
            directory=out/label;run(d,directory,executable=args.blender,timeout=180)
            with location_context({'blender':args.blender}):assert verify(directory)['verified']
            receipt=json.loads((directory/'verification.json').read_text());path=next(Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='image')
            width,height,data=read(path);pixels=[list(data[4*(y*width+x):4*(y*width+x)+4]) for y in range(24,40) for x in range(24,40)]
            mean=[sum(row[k] for row in pixels)/len(pixels) for k in range(4)]
            reference=(expected([v/255 for v in [64,32,16]],0)[:3] if space=='Non-Color' else [64,32,16])+[128]
            result={'case':label,'interiorPixels':len(pixels),'samples':256,'meanRGBA':mean,'independentExpectedRGBA':reference}
            report['checks'].append(result);target.write_text(json.dumps(report,indent=2)+'\n')
            assert all(abs(a-b)<=2 for a,b in zip(mean[:3],reference[:3])) and abs(mean[3]-128)<=3,result
            print(label+' PASS',flush=True)
        assert hashlib.sha256(runtime_archive()).hexdigest()==digest
        verify_identity(report,args.blender)
        report['status']='passed';report.pop('activeCase',None)
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
