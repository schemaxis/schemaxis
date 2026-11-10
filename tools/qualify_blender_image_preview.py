"""Captured-image Workbench previews with independent UV/encoded pixel oracles."""
import argparse,copy,hashlib,json,struct,subprocess,zlib
from pathlib import Path
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.png import read
from qualify_blender_render_policy import document,settings,expected,COLOUR,VIEWPORT

FIRST=[[64,128,192,255],[96,160,224,255],[128,192,64,255],[192,64,128,255]]
SECOND=[[0,255,255,255],[255,0,255,255],[255,255,255,255],[0,0,0,255]]
ALPHA=[[255,0,0,0],[0,255,0,255],[0,0,255,255],[255,255,0,255]]
FRACTIONAL=[[64,32,16,128]]*4


def png(path,colours):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+b''.join(bytes(colours[(y//4)*2+x//4]) for x in range(8)) for y in range(8))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',8,8,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))


def uv(shift=0):return [[[shift,0],[1+shift,0],[1+shift,1],[shift,1]]]


def fixture(inputs):
    d=settings(document(),'workbench','texture');d['cameras'][0]['scale']=2
    p=d['production'];p['images']=[{'id':name,'file':str(inputs/(name+'.png'))} for name in ['first','second','alpha','fractional']]
    g=p['materialGraphs'][0];g['displayTexture']={'kind':'image','image':'first'}
    # Preview selection is independent of both the shader and its other images.
    g['nodes']+=[{'id':'shaderFirst','kind':'image','properties':{'image':'first'}},{'id':'shaderSecond','kind':'image','properties':{'image':'second'}}]
    p['meshData']=[{'object':'patch','activeUV':'base','renderUV':'shifted','uvMaps':[{'name':'base','method':'coordinates','coordinates':uv()},{'name':'shifted','method':'coordinates','coordinates':uv(.5)}]}]
    return d


def rgba(directory,points):
    receipt=json.loads((directory/'verification.json').read_text());path=next(Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='image')
    w,h,data=read(path)
    return [list(data[4*(y*w+x):4*(y*w+x)+4]) for x,y in points]


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False);inputs=out/'inputs';inputs.mkdir()
    for name,colours in [('first',FIRST),('second',SECOND),('alpha',ALPHA),('fractional',FRACTIONAL)]:png(inputs/(name+'.png'),colours)
    # Pillow is a qualification-only independent JPEG encoder/decoder. The
    # adaptor itself and discovery retain their dependency-free host contract.
    from PIL import Image,__version__ as pillow_version
    jpeg=inputs/'colour.jpg';Image.new('RGB',(8,8),(64,128,192)).save(jpeg,quality=100,subsampling=0)
    with Image.open(jpeg) as independent:jpeg_rgb=list(independent.convert('RGB').getpixel((2,2)))
    digest=hashlib.sha256(runtime_archive()).hexdigest();tool=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':digest,'qualifierSha256':tool,'independentJPEGDecoder':{'library':'Pillow','version':pillow_version,'decodedRGB':jpeg_rgb},'inputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()},'checks':[]};target=out/'summary.json'
    points=[(8,8),(24,8),(8,24),(24,24)]
    def execute(label,value,wanted,locations=points):
        report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n')
        assert hashlib.sha256(runtime_archive()).hexdigest()==digest
        directory=out/label;run(value,directory,executable=args.blender,timeout=360)
        with location_context({'blender':args.blender}):assert verify(directory)['verified']
        actual=rgba(directory,locations)
        assert len(actual)==len(wanted) and all(abs(a-b)<=1 for colour,reference in zip(actual,wanted) for a,b in zip(colour,reference)),(label,actual,wanted)
        report['checks'].append({'label':label,'points':locations,'encodedRGBA':actual,'independentExpectedRGBA':wanted,'maximumByteError':1});target.write_text(json.dumps(report,indent=2)+'\n');return directory
    # Channel-packed channels are independent, including zero alpha:
    # https://docs.blender.org/api/5.2/bpy.types.Image.html#bpy.types.Image.alpha_mode
    try:
        baseline=fixture(inputs);execute('first-active-base-render-shifted',baseline,FIRST)
        d=copy.deepcopy(baseline);d['production']['materialGraphs'][0]['displayTexture']['image']='second';execute('second-preview',d,SECOND)
        d=copy.deepcopy(baseline);d['production']['meshData'][0].update(activeUV='shifted',renderUV='base');execute('active-shifted-render-base',d,[FIRST[1],FIRST[0],FIRST[3],FIRST[2]])
        fallback=[expected(VIEWPORT,0)]*4
        d=copy.deepcopy(baseline);d['production']['materialGraphs'][0]['displayTexture']={'kind':'none'};execute('explicit-swatch-fallback',d,fallback)
        d=copy.deepcopy(baseline);d['production']['meshData']=[];execute('missing-uv-swatch-fallback',d,fallback)
        d=copy.deepcopy(baseline);d['production']['images'][0]['colourSpace']='Non-Color';execute('linear-data-image',d,[expected([x/255 for x in c[:3]],0) for c in FIRST])
        for mode in ['straight','premultiplied','channelPacked','ignore']:
            d=copy.deepcopy(baseline);d['production']['materialGraphs'][0]['displayTexture']['image']='alpha';d['production']['images'][2]['alphaMode']=mode
            wanted=copy.deepcopy(ALPHA);wanted[0]=[255,0,0,255] if mode in ('ignore','channelPacked') else expected([.05,.05,.05],0)
            execute('alpha-'+mode,d,wanted)
        for mode,divisor in [('straight',255),('premultiplied',128)]:
            d=copy.deepcopy(baseline);d['production']['materialGraphs'][0]['displayTexture']['image']='fractional'
            d['production']['images'][3].update(alphaMode=mode,colourSpace='Non-Color')
            execute('fractional-linear-'+mode,d,[expected([x/divisor for x in FRACTIONAL[0][:3]],0)]*4)
        d=copy.deepcopy(baseline);d['production']['images'].append({'id':'jpeg','file':str(jpeg)})
        d['production']['materialGraphs'][0]['displayTexture']['image']='jpeg';execute('independently-decoded-jpeg',d,[jpeg_rgb+[255]]*4)
        d=copy.deepcopy(baseline);d['render']={'samples':1,'threads':2,'colourManagement':{'view':{'kind':'standard'}}};execute('shader-independent-preview',d,[expected(COLOUR,0)]*4)
        # A materially different two-panel scientific illustration combines separate
        # preview materials, typed fields and independently selected UV maps.
        d=copy.deepcopy(baseline);d['size']=[64,32];d['cameras'][0]['scale']=5;p=d['production']
        left=p['objects'][0];left['location']=[-1.2,0,0]
        right=copy.deepcopy(left);right.update(id='secondPanel',location=[1.2,0,0],material='secondSurface');p['objects'].append(right)
        g=copy.deepcopy(p['materialGraphs'][0]);g['id']='secondSurface';g['displayTexture']['image']='second';p['materialGraphs'].append(g)
        p['meshData'][0]['attributes']=[{'name':'temperature','kind':'float','domain':'POINT','mode':'dense','values':[12,14,18,16]}]
        field=copy.deepcopy(p['meshData'][0]);field.update(object='secondPanel',activeUV='shifted',renderUV='base');p['meshData'].append(field)
        locations=[(10,10),(23,10),(10,22),(23,22),(41,10),(54,10),(41,22),(54,22)]
        execute('scientific-two-panel-composition',d,FIRST+[SECOND[1],SECOND[0],SECOND[3],SECOND[2]],locations)
        assert hashlib.sha256(runtime_archive()).hexdigest()==digest and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==tool
        report['status']='passed';report.pop('activeCase',None);print(json.dumps({'status':'passed','cases':len(report['checks'])}))
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
