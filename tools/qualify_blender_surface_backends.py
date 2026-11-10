"""Built-in OSL Smart filtering with an independent periodic B-spline oracle."""
import argparse,json
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.configuration import location_context
from qualify_blender_render_policy import document,expected,pixel
from qualify_blender_image_preview import png
from blender_surface_evidence import identity,verify_identity


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    report={'status':'running',**identity(out,args.blender),'checks':[]};target=out/'summary.json'
    image=out/'stripes.png';png(image,[[0,0,0,255],[128,128,128,255],[0,0,0,255],[128,128,128,255]])
    try:
        for label,interpolation,u,linear in [('nearest-black','nearest',.4375,0),('nearest-bright','nearest',.5625,128/255),
                ('linear','linear',.4375,0),('cubic','cubic',.4375,128/255/6),('smart','smart',.4375,128/255/6)]:
            d=document();d['render'].update(renderer={'kind':'cycles','shadingSystem':'osl'},worldStrength=0,lightEnergy=0)
            p=d['production'];p['materialGraphs']=[]
            p['images']=[{'id':'stripes','file':str(image),'colourSpace':'Non-Color','alphaMode':'channelPacked'}]
            p['surfaceMaterials']=[{'id':'surface','ior':{'kind':'constant','value':1},'baseColour':{'kind':'constant','value':[0,0,0]},
                'samplers':[{'id':'stripe','image':'stripes','filter':interpolation,'coordinates':{'kind':'uv','transform':{'tile':[0,0],'offset':[u,.25]}}}],
                'emission':{'colour':{'kind':'sample','sampler':'stripe'},'strength':{'kind':'constant','value':1}}}]
            p['meshData']=[{'object':'patch','uvMaps':[{'name':'UV','method':'planar','origin':[-1,-1,0],'size':[2,2]}]}]
            directory=out/label;run(d,directory,executable=args.blender,timeout=180)
            with location_context({'blender':args.blender}):assert verify(directory)['verified']
            actual=pixel(directory);wanted=expected([linear]*3,0)
            receipt=json.loads((directory/'reopened.json').read_text())
            assert receipt['states'][0]['render']['renderer']=={'kind':'cycles','shadingSystem':'osl'},receipt['states'][0]['render']
            item={'case':label,'actualRGBA':actual,'independentExpectedRGBA':wanted,'maximumByteError':1,
                'reference':'The fixture is8x8 with four black columns then four128 columns. At u=3.5/8,v=.25, B-spline weights1/6,4/6,1/6,0 have one bright neighbour:128/255/6. Nearest/bilinear are0; nearest at4.5/8 is128/255. Zero coordinate derivatives imply magnification.'}
            report['checks'].append(item);target.write_text(json.dumps(report,indent=2)+'\n')
            assert all(abs(a-b)<=1 for a,b in zip(actual,wanted)),item
            print(label+' PASS',flush=True)
        verify_identity(report,args.blender);report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
