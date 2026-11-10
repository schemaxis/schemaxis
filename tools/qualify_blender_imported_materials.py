"""Imported DAG material source authority, appearance and portable original inputs."""
import argparse,ast,base64,hashlib,json,struct,subprocess
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.captured_inputs import adopt
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from schemaxis.publication_metadata import finalise,MANIFEST
from schemaxis.workflow import execute as workflow_execute
from qualify_blender_image_preview import png,rgba
from qualify_blender_mesh_data import native as unchecked_native

def native(executable,source):
    ast.parse(source,filename="generated-native.py");compile(source,"generated-native.py","exec")
    return unchecked_native(executable,source)


COLOURS=[[64,128,192,255],[190,80,40,255],[40,180,100,255],[160,60,200,255]]


def gltf(directory,name,colours,mode='principled'):
    binary=bytearray();views=[];accessors=[]
    def accessor(fmt,values,kind,count,component,**bounds):
        offset=len(binary);raw=struct.pack('<'+fmt,*values);binary.extend(raw)
        views.append({'buffer':0,'byteOffset':offset,'byteLength':len(raw)})
        accessors.append({'bufferView':len(views)-1,'componentType':component,
                          'count':count,'type':kind,**bounds})
        return len(accessors)-1
    positions=accessor('18f',[-.8,0,.8,0,0,.8,0,0,-.8,-.8,0,-.8,.8,0,.8,.8,0,-.8],
                       'VEC3',6,5126,min=[-.8,0,-.8],max=[.8,0,.8])
    uv=accessor('12f',[0,0,.5,0,.5,1,0,1,1,0,1,1],'VEC2',6,5126)
    indices=[accessor('6H',v,'SCALAR',6,5123) for v in ([0,1,2,0,2,3],[1,4,5,1,5,2])]
    materials=[];images=[]
    for i,colour in enumerate(colours):
        image=directory/(name+'-'+str(i)+'.png');png(image,[colour]*4)
        images.append({'name':'paintImage','uri':'data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()})
        material={'name':'paint','doubleSided':True,
            'pbrMetallicRoughness':{'baseColorFactor':[0,0,0,1],'metallicFactor':0,'roughnessFactor':.5},
            'emissiveFactor':[1,1,1],'emissiveTexture':{'index':i}}
        if mode=='unlit':
            material.pop('emissiveFactor');material.pop('emissiveTexture')
            material['pbrMetallicRoughness'].update(baseColorFactor=[1,1,1,1],baseColorTexture={'index':i})
            material['extensions']={'KHR_materials_unlit':{}}
        elif mode=='anisotropy':
            material['extensions']={'KHR_materials_anisotropy':{'anisotropyStrength':.6,
                'anisotropyRotation':.3,'anisotropyTexture':{'index':i}}}
        elif mode=='volume':
            material['extensions']={'KHR_materials_transmission':{'transmissionFactor':.7},
                'KHR_materials_volume':{'thicknessFactor':.25,'attenuationColor':[.2,.5,.8],'attenuationDistance':2}}
        materials.append(material)
    d={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(binary),
        'uri':'data:application/octet-stream;base64,'+base64.b64encode(binary).decode()}],
        'bufferViews':views,'accessors':accessors,'images':images,
        'textures':[{'source':i} for i in range(2)],'materials':materials,
        'meshes':[{'primitives':[{'attributes':{'POSITION':positions,'TEXCOORD_0':uv},
            'indices':indices[i],'material':i} for i in range(2)]}],
        'nodes':[{'mesh':0}],'scenes':[{'nodes':[0]}],'scene':0}
    extensions={e for m in materials for e in m.get('extensions',{})}
    if extensions:d['extensionsUsed']=sorted(extensions)
    path=directory/(name+'.gltf');path.write_text(json.dumps(d));return path


def document(sources,prepare=False):
    nodes=[];visible=[]
    for i,source in enumerate(sources):
        identity='source'+str(i);nodes.append({'id':identity,'filter':'readGltf','options':{'file':str(source)}})
        if len(sources)>1:
            moved='moved'+str(i);nodes.append({'id':moved,'filter':'transform',
                'inputs':{'input':identity},'options':{'translation':[-1 if i==0 else 1,0,0]}});visible.append(moved)
        else:visible.append(identity)
    return {'version':'schemaxis.blender/1','nodes':nodes,'scenes':[{'id':'source-materials',
        'visible':visible,'prepareOnly':prepare,'render':{'samples':1,'threads':2,'worldStrength':0,'lightEnergy':0,
            'renderer':{'kind':'cycles'},'colourManagement':{'view':{'kind':'standard'}}},
        'images':[{'id':'view','size':[64,32],'cameras':[{'direction':[0,0,1],
            'up':[0,1,0],'scale':4 if len(sources)>1 else 2}]}]}]}


def morph_source(source):
    """One relative shape, linearly animated at glTF seconds 0 and 1 (24fps)."""
    d=json.loads(source.read_text());raw=bytearray(base64.b64decode(d['buffers'][0]['uri'].split(',')[1]))
    def append(values,kind,count,**bounds):
        offset=len(raw);payload=struct.pack('<'+'f'*len(values),*values);raw.extend(payload)
        d['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(payload)})
        d['accessors'].append({'bufferView':len(d['bufferViews'])-1,'componentType':5126,
                              'count':count,'type':kind,**bounds})
        return len(d['accessors'])-1
    delta=append([0,0,-.4]*6,'VEC3',6,min=[0,0,-.4],max=[0,0,-.4])
    times=append([0,1],'SCALAR',2,min=[0],max=[1]);weights=append([.25,.75],'SCALAR',2)
    for primitive in d['meshes'][0]['primitives']:primitive['targets']=[{'POSITION':delta}]
    d['meshes'][0].update(weights=[.25],extras={'targetNames':['Lift']})
    d['animations']=[{'name':'LiftAction','samplers':[{'input':times,'output':weights,'interpolation':'LINEAR'}],
        'channels':[{'sampler':0,'target':{'node':0,'path':'weights'}}]}]
    d['buffers'][0]={'byteLength':len(raw),'uri':'data:application/octet-stream;base64,'+base64.b64encode(raw).decode()}
    path=source.with_name('morph.gltf');path.write_text(json.dumps(d));return path


def mesh_channels(source):
    """Retained alternate UV, two colour attributes and explicit source normals."""
    d=json.loads(source.read_text());raw=bytearray(base64.b64decode(d['buffers'][0]['uri'].split(',')[1]))
    def append(values,kind,count):
        offset=len(raw);payload=struct.pack('<'+'f'*len(values),*values);raw.extend(payload)
        d['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(payload)})
        d['accessors'].append({'bufferView':len(d['bufferViews'])-1,'componentType':5126,'count':count,'type':kind})
        return len(d['accessors'])-1
    attributes={'TEXCOORD_1':append([.25,.75]*6,'VEC2',6),
                'COLOR_0':append([1,0,0,1]*6,'VEC4',6),
                'COLOR_1':append([0,1,0,1]*6,'VEC4',6),
                'NORMAL':append([0,1,0]*6,'VEC3',6)}
    for p in d['meshes'][0]['primitives']:p['attributes'].update(attributes)
    d['buffers'][0]={'byteLength':len(raw),'uri':'data:application/octet-stream;base64,'+base64.b64encode(raw).decode()}
    path=source.with_name('mesh-channels.gltf');path.write_text(json.dumps(d));return path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False);inputs=out/'inputs';inputs.mkdir()
    fp=source_fingerprint('blender');archive=hashlib.sha256(runtime_archive()).hexdigest()
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'sourceFingerprint':fp,'runtimeArchiveSha256':archive,
        'qualifierSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[]}
    def write():(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    def record(value):report['checks'].append(value);write();print(value['case']+' PASS',flush=True)
    def build(label,d,points=None,wanted=None):
        packet=out/label;run(d,packet,executable=args.blender,timeout=300)
        with location_context({'blender':args.blender}):assert verify(packet)['verified']
        value={'case':label,'accepted':True}
        if points:
            found=rgba(packet,points)
            assert all(abs(a-b)<=1 for row,ref in zip(found,wanted) for a,b in zip(row,ref)),(label,found,wanted)
            value.update(encodedRGBA=found,independentExpectedRGBA=wanted,maximumByteError=1)
        record(value);return packet
    def attacks(packet,object_name='moved0',extra_cases=None):
        blend=packet/'0000.blend';receipt=packet/'verification.json';reopened=packet/'reopened.json'
        saved={p:p.read_bytes() for p in [blend,receipt,reopened,packet/MANIFEST,*packet.glob('*.metadata.json')]}
        cases=extra_cases if extra_cases is not None else [('unchanged-save','',True),
            ('hidden-subsurface',"shader.inputs['Subsurface Weight'].default_value=.63",False),
            ('source-emission',"shader.inputs['Emission Strength'].default_value=2",False),
            ('slot-order',"obj.data.materials[0],obj.data.materials[1]=obj.data.materials[1],obj.data.materials[0]",False),
            ('face-slot',"obj.data.polygons[0].material_index=1-obj.data.polygons[0].material_index",False),
            ('object-override',"obj.material_slots[0].link='OBJECT';obj.material_slots[0].material=mat.copy()",False),
            ('data-sharing',"obj.data=bpy.data.objects['moved1'].data",False),
            ('image-pointer',"tex.image=next(n.image for n in obj.data.materials[1].node_tree.nodes if n.bl_idname=='ShaderNodeTexImage')",False),
            ('image-colour-space',"tex.image.colorspace_settings.name='Non-Color'",False),
            ('unreviewed-source-class',"mat.node_tree.nodes.new('ShaderNodeHueSaturation')",False),
            ('uv-input-payload',"obj.data.uv_layers.active.data[0].uv=(.77,.33)",False),
            ('uv-render-selection',"obj.data.uv_layers.new(name='otherUV').active_render=True",False),
            ('colour-attribute-input',"a=obj.data.color_attributes.new(name='sourceColour',type='FLOAT_COLOR',domain='CORNER');a.data[0].color=(.1,.3,.6,1)",False),
            ('split-normal-input',"obj.data.normals_split_custom_set([(.2,.3,.9)]*len(obj.data.loops))",False),
            ('texture-space-input',"obj.data.use_auto_texspace=False;obj.data.texspace_location=(.3,.2,.1)",False),
            ('object-shader-colour',"obj.color=(.2,.4,.6,1)",False),
            ('source-vertex-input',"obj.data.vertices[0].co.x+=.1",False),
            ('source-transform-input',"obj.location.x+=.2",False)]
        if extra_cases is None:
            cases += [('render-only-modifier',"m=obj.modifiers.new('render-only','SOLIDIFY');m.show_viewport=False;m.show_render=True;m.thickness=.3",False)]
        try:
            for label,mutation,positive in cases:
                for path,value in saved.items():path.write_bytes(value)
                witness=out/(label+'-snapshot.json')
                code='import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+\
                    "from schemaxis.errors import SchemaxisError\nfrom schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.adaptor import plan\n"+\
                    f"master,selection,_=plan(json.loads(open({str(packet/'input.json')!r}).read()))\n"+\
                    f"obj=bpy.data.objects[{object_name!r}];mat=obj.data.materials[0];shader=next(n for n in mat.node_tree.nodes if n.bl_idname=='ShaderNodeBsdfPrincipled');tex=next(n for n in mat.node_tree.nodes if n.bl_idname=='ShaderNodeTexImage')\n"+mutation+'\n'+\
                    f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+\
                    f'readback_fault=None\ntry:state=snapshot(selection.order)\nexcept SchemaxisError as exc:state=json.loads(open({str(receipt)!r}).read())["states"][0]["snapshot"];readback_fault=exc.fault.to_dict()\n'+\
                    f'open({str(witness)!r},"w").write(json.dumps({{"state":state,"readbackFault":readback_fault}}))\n'
                native(args.blender,code);readback=json.loads(witness.read_text());state=readback['state']
                value=json.loads(saved[receipt]);value['states'][0]['snapshot']=state
                next(a for a in value['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest()
                receipt.write_text(json.dumps(value));value=json.loads(saved[reopened]);value['states'][0]=state
                reopened.write_text(json.dumps(value));finalise(packet);fault=None
                with location_context({'blender':args.blender}):
                    try:verify(packet)
                    except SchemaxisError as exc:fault=exc.fault.to_dict()
                direct=out/(label+'-direct-fault.json')
                native(args.blender,'import sys,json\n'+f'sys.path.insert(0,{str(Path.cwd()/"src")!r})\n'+
                    'from schemaxis.errors import SchemaxisError\nfrom schemaxis.adaptors.blender.native import reopen\n'+
                    f'fault=None\ntry:reopen({str(packet)!r},{str(out/(label+"-direct-readback.json"))!r})\nexcept SchemaxisError as exc:fault=exc.fault.to_dict()\n'+
                    f'open({str(direct)!r},"w").write(json.dumps(fault))\n')
                direct_fault=json.loads(direct.read_text())
                record({'case':label,'positive':positive,'fault':fault,'directFault':direct_fault,
                    'initialReadbackFault':readback['readbackFault'],'nativeHashRefreshed':True,
                    'bothSnapshotsReplaced':readback['readbackFault'] is None,'publicationMetadataRefreshed':True})
                if not positive:
                    mutant=out/'mutants'/label;mutant.mkdir(parents=True)
                    for path in saved:(mutant/path.name).write_bytes(path.read_bytes())
                assert (fault is None)==positive,(label,fault)
                assert (direct_fault is None)==positive,(label,direct_fault)
                if direct_fault:
                    unsupported={'unreviewed-source-class':'node type needs reviewed asset fidelity/dependency support',
                                 'morph-driver-refusal':'material geometry input drivers require a typed channel contract'}
                    context_inputs={'data-sharing','object-shader-colour','source-transform-input'}
                    expected_code='UNSUPPORTED_ASSET_DEPENDENCY' if label in unsupported else 'VERIFICATION_FAILED'
                    expected_guard=unsupported.get(label,
                        'render context differs' if label in context_inputs else 'shader state differs')
                    assert direct_fault['code']==expected_code and expected_guard in direct_fault['message'],direct_fault
                    assert fault['code']==expected_code and expected_guard in fault['message'],fault
        finally:
            for path,value in saved.items():path.write_bytes(value)
        with location_context({'blender':args.blender}):assert verify(packet)['verified']
        record({'case':'restored-public-positive','accepted':True})
    try:
        first=gltf(inputs,'first',COLOURS[:2]);second=gltf(inputs,'second',COLOURS[2:])
        build('two-regions',document([first]),[(27,16),(37,16)],COLOURS[:2])
        combined=build('colliding-multi-import-derived',document([first,second]),[(11,16),(21,16),(43,16),(53,16)],COLOURS)
        attacks(combined)
        channels=build('source-mesh-channels',document([mesh_channels(first)]),[(27,16),(37,16)],COLOURS[:2])
        attacks(channels,'source0',[
            ('channels-unchanged-save','',True),
            ('channels-uv-selection',"obj.data.uv_layers.active_index=1",False),
            ('channels-render-uv-selection',"obj.data.uv_layers[1].active_render=True",False),
            ('channels-active-colour-selection',"obj.data.color_attributes.active_color_index=1",False),
            ('channels-render-colour-selection',"obj.data.color_attributes.render_color_index=1",False)])
        for mode,node in [('unlit','ShaderNodeLightPath'),('anisotropy','ShaderNodeTangent'),('volume','ShaderNodeVolumeAbsorption')]:
            source=gltf(inputs,mode,COLOURS[2:],mode);packet=build('source-'+mode,document([source],mode!='unlit'),
                [(27,16),(37,16)] if mode=='unlit' else None,COLOURS[2:] if mode=='unlit' else None)
            witness=out/(mode+'-classes.json')
            native(args.blender,'import bpy,json\n'+f'bpy.ops.wm.open_mainfile(filepath={str(packet/"0000.blend")!r},use_scripts=False)\n'+
                f'open({str(witness)!r},"w").write(json.dumps(sorted({{n.bl_idname for m in bpy.data.materials if m.node_tree for n in m.node_tree.nodes}})))\n')
            assert node in json.loads(witness.read_text()),(mode,witness.read_text())
            record({'case':mode+'-source-class','requiredClass':node,
                'scope':'Native source fidelity; no claim of a physical anisotropy/volume rendering oracle.'})
        morph=build('relative-morph-source',document([morph_source(first)],True))
        witness=out/'morph-literal-readback.json'
        native(args.blender,'import bpy,json\n'+f'bpy.ops.wm.open_mainfile(filepath={str(morph/"0000.blend")!r},use_scripts=False)\n'+
            "obj=bpy.data.objects['source0'];key=obj.data.shape_keys;rows=[]\n"+
            "for frame in (0,12,24):\n bpy.context.scene.frame_set(frame);bpy.context.view_layer.update();o=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());m=o.to_mesh();rows.append({'frame':frame,'weight':key.key_blocks['Lift'].value,'firstVertex':list(m.vertices[0].co)});o.to_mesh_clear()\n"+
            f'open({str(witness)!r},"w").write(json.dumps(rows))\n')
        rows=json.loads(witness.read_text())
        for row,weight in zip(rows,(.25,.5,.75)):
            assert abs(row['weight']-weight)<1e-6,row
            assert all(abs(a-b)<1e-6 for a,b in zip(row['firstVertex'],(-.8,-.8+.4*weight,0))),row
        record({'case':'literal-morph-interpolation','native':rows,
                'independentWeights':[.25,.5,.75],'independentBase':[-.8,-.8,0],'independentDelta':[0,.4,0]})
        attacks(morph,'source0',[
            ('morph-unchanged-save','',True),
            ('morph-delta-source',"obj.data.shape_keys.key_blocks['Lift'].data[0].co.y+=.2",False),
            ('morph-action-source',"a=obj.data.shape_keys.animation_data.action;a.layers[0].strips[0].channelbags[0].fcurves[0].keyframe_points[0].co.y=.7",False),
            ('morph-driver-refusal',"obj.data.shape_keys.key_blocks['Lift'].driver_add('value').driver.expression='0.25'",False)])
        # Audit every other DAG file constructor. STL/PLY retain no implicit
        # shader; PLY colours remain editable source attributes. CSV geometry
        # receives its declared material through the ordinary DAG port.
        stl=inputs/'triangle.stl';stl.write_text('solid triangle\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid triangle\n')
        ply=inputs/'coloured.ply';ply.write_text('ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nelement face 1\nproperty list uchar uint vertex_indices\nend_header\n0 0 0 255 0 0\n1 0 0 0 255 0\n0 1 0 0 0 255\n3 0 1 2\n')
        csv=inputs/'line.csv';csv.write_text('x,y,z\n0,0,0\n1,0,0\n1,1,0\n')
        for kind,path in [('readSTL',stl),('readPLY',ply),('curveFromCSV',csv)]:
            d=document([path],True);d['nodes'][0]['filter']=kind
            if kind=='curveFromCSV':
                d['nodes'].insert(0,{'id':'material','filter':'material','options':{'colour':[.2,.4,.6,1]}})
                d['nodes'][1]['inputs']={'material':'material'}
            packet=build('source-'+kind,d);witness=out/(kind+'-native.json')
            native(args.blender,'import bpy,json\n'+f'bpy.ops.wm.open_mainfile(filepath={str(packet/"0000.blend")!r},use_scripts=False)\n'+
                "m=bpy.data.objects['source0'].data;rows={'vertices':len(m.vertices),'faces':len(m.polygons),'materials':[x.name for x in m.materials],'colours':{a.name:[list(c.color) for c in a.data] for a in m.color_attributes}}\n"+
                f'open({str(witness)!r},"w").write(json.dumps(rows))\n')
            row=json.loads(witness.read_text())
            if kind in ('readSTL','readPLY'):assert row['vertices']==3 and row['faces']==1 and not row['materials'],row
            if kind=='readPLY':assert list(row['colours'].values())[0]==[[1,0,0,1],[0,1,0,1],[0,0,1,1]],row
            if kind=='curveFromCSV':assert row['materials']==['material'],row
            record({'case':kind+'-literal-source-audit','native':row})
        # Explicit portable capture preserves the original glTF bytes including
        # both embedded textures; removing its workstation precursor is allowed.
        pin=adopt(first,out/'adopted-original');d=document([first]);d['nodes'][0]['options']['file']=pin['reference']
        workflow={'version':'schemaxis.workflow/1','operations':[{'id':'imported','document':d}]}
        result=workflow_execute(workflow,out/'portable',blender=args.blender,timeout=360);assert result['verified']
        removed=first.with_suffix('.removed');first.rename(removed)
        try:
            reused=workflow_execute(workflow,out/'portable',blender=args.blender,timeout=360,resume=True)
            assert reused['verified'] and any(j.get('reused') for j in reused['jobs'])
            packet=Path(reused['jobs'][0]['directory'])
            with location_context({'blender':args.blender}):assert verify(packet)['verified']
            found=rgba(packet,[(27,16),(37,16)]);assert all(abs(a-b)<=1 for row,ref in zip(found,COLOURS[:2]) for a,b in zip(row,ref))
            record({'case':'adopted-original-precursor-removal-reuse','pin':pin,'encodedRGBA':found,
                'independentExpectedRGBA':COLOURS[:2],'sourcePrecursorAbsent':not first.exists()})
        finally:removed.rename(first)
        assert source_fingerprint('blender')==fp and hashlib.sha256(runtime_archive()).hexdigest()==archive
        report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        write()


if __name__=='__main__':main()
