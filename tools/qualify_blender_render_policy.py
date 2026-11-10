"""Engine/display acceptance with independent encoded PNG colour expectations."""
import argparse,copy,json,math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.adaptors.blender.render_job import run as render_saved
from schemaxis.png import read
from schemaxis.configuration import location_context

COLOUR=[.04,.09,.25]
VIEWPORT=[.2,.03,.06]
OBJECT=[.05,.3,.02]


def document(renderer='cycles',exposure=0,view='standard',source='material'):
    return {'version':'schemaxis.blender.production/1','size':[32,32],
        'cameras':[{'direction':[0,0,1],'up':[0,1,0]}],
        'render':{'samples':1,'threads':2,'renderer':{'kind':'cycles'},'colourManagement':{'view':{'kind':view},'exposure':exposure}},
        'production':{'objects':[{'id':'patch','kind':'mesh','vertices':[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],'faces':[[0,1,2,3]],'material':'surface','displayColour':{'kind':'colour','value':OBJECT}}],
            'materialGraphs':[{'id':'surface','viewportColour':VIEWPORT,'nodes':[{'id':'emit','kind':'emission','values':{'colour':[*COLOUR,1]}},{'id':'finish','kind':'output'}],
                'links':[{'from':{'node':'emit','socket':'shader'},'to':{'node':'finish','socket':'surface'}}]}]}}


def settings(d,engine,source='material'):
    r=d['render']
    if engine!='cycles':r.pop('samples');r['renderer']={'kind':engine}
    if engine=='eevee':r['renderer']['samples']=1
    if engine=='workbench':r['renderer'].update(lighting={'kind':'flat'},colourSource={'kind':source},antiAliasing='OFF')
    return d


def pixel(directory):
    receipt=json.loads((directory/'verification.json').read_text())
    paths=[Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='image']
    assert len(paths)==1,paths
    w,h,data=read(paths[0]);return list(data[4*((h//2)*w+w//2):4*((h//2)*w+w//2)+4])


def expected(colour,exposure):
    def encode(x):return 12.92*x if x<=.0031308 else 1.055*x**(1/2.4)-.055
    return [round(255*min(1,max(0,encode(c*2**exposure)))) for c in colour]+[255]


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False)
    report={'status':'running','checks':[]};summary=out/'summary.json'
    def record(value):report['checks'].append(value);summary.write_text(json.dumps(report,indent=2)+'\n')
    def execute(label,d,wanted=None):
        directory=out/label;run(d,directory,executable=a.blender,timeout=360)
        with location_context({'blender':a.blender}):assert verify(directory)['verified']
        actual=pixel(directory)
        if wanted is not None:assert all(abs(x-y)<=1 for x,y in zip(actual,wanted)),(label,actual,wanted)
        record({'label':label,'centreEncodedRGBA':actual,'expectedRGBA':wanted,'maximumByteError':1 if wanted is not None else None});return directory,actual
    baseline=None
    for engine in ('cycles','eevee','workbench'):
        for exposure in (0,1):
            directory,_=execute(engine+'-exposure-'+str(exposure),settings(document(exposure=exposure),engine),expected(VIEWPORT if engine=='workbench' else COLOUR,exposure))
            if engine=='cycles' and exposure==0:baseline=directory
    execute('workbench-object-colour',settings(document(),'workbench','object'),expected(OBJECT,0))
    for kind,colour,wanted in [('colour',[.13,.04,.24,1],expected([.13,.04,.24],0)),('byteColour',[54,88,142,255],[54,88,142,255])]:
        d=settings(document(),'workbench','attribute')
        d['production']['meshData']=[{'object':'patch','activeColour':'chosen','renderColour':'chosen','attributes':[{'name':'unused','kind':'colour','domain':'CORNER','mode':'constant','value':[.8,.1,.1,1]},{'name':'chosen','kind':kind,'domain':'POINT','mode':'constant','value':colour}]}]
        execute('workbench-attribute-'+kind,d,wanted)
    for active,render,colour in [('chosen','unused',[.13,.04,.24]),('unused','chosen',[.8,.1,.1])]:
        d=settings(document(),'workbench','attribute')
        d['production']['meshData']=[{'object':'patch','activeColour':active,'renderColour':render,'attributes':[{'name':'unused','kind':'colour','domain':'POINT','mode':'constant','value':[.8,.1,.1,1]},{'name':'chosen','kind':'colour','domain':'POINT','mode':'constant','value':[.13,.04,.24,1]}]}]
        execute('attribute-active-'+active+'-render-'+render,d,expected(colour,0))
    for cull in (False,True):
        d=settings(document(),'workbench','object');d['production']['objects'][0]['faces'][0].reverse();d['render']['renderer']['backfaceCulling']=cull
        execute('workbench-backface-'+str(cull),d,expected([.05,.05,.05] if cull else OBJECT,0))
    d=settings(document(),'workbench','object');d['cameras'][0]['scale']=4
    source=d['production']['objects'][0];source['location']=[-1,0,0];source['vertices']=[[-.3,-.3,0],[.3,-.3,0],[.3,.3,0],[-.3,.3,0]]
    d['production']['objects']+=[{'id':'inherited','kind':'instance','source':'patch'},{'id':'override','kind':'instance','source':'patch','location':[1,0,0],'displayColour':{'kind':'colour','value':[.4,.08,.12]}}]
    directory,_=execute('workbench-instance-display-colours',d,expected(OBJECT,0))
    receipt=json.loads((directory/'verification.json').read_text());png=next(Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='image');w,h,data=read(png)
    for x,colour in [(8,OBJECT),(16,OBJECT),(24,[.4,.08,.12])]:
        actual=list(data[4*((h//2)*w+x):4*((h//2)*w+x)+4]);assert all(abs(a-b)<=1 for a,b in zip(actual,expected(colour,0))),(x,actual,colour)
    d=settings(document(),'workbench','object');d['render']['renderer']['background']=OBJECT
    directory,_=execute('uniform-valid-image',d,expected(OBJECT,0))
    receipt=json.loads((directory/'verification.json').read_text());png=next(Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='image');w,h,data=read(png)
    assert len({tuple(data[i:i+4]) for i in range(0,len(data),4)})==1
    from schemaxis.adaptors.blender.production_job import lower
    execute('authored-dag-workbench',lower(settings(document(),'workbench','object')),expected(OBJECT,0))
    # The saved-scene route must compose with production-only geometry, whose
    # visible roots are deliberately absent from the mesh DAG node list.
    receipt=json.loads((baseline/'verification.json').read_text());scene=next(Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='scene')
    saved={'version':'schemaxis.blender.render/1','sceneFile':str(scene),'size':[32,32],'cameras':[{'direction':[0,0,1],'up':[0,1,0]}],'render':{'threads':2,'renderer':{'kind':'workbench','lighting':{'kind':'flat'},'colourSource':{'kind':'object'},'antiAliasing':'OFF'},'colourManagement':{'view':{'kind':'standard'},'exposure':1}}}
    directory=out/'saved-production-workbench';render_saved(saved,directory,executable=a.blender,timeout=360);actual=pixel(directory);wanted=expected(OBJECT,1);assert all(abs(x-y)<=1 for x,y in zip(actual,wanted)),(actual,wanted);record({'label':'saved-production-workbench','centreEncodedRGBA':actual,'expectedRGBA':wanted})
    # Tone maps are qualified by actual native readback plus nontrivial output
    # changes, without treating a duplicated implementation as an exact oracle.
    pixels={}
    for view in ('agx','neutral','aces13','aces20'):
        _,actual=execute('view-'+view,document(view=view));pixels[view]=actual
    assert len({tuple(p) for p in pixels.values()})>=3,pixels
    report['status']='passed';summary.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','checks':len(report['checks'])}))

if __name__=='__main__':main()
