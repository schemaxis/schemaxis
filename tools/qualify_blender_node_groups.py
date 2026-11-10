"""Native reusable interface, nested graph, edit and asset-reuse acceptance."""
import argparse
import base64
import copy
import json
import math
from pathlib import Path
import subprocess
import tempfile
from schemaxis.adaptors.blender.adaptor import run
from schemaxis.adaptors.blender.node_groups import DOMAINS


def close(found,expected):assert len(found)==len(expected) and all(math.isclose(a,b,abs_tol=2e-5,rel_tol=1e-6) for a,b in zip(found,expected)),(found,expected)


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output).absolute();out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[1]
    baseline=json.loads((root/'examples/schemaxis/blender-node-groups.json').read_text());results=[]
    r=run(baseline,out/'connected',executable=a.blender,timeout=240)
    prod=json.loads((out/'connected'/'verification.json').read_text())['states'][0]['production'];close(prod['samples'][0]['objects']['housing']['bounds'],[-40,40,-25,25,5,25])
    results.append({'case':'threeDomainsNestedGeometry','result':r,'literalBounds':[-40,40,-25,25,5,25]})
    d=copy.deepcopy(baseline);d['prepareOnly']=True;d['production']['exports']=[]
    wrapper=next(g for g in d['production']['nodeGroups'] if g['id']=='LiftTwice');wrapper['nodes'][1]['values']={'twist':[0,0,math.pi/2]}
    r=run(d,out/'rotation',executable=a.blender,timeout=180)
    prod=json.loads((out/'rotation'/'verification.json').read_text())['states'][0]['production'];close(prod['samples'][0]['objects']['housing']['bounds'],[-25,25,-40,40,5,25])
    results.append({'case':'typedEulerRotationEffect','result':r,'literalBounds':[-25,25,-40,40,5,25]})
    # The reusable compositor group changes actual pixels, not just socket state.
    d=copy.deepcopy(baseline);d['production']['compositor']['nodes'][1]['values']={'exposure':1};d['production']['exports']=[]
    r=run(d,out/'brighter',executable=a.blender,timeout=240)
    from schemaxis.png import read
    def intensity(directory):
        receipt=json.loads((directory/'verification.json').read_text());path=next(a['file'] for a in receipt['artifacts'] if a['kind']=='image');w,h,pixels=read(path);channels=len(pixels)//(w*h)
        return sum(pixels[i] for i in range(len(pixels)) if i%channels<3)/(w*h*3)
    original_mean=intensity(out/'connected');bright_mean=intensity(out/'brighter');assert bright_mean>original_mean+1,(original_mean,bright_mean)
    results.append({'case':'compositorPixelEffect','result':r,'meanPixels':[original_mean,bright_mean]})
    d=copy.deepcopy(baseline);d['prepareOnly']=True;s=d['production'];s['exports']=[];s['collections']=[{'id':'parts'}];s['objects'].append({'id':'typeAnchor','kind':'empty'})
    pixel=out/'pixel.png';pixel.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='));s['images']=[{'id':'pixel','file':str(pixel)}]
    for family,kinds in DOMAINS.items():
        inputs=[];outputs=[];links=[]
        for kind in sorted(kinds):
            interface={'id':kind,'kind':kind}
            if kind in ('number','integer','boolean','vector','colour','string','rotation'):
                interface['default']={'number':.25,'integer':7,'boolean':True,'vector':[1,2,3],'colour':[.1,.2,.3,1],'string':'interface-label','rotation':[.1,.2,.3]}[kind]
            if kind in ('object','collection','material') or kind=='image' and family=='geometry':interface['default']={'object':'typeAnchor','collection':'parts','material':'finish','image':'pixel'}[kind]
            inputs.append(interface);outputs.append({'id':kind,'kind':kind});links.append({'from':{'node':'in','socket':kind},'to':{'node':'out','socket':kind}})
        s['nodeGroups'].append({'id':'Types'+family,'family':family,'inputs':inputs,'outputs':outputs,'nodes':[{'id':'in','kind':'input'},{'id':'out','kind':'output'}],'links':links})
    r=run(d,out/'interfaces',executable=a.blender,timeout=180);results.append({'case':'all29DomainTypeMappings','result':r,'domainTypes':sum(map(len,DOMAINS.values()))})
    # Native editing is deliberately adopted as a new input rather than forging
    # the original workflow's verification contract.
    edited=out/'edited.blend'
    with tempfile.TemporaryDirectory(prefix='schemaxis-group-edit-') as temp:
        script=Path(temp)/'edit_group.py';script.write_text('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"connected"/"0000.blend")!r},use_scripts=False)\n'+"bpy.data.node_groups['lifted'].nodes['lift'].inputs['lift'].default_value=(0,0,4)\nbpy.context.view_layer.update()\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(edited)!r})\n')
        native=subprocess.run([a.blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script)],timeout=60,capture_output=True,text=True);assert native.returncode==0,(native.stdout,native.stderr)
    d={'version':'schemaxis.blender.production/1','id':'edited-groups','prepareOnly':True,'production':{'units':'millimetres','assets':[{'id':'product','file':str(edited),'format':'blend','sourceUnits':'millimetres'}]}}
    r=run(d,out/'reused',executable=a.blender,timeout=180)
    prod=json.loads((out/'reused'/'verification.json').read_text())['states'][0]['production'];bounds=prod['samples'][0]['objects']['product']['bounds'];close(bounds,[-40,40,-25,25,8,28])
    results.append({'case':'editedNestedGroupNativeAssetReuse','result':r,'literalBounds':[-40,40,-25,25,8,28]})
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
