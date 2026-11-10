"""Independent region/palette pixels and editable native surface assignments."""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from qualify_blender_render_policy import document,settings,expected
from qualify_blender_image_preview import rgba,png

COLOURS={'red':[1,0,0],'blue':[0,0,1],'green':[0,1,0],'yellow':[1,1,0]}


def graph(name):
    return {'id':name,'viewportColour':COLOURS[name],'nodes':[{'id':'colour','kind':'emission','values':{'colour':[*COLOURS[name],1]}},{'id':'output','kind':'output'}],
        'links':[{'from':{'node':'colour','socket':'shader'},'to':{'node':'output','socket':'surface'}}]}


def fixture(engine='cycles',linked=False):
    d=settings(document(),engine);d['size']=[64,32];d['cameras'][0]['scale']=4 if linked else 2
    p=d['production'];p['materialGraphs']=[graph(n) for n in COLOURS]
    p['objects']=[{'id':'patch','kind':'mesh','vertices':[[-.8,-.8,0],[0,-.8,0],[0,.8,0],[-.8,.8,0],[.8,-.8,0],[.8,.8,0]],'faces':[[0,1,2,3],[1,4,5,2]],'material':'red','location':[-1,0,0] if linked else [0,0,0]}]
    layout={'id':'finish','kind':'layout','object':'patch','sharing':'shared' if linked else 'refuse',
        'slots':[{'id':'body','material':'red'},{'id':'label','material':'blue'}],'defaultSlot':'body',
        'regions':[{'slot':'label','selection':{'kind':'faceIndices','indices':[1]}}]}
    p['materialAssignments']=[layout]
    if linked:
        p['objects'].append({'id':'other','kind':'instance','source':'patch','location':[1,0,0]})
        p['materialAssignments'].append({'id':'edition','kind':'override','object':'other','layout':'finish','slots':[{'id':'label','material':'yellow'},{'id':'body','material':'green'}]})
    return d


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    archive=hashlib.sha256(runtime_archive()).hexdigest();tool=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':archive,'qualifierSha256':tool,'checks':[],'refusals':[]}
    target=out/'summary.json'
    def write():target.write_text(json.dumps(report,indent=2)+'\n')
    def execute(label,d,locations=None,colours=None,indices=None):
        report['activeCase']=label;write();assert hashlib.sha256(runtime_archive()).hexdigest()==archive
        directory=out/label;run(d,directory,executable=args.blender,timeout=240)
        with location_context({'blender':args.blender}):assert verify(directory)['verified']
        current=json.loads((directory/'reopened.json').read_text())['production'][0]['materialAssignments']
        if indices is not None:assert [r['indices'] for r in current]==indices,(label,current,indices)
        record={'label':label,'indices':[r['indices'] for r in current],'owners':[r['owners'] for r in current]}
        if locations:
            found=rgba(directory,locations);wanted=[expected(c,0) for c in colours]
            assert all(abs(x-y)<=1 for a,b in zip(found,wanted) for x,y in zip(a,b)),(label,found,wanted)
            record.update(points=locations,encodedRGBA=found,independentExpectedRGBA=wanted,maximumByteError=1)
        report['checks'].append(record);write();print(label+' PASS',flush=True);return directory
    try:
        for engine in ('cycles','workbench'):
            execute('two-regions-'+engine,fixture(engine),[(27,16),(37,16)],[COLOURS['red'],COLOURS['blue']],[[0,1]])
            execute('linked-palette-'+engine,fixture(engine,True),[(11,16),(21,16),(43,16),(53,16)],list(COLOURS.values()),[[0,1],[0,1]])
        d=fixture('workbench',True);d['production']['materialAssignments']=d['production']['materialAssignments'][:1];d['production']['materialAssignments'][0]['sharing']='copy'
        execute('isolated-layout-retains-other-owner',d,[(11,16),(21,16),(43,16),(53,16)],[COLOURS[n] for n in ('red','blue','red','red')],[[0,1]])
        inputs=out/'inputs';inputs.mkdir()
        for name,colour in COLOURS.items():png(inputs/(name+'.png'),[[round(c*255) for c in colour]+[255]]*4)
        d=fixture('workbench',True);p=d['production'];d['render']['renderer']['colourSource']={'kind':'texture'}
        p['images']=[{'id':name+'Image','file':str(inputs/(name+'.png'))} for name in COLOURS]
        for g in p['materialGraphs']:
            g['displayTexture']={'kind':'image','image':g['id']+'Image'}
            # Different shader colours prove the preview selection is per-slot.
            g['nodes'][0]['values']['colour']=[.2,.2,.2,1]
        coordinates=[[[0,0],[1,0],[1,1],[0,1]]]*2
        p['meshData']=[{'object':'patch','sharing':'shared','activeUV':'labelUV','uvMaps':[{'name':'labelUV','method':'coordinates','coordinates':coordinates}]}]
        execute('linked-per-face-captured-images',d,[(11,16),(21,16),(43,16),(53,16)],list(COLOURS.values()),[[0,1],[0,1]])
        d=fixture('workbench');d['prepareOnly']=True;d['production']['meshEdits']=[{'object':'patch','steps':[{'id':'triangles','kind':'triangulate','selection':{'kind':'all'}}]}]
        d['production']['materialAssignments'][0]['regions'][0]['selection']={'kind':'faceBox','minimum':[0,-1,-1],'maximum':[1,1,1]}
        d['production']['meshData']=[{'object':'patch','attributes':[{'name':'temperature','kind':'float','mode':'constant','domain':'FACE','value':17}],'uvMaps':[{'name':'labelUV','method':'planar'}]}]
        execute('post-topology-field-uv',d,indices=[[0,0,1,1]])
        d=fixture();d['prepareOnly']=True;p=d['production'];p['objects']=[{'id':'patch','kind':'spline','splines':[{'id':'lower','kind':'POLY','points':[{'position':[-1,-.5,0]},{'position':[1,-.5,0]}]},{'id':'upper','kind':'POLY','points':[{'position':[-1,.5,0]},{'position':[1,.5,0]}]}],'bevel':{'kind':'round','depth':.1}}]
        p['materialAssignments'][0]['regions'][0]['selection']={'kind':'splines','names':['upper']};execute('named-splines',d,indices=[[0,1]])
        d=fixture();d['prepareOnly']=True;p=d['production'];p['objects']=[{'id':'patch','kind':'text','body':'Aé中Z'}]
        p['materialAssignments'][0]['regions'][0]['selection']={'kind':'characters','start':1,'end':3};execute('unicode-text',d,indices=[[0,1,1,0]])
        # Refusals exercise native ownership/identity admission, not only schema.
        for label,mutation in [('implicit-shared-layout',lambda p:p['materialAssignments'][0].update(sharing='refuse')),
            ('unlinked-palette',lambda p:p['objects'][1].update(linked=False)),
            ('legacy-binding-conflict',lambda p:p.update(materialBindings=[{'object':'patch','material':'red'}]))]:
            d=fixture(linked=True);d['prepareOnly']=True;mutation(d['production'])
            try:run(d,out/label,executable=args.blender,timeout=180)
            except SchemaxisError as exc:report['refusals'].append({'label':label,'code':exc.fault.code});write()
            else:raise AssertionError('accepted '+label)
        assert hashlib.sha256(runtime_archive()).hexdigest()==archive and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==tool
        report['status']='passed';report.pop('activeCase',None)
    finally:
        if report['status']=='running':report['status']='failed'
        write()


if __name__=='__main__':main()
