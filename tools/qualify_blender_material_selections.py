"""Shader-requested selection masks, captured originals and presentation controls."""
import argparse,ast,copy,hashlib,json,subprocess
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.captured_inputs import adopt
from schemaxis.errors import SchemaxisError
from schemaxis.png import read
from schemaxis.publication_metadata import finalise,MANIFEST
from schemaxis.workflow import execute as workflow_execute
from qualify_blender_mesh_data import native as unchecked_native
from qualify_blender_image_preview import rgba

def native(executable,source):
    ast.parse(source,filename="generated-native.py");compile(source,"generated-native.py","exec")
    return unchecked_native(executable,source)


def fixture(query=True):
    nodes=[{'id':'emit','kind':'emission','values':{'colour':[1,1,1,1]}},{'id':'finish','kind':'output'}]
    links=[{'from':{'node':'emit','socket':'shader'},'to':{'node':'finish','socket':'surface'}}]
    if query:
        nodes.append({'id':'select','kind':'attribute','properties':{'name':'.select_vert'}})
        links.append({'from':{'node':'select','socket':'factor'},'to':{'node':'emit','socket':'colour'}})
    return {'version':'schemaxis.blender.production/1','size':[32,32],
        'cameras':[{'direction':[0,0,1],'up':[0,1,0]}],
        'render':{'samples':1,'threads':2,'renderer':{'kind':'cycles'},'colourManagement':{'view':{'kind':'standard'}},'worldStrength':0,'lightEnergy':0},
        'production':{'objects':[{'id':'patch','kind':'mesh','vertices':[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],'faces':[[0,1,2,3]],'material':'surface'}],
            'materialGraphs':[{'id':'surface','nodes':nodes,'links':links}]}}


def resource_fixture():
    d=fixture();p=d['production'];source=copy.deepcopy(p['objects'][0]);source['id']='resource';source['material']='';source['hidden']=True
    p['objects'].append(source);d['visible']=['patch']
    p['geometryResources']=[{'id':'sourceMesh','kind':'object','object':'resource'}]
    p['geometryGraphs']=[{'id':'copy','nodes':[
        {'id':'source','kind':'objectInfo','values':{'object':'sourceMesh','asInstance':False}},
        {'id':'finish','kind':'setMaterial','values':{'material':'surface'}},{'id':'out','kind':'output'}],
        'links':[{'from':{'node':'source','socket':'geometry'},'to':{'node':'finish','socket':'geometry'}},
                 {'from':{'node':'finish','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]}]
    p['geometryBindings']=[{'object':'patch','graph':'copy'}];return d


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    fp=source_fingerprint('blender');archive=hashlib.sha256(runtime_archive()).hexdigest()
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'sourceFingerprint':fp,'runtimeArchiveSha256':archive,'qualifierSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[]}
    def record(row):
        report['checks'].append(row);(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(row['case']+' PASS',flush=True)
    def build(label,d,baseline=255):
        packet=out/label;run(d,packet,executable=args.blender,timeout=240)
        with location_context({'blender':args.blender}):assert verify(packet)['verified']
        assert rgba(packet,[(16,16)])==[[baseline,baseline,baseline,255]],label
        record({'case':label,'literalBaselineRGBA':[baseline,baseline,baseline,255]});return packet
    def exercise(label,packet,target,consumed,baseline=255,source_selected=True,render_frame=None):
        blend=packet/'0000.blend';receipt=packet/'verification.json';reopened=packet/'reopened.json'
        saved={p:p.read_bytes() for p in (blend,receipt,reopened,packet/MANIFEST,*packet.glob('*.metadata.json'))}
        try:
            for case,selected in [('unchanged-save',None),('deselected',False),('selected',True)]:
                for p,b in saved.items():p.write_bytes(b)
                name=label+'-'+case;witness=out/(name+'.json');image=out/(name+'.png')
                code=('import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+
                    'from schemaxis.adaptors.blender.adaptor import plan\nfrom schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+
                    f'master,selection,_=plan(json.loads(open({str(packet/"input.json")!r}).read()));spec=master.document["scenes"][0]["production"]\n'+
                    f'obj={target}\n')
                if selected is not None:code+=f'for v in obj.data.vertices:v.select={selected!r}\n'
                code+=('obj.data.update();bpy.context.view_layer.update()\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+
                    'production=observe(spec);production["meshEditBaselines"]=[]\n'+
                    f'open({str(witness)!r},"w").write(json.dumps({{"state":snapshot(selection.order),"production":production,"flags":[v.select for v in obj.data.vertices]}}))\n')
                if render_frame is not None:code+=f'bpy.context.scene.frame_set({render_frame})\n'
                code+=f'bpy.context.scene.render.filepath={str(image)!r}\nbpy.ops.render.render(write_still=True)\n'
                native(args.blender,code);value=json.loads(witness.read_text())
                r=json.loads(saved[receipt]);r['states'][0]['snapshot']=value['state'];r['states'][0]['production']=value['production']
                next(a for a in r['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();receipt.write_text(json.dumps(r))
                r=json.loads(saved[reopened]);r['states'][0]=value['state'];r['production'][0]=value['production'];reopened.write_text(json.dumps(r));finalise(packet)
                fault=None
                with location_context({'blender':args.blender}):
                    try:verify(packet)
                    except SchemaxisError as exc:fault=exc.fault.to_dict()
                direct=out/(name+'-direct.json')
                native(args.blender,'import sys,json\n'+f'sys.path.insert(0,{str(Path.cwd()/"src")!r})\n'+
                    'from schemaxis.errors import SchemaxisError\nfrom schemaxis.adaptors.blender.native import reopen\n'+
                    f'fault=None\ntry:reopen({str(packet)!r},{str(out/(name+"-readback.json"))!r})\nexcept SchemaxisError as exc:fault=exc.fault.to_dict()\n'+
                    f'open({str(direct)!r},"w").write(json.dumps(fault))\n')
                direct_fault=json.loads(direct.read_text());w,h,pixels=read(image);pixel=list(pixels[4*(16*w+16):4*(16*w+16)+4])
                rejected=consumed and selected is not None and selected!=source_selected
                row={'case':name,'consumed':consumed,'nativeFlags':value['flags'],'pixel':pixel,'fault':fault,'directFault':direct_fault,
                    'nativeHashBothSnapshotsAndProductionReadbacksReplaced':True,'publicationMetadataRefreshed':True,
                    'renderFrame':render_frame,'savedFrame':1 if render_frame is not None else None}
                record(row)
                if rejected:
                    mutant=out/'mutants'/name;mutant.mkdir(parents=True)
                    for p in saved:(mutant/p.name).write_bytes(p.read_bytes())
                    assert fault and fault['code']=='VERIFICATION_FAILED',row
                    assert direct_fault and 'shader state differs' in direct_fault['message'],row
                    value=255 if selected else 0
                    assert pixel==[value,value,value,255],row
                else:
                    assert fault is None and direct_fault is None,row
                    assert pixel==[baseline,baseline,baseline,255],row
        finally:
            for p,b in saved.items():p.write_bytes(b)
        with location_context({'blender':args.blender}):assert verify(packet)['verified']
        record({'case':label+'-restored-public-positive'})
    try:
        authored=build('authored',fixture());exercise('authored',authored,"bpy.data.objects['patch']",True)
        source=out/'original.blend';source.write_bytes((authored/'0000.blend').read_bytes())
        d=fixture();d['production']={'assets':[{'id':'source','format':'blend','file':str(source)}]}
        captured=build('captured',d);exercise('captured',captured,"next(o for o in bpy.data.objects if o.type=='MESH')",True)
        # Captured layered Actions can change the query mode while its literal
        # reserved name remains static. Save/forge at frame1 (OBJECT), but test
        # the source's future GEOMETRY-mode image independently at frame12.
        animated_source=out/'animated-original.blend';animation=out/'animated-source.json'
        native(args.blender,'import bpy,json\n'+f'bpy.ops.wm.open_mainfile(filepath={str(authored/"0000.blend")!r},use_scripts=False)\n'+
            'obj=bpy.data.objects["patch"];node=next(n for n in obj.data.materials[0].node_tree.nodes if n.bl_idname=="ShaderNodeAttribute")\n'+
            'node.attribute_type="OBJECT";node.keyframe_insert(data_path="attribute_type",frame=1)\n'+
            'node.attribute_type="GEOMETRY";node.keyframe_insert(data_path="attribute_type",frame=12)\n'+
            'modes={}\nfor frame in (1,12):\n bpy.context.scene.frame_set(frame);modes[str(frame)]=node.attribute_type\n'+
            'bpy.context.scene.frame_set(1)\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(animated_source)!r})\n'+
            f'open({str(animation)!r},"w").write(json.dumps({{"modes":modes,"action":node.id_data.animation_data.action.name}}))\n')
        modes=json.loads(animation.read_text());assert modes['modes']=={'1':'OBJECT','12':'GEOMETRY'},modes
        record({'case':'captured-animated-source-modes','native':modes})
        d['production']['assets'][0]['file']=str(animated_source)
        animated=build('captured-animated',d,0)
        exercise('captured-animated',animated,"next(o for o in bpy.data.objects if o.type=='MESH')",True,render_frame=12)
        unqueried=build('unqueried',fixture(False));exercise('unqueried',unqueried,"bpy.data.objects['patch']",False)
        unqueried_source=out/'unqueried-original.blend';unqueried_source.write_bytes((unqueried/'0000.blend').read_bytes())
        d['production']['assets'][0]['file']=str(unqueried_source)
        unqueried_captured=build('unqueried-captured',d)
        exercise('unqueried-captured',unqueried_captured,"next(o for o in bpy.data.objects if o.type=='MESH')",False)
        # The hidden source contributes geometry and flags through Object Info;
        # only the consumer is visible, avoiding two coplanar rendered meshes.
        resource=build('resource',resource_fixture());witness=out/'resource-inputs.json'
        native(args.blender,'import bpy,json,sys\n'+f'sys.path.insert(0,{str(Path.cwd()/"src")!r})\n'+
            'from schemaxis.adaptors.blender.native import reopen\n'+
            f'reopen({str(resource)!r},{str(out/"resource-current.json")!r})\n'+
            'from schemaxis.adaptors.blender.selection_inputs_native import objects,observe\nfrom schemaxis.adaptors.blender.object_materials_native import ImportedShaders\nfrom schemaxis.adaptors.blender.shader_budget_native import ShaderBudget\n'+
            's=ImportedShaders([],shader_budget=ShaderBudget());values,attributes=observe(objects(),s,bpy.context.evaluated_depsgraph_get());o=bpy.data.objects["patch"].evaluated_get(bpy.context.evaluated_depsgraph_get());m=o.to_mesh(preserve_all_data_layers=True,depsgraph=bpy.context.evaluated_depsgraph_get());row={"inputs":values,"attributeInputs":attributes,"vertices":[list(v.co) for v in m.vertices],"faces":[list(p.vertices) for p in m.polygons],"materials":[v.name for v in m.materials],"evaluatedSelectionAttributePresent":m.attributes.get(".select_vert") is not None};o.to_mesh_clear()\n'+
            f'open({str(witness)!r},"w").write(json.dumps(row))\n')
        row=json.loads(witness.read_text());assert row['inputs']['resource']['requested']==['.select_vert'],row
        assert row['evaluatedSelectionAttributePresent'] and 'surface' in row['materials'],row
        assert sorted(row['vertices'])==[[-1,-1,0],[-1,1,0],[1,-1,0],[1,1,0]] and len(row['faces'])==1,row
        record({'case':'propagated-resource-inputs','native':row,'scope':'Literal source quad, actual selected attribute and material; hidden source contributes through Object Info.'})
        exercise('resource',resource,"bpy.data.objects['resource']",True)
        # This is an explicit new original input, not a resnapshot or migration
        # of a submitted output's obsolete witness. The old authored packet
        # remains restored and independently verifiable.
        edited=out/'edited-original.blend';edited.write_bytes((out/'mutants/authored-deselected/0000.blend').read_bytes())
        pin=adopt(edited,out/'adopted-edited-original');d=fixture();d['production']={'assets':[{'id':'source','format':'blend','file':pin['reference']}]}
        workflow={'version':'schemaxis.workflow/1','operations':[{'id':'selectionEdition','document':d}]}
        result=workflow_execute(workflow,out/'edited-workflow',blender=args.blender,timeout=300);assert result['verified']
        packet=Path(result['jobs'][0]['directory']);assert rgba(packet,[(16,16)])==[[0,0,0,255]]
        removed=edited.with_suffix('.removed');edited.rename(removed)
        try:
            reused=workflow_execute(workflow,out/'edited-workflow',blender=args.blender,timeout=300,resume=True)
            assert reused['verified'] and any(j.get('reused') for j in reused['jobs'])
            with location_context({'blender':args.blender}):assert verify(packet)['verified']
            record({'case':'explicit-edited-original-adoption','pin':pin,'literalRGBA':[0,0,0,255],
                'workstationPrecursorAbsent':not edited.exists(),'verifiedReuse':True})
        finally:removed.rename(edited)
        exercise('edited-original',packet,"next(o for o in bpy.data.objects if o.type=='MESH')",True,0,False)
        assert source_fingerprint('blender')==fp and hashlib.sha256(runtime_archive()).hexdigest()==archive
        report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
