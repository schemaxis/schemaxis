"""Artist shader edit, pinned-original adoption, pixel response and lifecycle."""
import argparse,copy,hashlib,json,threading
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.captured_inputs import adopt
from schemaxis.configuration import location_context
from schemaxis.dispatch import allocation
from schemaxis.errors import SchemaxisError
from schemaxis.workflow import execute
from schemaxis.publication_metadata import finalise,MANIFEST
from qualify_blender_material_assignments import fixture,COLOURS
from qualify_blender_render_policy import expected
from qualify_blender_image_preview import png,rgba
from qualify_blender_imported_materials import native
from blender_surface_evidence import identity,verify_identity


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False);exe=args.blender
    report={'status':'running',**identity(out,exe),'checks':[]};target=out/'summary.json'
    def record(case,**values):
        report['checks'].append({'case':case,**values});target.write_text(json.dumps(report,indent=2)+'\n');print(case+' PASS',flush=True)
    def refused(call,codes):
        try:call()
        except SchemaxisError as error:
            assert error.fault.code in codes,error.fault.to_dict();return error.fault.to_dict()
        raise AssertionError('expected structured refusal')
    def pixels(directory,colours):
        actual=rgba(directory,[(11,16),(21,16),(43,16),(53,16)]);wanted=[expected(c,0) for c in colours]
        assert all(abs(a-b)<=1 for row,ref in zip(actual,wanted) for a,b in zip(row,ref)),(actual,wanted)
        return {'actualRGBA':actual,'independentExpectedRGBA':wanted,'maximumByteError':1}
    def coforge(packet,mutation,label):
        blend=packet/'0000.blend';receipt=packet/'verification.json';reopened=packet/'reopened.json'
        saved={p:p.read_bytes() for p in [blend,receipt,reopened,packet/MANIFEST,*packet.glob('*.metadata.json')]}
        witness=out/(label+'-observed.json')
        try:
            native(exe,'import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'+
                f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+
                'bpy.context.preferences.filepaths.save_version=0\n'+mutation+'\n'+
                f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+
                'from schemaxis.adaptors.blender.adaptor import plan\nfrom schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+
                f'master,selection,_=plan(json.loads(open({str(packet/"input.json")!r}).read()))\n'+
                f'open({str(witness)!r},"w").write(json.dumps({{"state":snapshot(selection.order),"production":observe(master.document["scenes"][0]["production"])}}))\n')
            observed=json.loads(witness.read_text());observed['production']['meshEditBaselines']=json.loads(saved[receipt])['states'][0]['production']['meshEditBaselines']
            value=json.loads(saved[receipt]);value['states'][0].update(snapshot=observed['state'],production=observed['production'])
            next(a for a in value['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();receipt.write_text(json.dumps(value))
            value=json.loads(saved[reopened]);value['states'][0]=observed['state'];value['production'][0]=observed['production'];reopened.write_text(json.dumps(value));finalise(packet)
            with location_context({'blender':exe}):fault=refused(lambda:verify(packet),{'VERIFICATION_FAILED'})
            mutant=out/'mutants'/label;mutant.mkdir(parents=True)
            for path in saved:(mutant/path.name).write_bytes(path.read_bytes())
            record(label,publicFault=fault,bothSnapshotsNativeHashPublicationRefreshed=True)
        finally:
            for path,data in saved.items():path.write_bytes(data)
        with location_context({'blender':exe}):assert verify(packet)['verified']
        assert all(path.read_bytes()==data for path,data in saved.items());record(label+'-restored-positive')
    try:
        image=out/'red.png';png(image,[[255,0,0,255]]*4)
        d=fixture('cycles',True);d['render'].update(worldStrength=0,lightEnergy=0);p=d['production'];p['materialGraphs']=[]
        p['images']=[{'id':'redImage','file':str(image),'colourSpace':'Non-Color','alphaMode':'channelPacked'}]
        p['surfaceMaterials']=[]
        for name,colour in COLOURS.items():
            material={'id':name,'baseColour':{'kind':'constant','value':[0,0,0]},'ior':{'kind':'constant','value':1},
                'emission':{'colour':{'kind':'constant','value':colour},'strength':{'kind':'constant','value':1}}}
            if name=='red':
                material['samplers']=[{'id':'ink','image':'redImage','filter':'nearest'}];material['emission']['colour']={'kind':'sample','sampler':'ink'}
            p['surfaceMaterials'].append(material)
        p['meshData']=[{'object':'patch','sharing':'shared','uvMaps':[{'name':'UV','method':'planar','origin':[-.8,-.8,0],'size':[1.6,1.6]}]}]
        producer=out/'producer';run(d,producer,executable=exe,timeout=180)
        with location_context({'blender':exe}):assert verify(producer)['verified']
        colours=[COLOURS[n] for n in ('red','blue','green','yellow')];record('artist-linked-palette-pixels',**pixels(producer,colours))
        coforge(producer,'bpy.context.scene.cycles.shading_system=True','undeclared-osl-backend')
        edited=out/'edited-surface.blend'
        native(exe,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(producer/"0000.blend")!r},use_scripts=False)\n'+
            "shader=next(n for n in bpy.data.materials['red'].node_tree.nodes if n.bl_idname=='ShaderNodeBsdfPrincipled');shader.inputs['Emission Strength'].default_value=.25\n"+
            f'bpy.ops.wm.save_as_mainfile(filepath={str(edited)!r})\n')
        pinned=adopt(edited,out/'adopted-input');report['adoption']=pinned
        consumer=copy.deepcopy(d);consumer['production']={'assets':[{'id':'edition','file':pinned['reference'],'format':'blend'}]}
        workflow={'version':'schemaxis.workflow/1','operations':[{'id':'finish','document':consumer}]}
        held=[(edited,edited.with_suffix('.held')),(image,image.with_suffix('.held')),(producer,out/'producer.held')]
        try:
            for original,temporary in held:original.rename(temporary)
            result=execute(workflow,out/'workflow',blender=exe,timeout=300);assert result['verified'];packet=Path(result['jobs'][0]['directory'])
            record('edited-shader-adopted-with-precursors-absent',**pixels(packet,[[.25,0,0],*colours[1:]]))
            resumed=execute(workflow,out/'workflow',blender=exe,timeout=300,resume=True);assert resumed['verified'] and any(j.get('reused') for j in resumed['jobs'])
            record('pinned-shader-workflow-resume',reused=True)
            coforge(packet,"root=bpy.data.objects['edition'];records=json.loads(root['schemaxisAssetMembers']);member=bpy.data.objects[next(r['name'] for r in records if r['sourceName']=='patch')];mat=member.material_slots[0].material;shader=next(n for n in mat.node_tree.nodes if n.bl_idname=='ShaderNodeBsdfPrincipled');shader.inputs['Emission Strength'].default_value=1",'coforged-captured-pbr-shader')
        finally:
            for original,temporary in reversed(held):temporary.rename(original)
        cancel=threading.Event();cancel.set()
        with allocation({},cancel):fault=refused(lambda:run(d,out/'cancelled',executable=exe),{'RUNNER_CANCELLED'})
        assert json.loads((out/'cancelled/result.json').read_text())['verified'] is False;record('cancelled-incomplete',fault=fault)
        fault=refused(lambda:run(d,out/'timedout',executable=exe,timeout=.001),{'RUNNER_TIMED_OUT'})
        assert json.loads((out/'timedout/result.json').read_text())['verified'] is False;record('deadline-incomplete',fault=fault)
        run(d,out/'recovered',executable=exe,timeout=180)
        with location_context({'blender':exe}):assert verify(out/'recovered')['verified']
        record('fresh-run-recovers',**pixels(out/'recovered',colours));verify_identity(report,exe);report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
