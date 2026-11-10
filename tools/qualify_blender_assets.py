"""Native asset round-trip: editable packed blend and complete binary GLB reuse."""
import argparse
import base64
import json
import math
from pathlib import Path
import struct
import zlib
from schemaxis.adaptors.blender.adaptor import run


def png(path):
    def chunk(kind,payload):return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\xff\0\0\0\xff\0\0\0\0\xff\xff\xff\0'))+chunk(b'IEND',b''))


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',required=True);args=p.parse_args();directory=Path(args.output).absolute();directory.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];producer=json.loads((root/'examples/schemaxis/blender-production.json').read_text());spec=producer['scenes'][0]['production']
    spec['currentFrame']=1;spec['objects']=[{'id':'motion','kind':'empty'},{'id':'copy','kind':'instance','source':'box','location':[4,0,0]}];spec['collections']=[];spec['exports']=[{'id':f,'format':f,'objects':['motion'],'frame':1} for f in ('glb','obj','ply','stl','usd')];spec['renderFrames']=[]
    producer['nodes']=[{'id':'paint','filter':'material'}]
    vertices=[[-1,-1,-1],[-1,-1,1],[-1,1,-1],[-1,1,1],[1,-1,-1],[1,-1,1],[1,1,-1],[1,1,1]]
    faces=[list(reversed(f)) for f in [[0,4,6,2],[1,3,7,5],[0,1,5,4],[2,6,7,3],[0,2,3,1],[4,5,7,6]]]
    spec['objects'].insert(0,{'id':'box','kind':'mesh','vertices':vertices,'faces':faces,'uv':[[[0,0],[1,0],[1,1],[0,1]] for _ in faces],'material':'paint'})
    spec['rigs']=[{'id':'skeleton','bones':[{'id':'root','head':[0,0,0],'tail':[0,0,1]}]}]
    spec['skin']=[{'object':'box','rig':'skeleton','weights':[{'bone':'root','vertices':list(range(8)),'weight':1}]}]
    spec['tracks'].append({'object':'skeleton','bone':'root','channel':'location','keys':[{'frame':1,'value':[0,0,0]},{'frame':11,'value':[0,2,0]}]})
    image=directory/'texture.png';png(image);spec['images']=[{'id':'texture','file':str(image),'pack':True}]
    graph=spec['materialGraphs'][0];graph['nodes'][0]={'id':'checker','kind':'image','properties':{'image':'texture'}}
    result=run(producer,directory/'producer',executable=args.blender,timeout=180);results=[{'case':'producer','result':result}]
    binary=(directory/'producer'/'0000-export-glb.glb').read_bytes();offset=12;gltf=None;payload=None
    while offset<len(binary):
        length,kind=struct.unpack_from('<II',binary,offset);offset+=8;chunk=binary[offset:offset+length];offset+=length
        if kind==0x4e4f534a:gltf=json.loads(chunk)
        elif kind==0x004e4942:payload=chunk
    gltf['buffers'][0]['uri']='data:application/octet-stream;base64,'+base64.b64encode(payload).decode();gltf_file=directory/'embedded.gltf';gltf_file.write_text(json.dumps(gltf))
    for format in ('glb','blend','gltf','stl','ply','obj','usd'):
        source=gltf_file if format=='gltf' else directory/'producer'/('0000.blend' if format=='blend' else '0000-export-'+format+('.usda' if format=='usd' else '.'+format))
        doc={'version':'schemaxis.blender/1','nodes':[{'id':'anchor','filter':'material'}],'scenes':[{'id':'reuse','visible':['product'],'prepareOnly':True,'render':{'samples':1,'threads':1},'images':[{'id':'preview','size':[32,32],'cameras':[{'direction':[1,-2,1]}]}],'production':{'frameStart':1,'frameEnd':11,'currentFrame':6,'assets':[{'id':'product','file':str(source),'format':format,'sourceUnits':'metres','location':[10,0,0]}],'intents':[{'id':'show','kind':'turntable','objects':['product'],'angleDegrees':180}],'renderFrames':[1,6,11],'exports':[{'id':f,'format':f,'objects':['product'],'frame':6} for f in ('glb','obj','ply','stl','usd')]}}]}
        scene=doc['scenes'][0];doc={'version':'schemaxis.blender.production/1','id':'reuse','visible':scene['visible'],'prepareOnly':True,'render':scene['render'],'size':[32,32],'production':scene['production']}
        result=run(doc,directory/('reuse-'+format),executable=args.blender,timeout=180);receipt=json.loads((directory/('reuse-'+format)/'verification.json').read_text());prod=receipt['states'][0]['production']
        samples={s['frame']:s for s in prod['samples']};intent=prod['intents'][0]
        assert all(math.isclose(a,b,abs_tol=1e-5) for a,b in zip(intent['pivot'],[12,0,0])),intent
        bounds=samples[6]['objects']['product']['bounds'];expected=[11,13,-3,3,-1,1] if format!='blend' else [11,13,-1,5,-1,2]
        assert all(math.isclose(a,b,abs_tol=2e-5) for a,b in zip(bounds,expected)),(format,bounds,expected)
        member_types=[m['type'] for m in prod['assets'][0]['members']];assert member_types.count('MESH')>=1,member_types
        if format=='blend':assert member_types.count('ARMATURE')==1,member_types
        results.append({'case':'reuse-'+format,'result':result,'literalPivot':[12,0,0],'literalFrame6Bounds':expected,'memberTypes':member_types})
    (directory/'summary.json').write_text(json.dumps({'status':'passed','cases':results,'scope':'packed texture and animated hierarchy retained by native blend; GLB retains static imported hierarchy/materials; all five geometry formats +3renderedframes + fresh current-byte project verification'},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
