"""Native mesh-field, UV, sharing, saved-edit and neutral handoff acceptance."""
import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
import tempfile
import io
import zipfile
from schemaxis.adaptors.blender.adaptor import run
from schemaxis.adaptors.blender.mesh_data import CHANNELS
from schemaxis.errors import SchemaxisError


def close(found,expected):assert len(found)==len(expected) and all(math.isclose(a,b,rel_tol=1e-6,abs_tol=2e-5) for a,b in zip(found,expected)),(found,expected)


def native(executable,script):
    with tempfile.TemporaryDirectory(prefix='schemaxis-mesh-') as temp:
        path=Path(temp)/'check.py';path.write_text(script)
        r=subprocess.run([executable,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(path)],timeout=90,capture_output=True,text=True)
        assert r.returncode==0,(r.stdout,r.stderr)


def production(directory):return json.loads((directory/'verification.json').read_text())['states'][0]['production']


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',required=True);p.add_argument('--cad-baseline');p.add_argument('--cad-variant');p.add_argument('--resume',action='store_true');a=p.parse_args()
    out=Path(a.output).absolute();out.mkdir(parents=True,exist_ok=a.resume);repo=Path(__file__).resolve().parents[1];results=[]
    d=json.loads((repo/'examples/schemaxis/blender-mesh-fields.json').read_text())
    from schemaxis.artifacts import runtime_archive
    from schemaxis.adaptors.blender.adaptor import verify
    with zipfile.ZipFile(io.BytesIO(runtime_archive())) as archive:
        trusted={n:archive.read(n) for n in archive.namelist()}
    def execute(label,d):
        directory=out/label;reused=False
        if a.resume and (directory/'result.json').is_file() and json.loads((directory/'result.json').read_text()).get('status')=='succeeded':
            assert json.loads((directory/'authored.json').read_text())==d,(label,'authored input changed')
            with zipfile.ZipFile(directory/'runtime.zip') as archive:
                assert set(archive.namelist())==set(trusted) and all(archive.read(n)==trusted[n] for n in trusted),(label,'trusted source archive changed')
            # Current public verification freshly reopens native bytes. Resume
            # does not accept old self-reported success or an existing output.
            r=verify(directory);assert r['verified'];reused=True
        else:
            if directory.exists():
                n=1
                while (out/(label+'-retry-'+str(n))).exists():n+=1
                directory=out/(label+'-retry-'+str(n))
            r=run(d,directory,executable=a.blender,timeout=180)
        results.append({'case':label,'directory':str(directory),'reusedWithExactSourceAndFreshVerification':reused,'result':r});return production(directory)
    obs=execute('fields',d);close(obs['samples'][0]['objects']['panel']['bounds'],[0,40,0,30,0,4])
    assert obs['meshData'][0]['uvMaps'][0]['coordinates']==[[[0,0],[1,0],[1,1],[0,1]]]
    # The independently parsed GLB contains the deformed surface, physical metres.
    from schemaxis.adaptors.blender.production_outputs import file_geometry
    path=next((out/'fields').glob('*field-panel*.glb'));geometry=file_geometry(path,'glb');close(geometry['bounds'],[0,.04,0,.03,0,.004])
    # Every semantic channel/domain is written non-default and read after reopening.
    types=copy.deepcopy(d);s=types['production'];s['geometryBindings']=[];s['geometryGraphs']=[];s['exports']=[];s['meshData'][0]['attributes']=[]
    counts={'POINT':4,'EDGE':4,'FACE':1,'CORNER':4};values={'float':2.5,'integer':17,'boolean':True,'vector':[1,2,3],'colour':[.1,.2,.3,.4],'byteColour':[17,123,245,200],'vector2':[.25,.75],'quaternion':[0,0,0,1]}
    for kind in CHANNELS:
        for domain,count in counts.items():
            if kind=='vector2' and domain=='CORNER':continue
            for mode in ('constant','dense','sparse'):
                c={'name':kind+domain+mode,'kind':kind,'domain':domain,'mode':mode}
                if mode=='constant':c['value']=values[kind]
                elif mode=='dense':c['values']=[values[kind]]*count
                else:c.update(default=values[kind],entries=[{'index':count-1,'value':values[kind]}])
                s['meshData'][0]['attributes'].append(c)
    typed=execute('types-domains-storage',types);assert len(typed['meshData'][0]['attributes'])==93
    # EDGE values deliberately distinguish all4canonical endpoint pairs.
    s['meshData'][0]['attributes']=[{'name':'edgeZone','kind':'integer','domain':'EDGE','mode':'dense','values':[11,22,33,44]}]
    edge=execute('canonical-edges',types);assert edge['meshData'][0]['attributes'][0]['values']==[11,22,33,44]
    # Rectangular two-face strip: UV corner order and seam endpoints are explicit.
    uv=copy.deepcopy(types);s=uv['production'];s['meshData'][0]['attributes']=[]
    s['objects'][0]['vertices']=[[0,0,0],[2,0,0],[4,0,0],[0,3,0],[2,3,0],[4,3,0]];s['objects'][0]['faces']=[[0,1,4,3],[1,2,5,4]]
    s['meshData'][0]['uvMaps']=[{'name':'Label','method':'coordinates','coordinates':[[[0,0],[.5,0],[.5,1],[0,1]],[[.5,0],[1,0],[1,1],[.5,1]]]},{'name':'Box','method':'box','size':[4,3,1]}];s['meshData'][0]['renderUV']='Box'
    obs=execute('explicit-box-uv',uv);assert obs['meshData'][0]['uvMaps'][1]['coordinates']==[[[0,0],[.5,0],[.5,1],[0,1]],[[.5,0],[1,0],[1,1],[.5,1]]]
    for method in ('CONFORMAL','ANGLE_BASED','MINIMUM_STRETCH'):
        s['meshData'][0]['uvMaps']=[{'name':'Label','method':'unwrap','unwrapMethod':method,'seams':[[1,4]],'pack':True,'paddingPixels':8,'textureSize':[512,1024]}];s['meshData'][0]['renderUV']='Label'
        obs=execute('unwrap-'+method.lower(),uv);coords=obs['meshData'][0]['uvMaps'][0]['coordinates']
        # Independent polygon shoelace area; unwrap must produce two usable
        # islands, with a positive physical pixel gap along some separating axis.
        areas=[abs(sum(p[0]*q[1]-q[0]*p[1] for p,q in zip(f,f[1:]+f[:1])))/2 for f in coords];assert min(areas)>.01,areas
        boxes=[[min(p[i] for p in f) for i in (0,1)]+[max(p[i] for p in f) for i in (0,1)] for f in coords]
        gap_pixels=max(max(boxes[0][i]-boxes[1][i+2],boxes[1][i]-boxes[0][i+2])*[512,1024][i] for i in (0,1));assert gap_pixels>=8-.01,(coords,gap_pixels)
    # Packing an explicit tiled/negative projection still targets tile0–1.
    tiled=copy.deepcopy(uv);tiled['production']['meshData'][0]['uvMaps']=[{'name':'Label','method':'planar','origin':[10,10,0],'size':[.1,.1],'pack':True}];tiled['production']['meshData'][0]['renderUV']='Label'
    execute('packed-tiled-projection',tiled)
    # Linked Object prototypes have intentional shared/copy behaviour.
    shared=copy.deepcopy(d);s=shared['production'];s['exports']=[];s['geometryBindings']=[];s['geometryGraphs']=[]
    s['objects'].append({'id':'twin','kind':'instance','source':'panel','location':[50,0,0]})
    try:execute('refused-shared-default',shared)
    except SchemaxisError as error:assert error.fault.code=='SHARED_MESH_DATA',error
    else:raise AssertionError('implicit shared write accepted')
    for policy in ('copy','shared'):
        s['meshData'][0]['sharing']=policy;obs=execute('sharing-'+policy,shared)
        assert obs['meshData'][0]['owners']==(['panel'] if policy=='copy' else ['panel','twin'])
    # CAD/neutral asset composition: use the field GLB as a captured metre asset
    # placed in a millimetre production and author a second UV/channel layer.
    adopted={'version':'schemaxis.blender.production/1','id':'neutral-fields','prepareOnly':True,'production':{'units':'millimetres','assets':[{'id':'product','file':str(path),'format':'glb','sourceUnits':'metres'}],
        'meshData':[{'object':'product','attributes':[{'name':'batch','kind':'integer','domain':'FACE','mode':'constant','value':7}],'uvMaps':[{'name':'ServiceLabel','method':'smart','pack':True}]}]}}
    obs=execute('neutral-field-handoff',adopted);close(obs['samples'][0]['objects']['product']['bounds'],[0,40,0,30,0,4])
    # Native saved edit changes the field; adopt it as a new packed source and
    # apply a new channel to the exact semantic source part without flattening.
    edited=out/'edited.blend'
    if not (a.resume and edited.is_file()):native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"fields"/"0000.blend")!r},use_scripts=False)\n'+"a=bpy.data.objects['panel'].data.attributes['displacement']\nfor v in a.data:v.vector.z+=1\nbpy.context.view_layer.update()\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(edited)!r})\n')
    adopted['production']['assets'][0].update(file=str(edited),format='blend',sourceUnits='millimetres');adopted['production']['meshData'][0]['sourceObject']='panel'
    obs=execute('native-edit-adopt',adopted);close(obs['samples'][0]['objects']['product']['bounds'],[0,40,0,30,1,5])
    # Independently open result and assert native prototype data, typed shader,
    # shared owner relationships and actual source hierarchy survived save.
    native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"sharing-copy"/"0000.blend")!r},use_scripts=False)\n'+"assert bpy.data.objects['panel'].data!=bpy.data.objects['twin'].data\nassert 'temperature' not in bpy.data.objects['twin'].data.attributes\nassert bpy.data.materials['fieldColour'].node_tree.nodes['colour'].attribute_name=='fieldColour'\n")
    # Field deformation composes with morphs and a weighted armature, rather
    # than replacing the earlier editable deformation families.
    rigged=copy.deepcopy(d);rigged['production']['exports']=[];rigged['production']['meshData'][0]['uvMaps']=[];rigged['production']['meshData'][0].update(activeUV='',renderUV='')
    rigged['production'].update(shapeKeys=[{'object':'panel','keys':[{'id':'raised','offsets':[{'vertices':[0,1,2,3],'offset':[0,0,1]}],'value':1}]}],rigs=[{'id':'rig','bones':[{'id':'root','head':[0,0,0],'tail':[0,10,0]}]}],skin=[{'object':'panel','rig':'rig','weights':[{'bone':'root','vertices':[0,1,2,3],'weight':1}]}],tracks=[{'object':'rig','bone':'root','channel':'rotation','keys':[{'frame':1,'value':[0,0,math.pi/2]}]}])
    obs=execute('fields-morph-armature',rigged);close(obs['samples'][0]['objects']['panel']['bounds'],[-30,0,0,40,1,5])
    # Typed shader fields must change actual pixels, not merely node settings.
    from schemaxis.png import read
    means=[]
    for label,rgba in [('red',[1,0,0,1]),('blue',[0,0,1,1])]:
        rendered=copy.deepcopy(d);rendered['prepareOnly']=False;rendered['size']=[64,64];rendered['render']={'samples':2,'threads':1};rendered['cameras']=[{'direction':[0,0,1],'up':[0,1,0]}];rendered['production']['exports']=[]
        rendered['production']['meshData'][0]['attributes'][2]['values']=[rgba]*4
        execute('shader-'+label,rendered)
        receipt=json.loads((out/('shader-'+label)/'verification.json').read_text());image=next(x['file'] for x in receipt['artifacts'] if x['kind']=='image')
        w,h,pixels=read(image);channels=len(pixels)//(w*h);means.append([sum(pixels[i] for i in range(c,len(pixels),channels))/(w*h) for c in (0,1,2)])
    assert means[0][0]>means[0][2]+10 and means[1][2]>means[1][0]+10,means
    # Native selected-collection prototypes share a Mesh across two Objects.
    # Source identity selection and default refusal remain meaningful after append.
    source=out/'shared-source.blend'
    if not (a.resume and source.is_file()):native(a.blender,"import bpy\nbpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)\nm=bpy.data.meshes.new('shared');m.from_pydata([(0,0,0),(2,0,0),(0,3,0)],[],[(0,1,2)])\nfor name,x in [('partA',0),('partB',4)]:\n o=bpy.data.objects.new(name,m);bpy.context.scene.collection.objects.link(o);o.location.x=x\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n')
    selected={'version':'schemaxis.blender.production/1','id':'selected-fields','prepareOnly':True,'production':{'assets':[{'id':'assembly','file':str(source),'format':'blend'}],'meshData':[{'object':'assembly','sourceObject':'partA','sharing':'copy','attributes':[{'name':'region','kind':'integer','mode':'constant','value':19}]}]}}
    obs=execute('collection-source-copy',selected);assert obs['meshData'][0]['owners']==['assembly--partA'];close(obs['samples'][0]['objects']['assembly']['bounds'],[0,6,0,3,0,0])
    selected['production']['meshData'][0]['sharing']='shared';obs=execute('collection-source-shared',selected);assert obs['meshData'][0]['owners']==['assembly--partA','assembly--partB']
    for label,edit,code in [('ambiguous-source',lambda x:x['production']['meshData'][0].update(sourceObject=''),'AMBIGUOUS_MESH_TARGET'),('colliding-source',lambda x:x['production'].update(objects=[{'id':'partA','kind':'empty'}]),'AMBIGUOUS_MESH_TARGET'),('imported-shared-default',lambda x:x['production']['meshData'][0].update(sharing='refuse'),'SHARED_MESH_DATA')]:
        refused=copy.deepcopy(selected);edit(refused)
        # Existing public objects are constructed AFTER asset append. Use a DAG
        # Object collision below to exercise the true pre-append source case.
        if label=='colliding-source':
            refused={'version':'schemaxis.blender/1','nodes':[{'id':'paint','filter':'material'},{'id':'partA','filter':'cube','inputs':{'material':'paint'}}],'scenes':[{'id':'collision','visible':['assembly','partA'],'prepareOnly':True,'images':[{'id':'view','size':[32,32],'cameras':[{'direction':[1,-2,1]}]}],'production':copy.deepcopy(selected['production'])}]}
        try:execute(label,refused)
        except SchemaxisError as error:assert error.fault.code==code,(label,error.fault)
        else:raise AssertionError(label+' was accepted')
    # A mesh may mix polygon boundaries and loose wire edges. EDGE storage
    # counts all native edges, in canonical endpoint order, not only face edges.
    wire=out/'wire-source.blend'
    if not (a.resume and wire.is_file()):native(a.blender,"import bpy\nbpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)\nm=bpy.data.meshes.new('wire');m.from_pydata([(0,0,0),(2,0,0),(0,3,0),(2,3,0)],[(2,3)],[(0,1,2)]);o=bpy.data.objects.new('wirePart',m);bpy.context.scene.collection.objects.link(o)\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(wire)!r})\n')
    wire_doc={'version':'schemaxis.blender.production/1','id':'wire-fields','prepareOnly':True,'production':{'assets':[{'id':'wire','file':str(wire),'format':'blend'}],'meshData':[{'object':'wire','attributes':[{'name':'conductance','kind':'float','domain':'EDGE','mode':'dense','values':[11,22,33,44]}]}]}}
    obs=execute('loose-edge-fields',wire_doc);assert obs['meshData'][0]['edges']==[[0,1],[0,2],[1,2],[2,3]];assert obs['meshData'][0]['attributes'][0]['values']==[11,22,33,44]
    for flag,height in [('cad_baseline',30),('cad_variant',32.5)]:
        path_=getattr(a,flag)
        if not path_:continue
        cad={'version':'schemaxis.blender.production/1','id':flag,'prepareOnly':True,'production':{'units':'millimetres','assets':[{'id':'enclosure','file':str(Path(path_).absolute()),'format':'glb','sourceUnits':'metres'}],
            'meshData':[{'object':'enclosure','sourceObject':'housingView-exchange','attributes':[{'name':'temperature','kind':'float','domain':'POINT','mode':'constant','value':315}], 'uvMaps':[{'name':'Paint','method':'smart','pack':True,'textureSize':[1024,1024],'paddingPixels':4}]}, {'object':'enclosure','sourceObject':'lidView-exchange','attributes':[{'name':'region','kind':'integer','domain':'FACE','mode':'constant','value':2}],'uvMaps':[{'name':'Label','method':'planar','axis':'Z','size':[.03,.04]}]}],
            'exports':[{'id':'field-handoff','format':'glb','objects':['enclosure'],'frame':1}]}}
        obs=execute(flag,cad);close(obs['samples'][0]['objects']['enclosure']['bounds'],[-15,15,-20,20,0,height])
        assert [x['sourceObject'] for x in obs['meshData']]==['housingView-exchange','lidView-exchange']
    (out/'summary.json').write_text(json.dumps({'status':'passed','runtime':a.blender,'cases':results},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results),'channelVariants':93}))

if __name__=='__main__':main()
