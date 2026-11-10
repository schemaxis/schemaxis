"""Current native preview controls, captured-source authority and resource lifecycle."""
import argparse,copy,hashlib,json,subprocess,threading
from pathlib import Path
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.adaptors.blender.adaptor import run,verify,_verify
from schemaxis.captured_inputs import adopt
from schemaxis.dispatch import allocation
from schemaxis.errors import SchemaxisError
from schemaxis.workflow import execute
from schemaxis.studio_library import load_library,instantiate_item
from qualify_blender_image_preview import fixture,png,FIRST,SECOND,ALPHA,FRACTIONAL,rgba
from qualify_blender_mesh_data import native
from blender_tamper import qualify


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.absolute();out.mkdir(parents=True,exist_ok=False);suite=a.suite.absolute();baseline=suite/'first-active-base-render-shifted';blender=a.blender
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':hashlib.sha256(runtime_archive()).hexdigest(),'checks':[]};summary=out/'summary.json'
    def record(label,**value):report['checks'].append({'case':label,**value});summary.write_text(json.dumps(report,indent=2)+'\n');print(label+' PASS',flush=True)
    def refused(call,codes):
        try:call()
        except SchemaxisError as error:
            assert error.fault.code in codes,error.fault.to_dict();return error.fault.to_dict()
        raise AssertionError('expected structured refusal')
    points=[(8,8),(24,8),(8,24),(24,24)]
    def pixels(directory,wanted):
        actual=rgba(directory,points);assert all(abs(x-y)<=1 for row,ref in zip(actual,wanted) for x,y in zip(row,ref)),(actual,wanted);return actual
    try:
        assert verify(baseline)['verified']
        preamble="tree=bpy.data.materials['surface'].node_tree;helper=tree.nodes['__schemaxis_display_texture'];mesh=bpy.data.objects['patch'].data\n"
        mutations={
            'previewImage':"helper.image=bpy.data.images['second']",
            'previewFlag':"helper.show_texture=False",
            'otherPreviewFlag':"tree.nodes['shaderSecond'].show_texture=True",
            'activeImageNode':"tree.nodes.active=tree.nodes['shaderSecond']",
            'previewProjection':"helper.projection='BOX'",
            'previewLink':"tree.links.new(helper.outputs['Color'],tree.nodes['emit'].inputs['Color'])",
            'alphaInterpretation':"bpy.data.images['first'].alpha_mode='PREMUL'",
            'colourSpace':"bpy.data.images['first'].colorspace_settings.name='Non-Color'",
            'packedPayload':"image=bpy.data.images['first'];image.unpack(method='REMOVE');image.filepath="+repr(str(suite/'inputs/second.png'))+";image.reload();image.pack()",
            'activeUV':"mesh.uv_layers.active_index=1",
            'renderUV':"mesh.uv_layers['base'].active_render=True",
            'imageFakeUser':"bpy.data.images['fractional'].use_fake_user=False"}
        record('refreshed-hash-native-controls',result=qualify(blender,[('preview',baseline)],mutations,preamble))
        source=suite/'inputs/first.png';original=source.read_bytes();source.rename(source.with_suffix('.held'))
        try:
            fault=refused(lambda:verify(baseline),{'RESOURCE_NOT_FOUND'});record('removed-original-refused',fault=fault)
            native(blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(baseline/"0000.blend")!r},use_scripts=False)\n'+"image=bpy.data.materials['surface'].node_tree.nodes['__schemaxis_display_texture'].image\nassert image.packed_file and image.name=='first'\n")
            record('packed-preview-reopens-with-original-absent')
        finally:source.with_suffix('.held').rename(source)
        assert verify(baseline)['verified'];record('restored-original-verifies')
        try:
            png(source,SECOND);record('changed-original-refused',fault=refused(lambda:verify(baseline),{'INPUT_CHANGED'}))
        finally:source.write_bytes(original)
        assert verify(baseline)['verified']
        # A deliberate native edit becomes a newly pinned input, never a rewrite
        # of the source declaration or its old receipt.
        edited=out/'edited-preview.blend'
        native(blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(baseline/"0000.blend")!r},use_scripts=False)\n'+"bpy.data.materials['surface'].node_tree.nodes['__schemaxis_display_texture'].image=bpy.data.images['second']\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(edited)!r})\n')
        pinned=adopt(edited,out/'adopted-input');report['adoption']=pinned
        d=copy.deepcopy(json.loads((baseline/'authored.json').read_text()));d['production']={'assets':[{'id':'edited','file':pinned['reference'],'format':'blend'}]}
        workflow={'version':'schemaxis.workflow/1','operations':[{'id':'adopted','document':d}]}
        target=out/'adopted-workflow';result=execute(workflow,target,blender=blender,timeout=360);assert result['verified'];consumer=Path(result['jobs'][0]['directory']);record('actual-captured-input-native-edit-adoption',encodedRGBA=pixels(consumer,SECOND))
        resumed=execute(workflow,target,blender=blender,timeout=360,resume=True);assert resumed['verified']
        assert any(x.get('reused') for x in resumed.get('jobs',[])),resumed
        record('unchanged-workflow-resume-reuses-verified-preview',result=resumed)
        # The submitted witness must not authorise a different captured material.
        blend=consumer/'0000.blend';receipt=consumer/'verification.json';reopened=consumer/'reopened.json';saved={x:x.read_bytes() for x in (blend,receipt,reopened)}
        current=out/'changed-fidelity.json'
        try:
            code='import bpy,json,sys\n'+f'sys.path.insert(0,{str(consumer/"runtime.zip")!r})\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+"root=bpy.data.objects['edited'];member=next(o for o in root.instance_collection.all_objects if o.type=='MESH');tree=member.data.materials[0].node_tree\nhelper=tree.nodes['__schemaxis_display_texture'];helper.show_texture=False\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+'from schemaxis.adaptors.blender.production_asset_snapshot import snapshot_asset_members\n'+f'open({str(current)!r},"w").write(json.dumps(snapshot_asset_members(root)))\n'
            native(blender,code);fidelity=json.loads(current.read_text());r=json.loads(saved[receipt]);next(x for x in r['artifacts'] if x['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();r['states'][0]['production']['assets'][0]['fidelity']=fidelity;receipt.write_text(json.dumps(r));r=json.loads(saved[reopened]);r['production'][0]['assets'][0]['fidelity']=fidelity;reopened.write_text(json.dumps(r))
            fault=refused(lambda:_verify(consumer),{'VERIFICATION_FAILED'});assert fault['message']=='fresh native production readback refused current project',fault
            record('captured-preview-flag-authority-refuses-replaced-fidelity',fault=fault)
        finally:
            for path,data in saved.items():path.write_bytes(data)
        assert verify(consumer)['verified']
        # Real public resource refusal and an actual native recovery use fresh
        # output directories; failed partial runs never become reusable outputs.
        recovery=copy.deepcopy(json.loads((baseline/'authored.json').read_text()));missing=out/'recovery.png';recovery['production']['images'][0]['file']=str(missing)
        record('public-missing-input',fault=refused(lambda:run(recovery,out/'missing',executable=blender),{'RESOURCE_NOT_FOUND'}))
        missing.write_bytes(original);run(recovery,out/'recovered',executable=blender,timeout=360);assert verify(out/'recovered')['verified'];record('resource-restoration-new-run-recovers',encodedRGBA=pixels(out/'recovered',FIRST))
        cancel=threading.Event();cancel.set()
        with allocation({},cancel):fault=refused(lambda:run(recovery,out/'cancelled',executable=blender),{'RUNNER_CANCELLED'})
        assert json.loads((out/'cancelled/result.json').read_text())['verified'] is False;record('cancelled-native-submission-stays-incomplete',fault=fault)
        record('short-native-deadline-stays-incomplete',fault=refused(lambda:run(recovery,out/'timedout',executable=blender,timeout=.001),{'RUNNER_TIMED_OUT'}))
        assert json.loads((out/'timedout/result.json').read_text())['verified'] is False
        library=load_library('blender');starter=next(x for x in library['templates'] if x['id']=='image-preview')
        runnable=instantiate_item(library,starter);runnable['production']['images'][0]['file']=str((Path(__file__).resolve().parents[1]/'examples/schemaxis/blender-image-preview.png'))
        run(runnable,out/'studio-starter',executable=blender,timeout=360);assert verify(out/'studio-starter')['verified'];record('actual-filled-studio-starter',encodedRGBA=pixels(out/'studio-starter',FIRST))
        report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        summary.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    with location_context({'blender':__import__('sys').argv[__import__('sys').argv.index('--blender')+1]}):main()
