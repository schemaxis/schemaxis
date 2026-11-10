"""Native shader authority: hidden state, embedded owners and forged witnesses."""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run, verify, _verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from qualify_blender_material_assignments import fixture
from qualify_blender_mesh_data import native
from qualify_blender_image_preview import png


def link(a, out, b, target):
    return {'from':{'node':a,'socket':out}, 'to':{'node':b,'socket':target}}


def material_document(inputs):
    d = fixture(); d['prepareOnly'] = True; p = d['production']
    for name, value in [('chart',[64,128,192,255]), ('alternate',[192,64,128,255])]:
        png(inputs/(name+'.png'), [value]*4)
    p['images'] = [{'id':'chart', 'file':str(inputs/'chart.png'), 'pack':False},
                   {'id':'alternate', 'file':str(inputs/'alternate.png')}]
    p['nodeGroups'] = [
        {'id':'InnerShader','family':'material','inputs':[],
         'outputs':[{'id':'surface','kind':'shader'}],
         'nodes':[{'id':'shader','kind':'principled','values':{'colour':[.2,.4,.6,1]}},
                  {'id':'out','kind':'output'}],
         'links':[link('shader','shader','out','surface')]},
        {'id':'OuterShader','family':'material','inputs':[],
         'outputs':[{'id':'surface','kind':'shader'}],
         'nodes':[{'id':'inner','kind':'group','group':'InnerShader'}, {'id':'out','kind':'output'}],
         'links':[link('inner','surface','out','surface')]}]
    red = p['materialGraphs'][0]
    red['nodes'] = [
        {'id':'colour','kind':'principled'},
        {'id':'normal','kind':'normalMap','values':{'colour':[.8,.5,.9,1]}},
        {'id':'texture','kind':'image','properties':{'image':'chart'}},
        {'id':'outer','kind':'group','group':'OuterShader'},
        {'id':'mix','kind':'mixShader','values':{'factor':.1}},
        {'id':'output','kind':'output'}]
    red['links'] = [link('normal','normal','colour','normal'), link('texture','colour','colour','colour'),
                    link('colour','shader','mix','a'), link('outer','surface','mix','b'),
                    link('mix','shader','output','surface')]
    return d


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blender', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); out = args.output.absolute(); out.mkdir(parents=True, exist_ok=False)
    inputs = out/'inputs'; inputs.mkdir()
    fingerprint = source_fingerprint('blender'); archive = hashlib.sha256(runtime_archive()).hexdigest()
    report = {'status':'running', 'providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
              'sourceFingerprint':fingerprint, 'runtimeArchiveSha256':archive,
              'qualifierSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'checks':[]}
    summary = out/'summary.json'
    def write(): summary.write_text(json.dumps(report,indent=2)+'\n')
    def exercise(label, packet, mutations):
        blend = packet/'0000.blend'; receipt = packet/'verification.json'; reopened = packet/'reopened.json'
        saved = {path:path.read_bytes() for path in (blend, receipt, reopened)}
        try:
            for name, mutation, positive in [('unchangedSave','',True),
                    *[(name, code, positive) for name, (code, positive) in mutations.items()]]:
                for path, value in saved.items(): path.write_bytes(value)
                witness = out/(label+'-'+name+'.json')
                code = ('import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'
                        +f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'
                        +'from schemaxis.adaptors.blender.production_native import observe\n'
                        +'from schemaxis.errors import SchemaxisError\n'
                        +'from schemaxis.adaptors.blender.adaptor import plan\n'
                        +'from schemaxis.adaptors.blender.production_references_native import shader_names\n'
                        +'from schemaxis.adaptors.blender.shader_fidelity_native import observe as shader_state\n'
                        +f'doc=json.loads(open({str(packet/"input.json")!r}).read());spec=doc["scenes"][0]["production"]\n'
                        +'master,selection,_=plan(doc);names=shader_names(master,selection)\n'
                        +'before=observe(spec);old=shader_state(*names) if any(names[:2]) else None\n'
                        +mutation+'\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'
                        +"readback_fault=None\ntry:after=observe(spec)\nexcept SchemaxisError as exc:after=before;readback_fault=exc.fault.to_dict()\n"
                        +"after['meshEditBaselines']=[];new=shader_state(*names) if any(names[:2]) else None\n"
                        +"result={'production':after,'shaders':new,'initialReadbackFault':readback_fault,'shaderStateChanged':old!=new,'sourceFidelityChanged':bool(before['assets']) and before['assets'][0]['fidelity']!=after['assets'][0]['fidelity']}\n"
                        +f'open({str(witness)!r},"w").write(json.dumps(result))\n')
                native(args.blender, code); actual = json.loads(witness.read_text())
                value = json.loads(saved[receipt])
                next(a for a in value['artifacts'] if a['file']==str(blend))['sha256'] = hashlib.sha256(blend.read_bytes()).hexdigest()
                value['states'][0]['production'] = actual['production']; receipt.write_text(json.dumps(value))
                value = json.loads(saved[reopened]); value['production'][0] = actual['production']
                assert 'shaders' not in value, 'shader authority must not require a stored signature'
                reopened.write_text(json.dumps(value)); fault = None
                with location_context({'blender':args.blender}):
                    try: _verify(packet)
                    except SchemaxisError as exc: fault = exc.fault.to_dict()
                record = {'case':label+'/'+name, 'accepted':fault is None, 'positive':positive,
                          'fault':fault, 'shaderStateChanged':actual['shaderStateChanged'],
                          'sourceFidelityChanged':actual['sourceFidelityChanged'],
                          'bothReadbacksReplaced':True, 'nativeHashRefreshed':True,
                          'initialReadbackFault':actual['initialReadbackFault']}
                report['checks'].append(record); write(); print(record['case'],flush=True)
                if positive: assert fault is None, record
                else:
                    message='native assets differ from trusted captured-source reconstruction' if label=='captured' else 'shader state differs from trusted authored-source reconstruction'
                    if label=='authored' and name=='nodeMute':message='node graph contains a muted node'
                    if label=='authored' and name=='previewActiveImage':message='material display texture helper differs'
                    assert fault and fault['code']=='VERIFICATION_FAILED' and fault['message']==message, record
                    assert actual['shaderStateChanged'] or actual['sourceFidelityChanged'], record
        finally:
            for path, value in saved.items(): path.write_bytes(value)
        with location_context({'blender':args.blender}): assert verify(packet)['verified']
        report['checks'].append({'case':label+'/restoredPublicPositive','accepted':True,'positive':True}); write()
    def receipt_versions(packet):
        receipt, reopened = packet/'verification.json', packet/'reopened.json'
        saved = {p:p.read_bytes() for p in (receipt,reopened)}
        native_hash = hashlib.sha256((packet/'0000.blend').read_bytes()).hexdigest()
        try:
            for label, version in [('obsoleteVersion','schemaxis.blender.asset-fidelity/1'),
                                   ('missingVersion',None),
                                   ('unknownVersion','schemaxis.blender.asset-fidelity/3'),
                                   ('collidingKeysRelabelled','schemaxis.blender.asset-fidelity/2')]:
                old = json.loads(saved[receipt]); fresh = json.loads(saved[reopened])
                fidelity = copy.deepcopy(old['states'][0]['production']['assets'][0]['fidelity'])
                assert fidelity['version']=='schemaxis.blender.asset-fidelity/2'
                if version is None: fidelity.pop('version')
                else: fidelity['version']=version
                if label=='collidingKeysRelabelled':
                    deps=fidelity['dependencies']; embedded=[k for k in deps if k.startswith('@embedded:')]
                    assert len(embedded)>=2
                    shared='ShaderNodeTree:Shader Nodetree'; tree=deps[embedded[0]]
                    for record in deps.values():
                        if record.get('type')=='Material' and record.get('tree') in embedded:record['tree']=shared
                    for key in embedded:del deps[key]
                    deps[shared]=tree
                old['states'][0]['production']['assets'][0]['fidelity']=fidelity
                fresh['production'][0]['assets'][0]['fidelity']=fidelity
                receipt.write_text(json.dumps(old));reopened.write_text(json.dumps(fresh))
                fault=None
                with location_context({'blender':args.blender}):
                    try:_verify(packet)
                    except SchemaxisError as exc:fault=exc.fault.to_dict()
                assert fault and fault['code']==('RERUN_REQUIRED' if label=='obsoleteVersion' else 'VERIFICATION_FAILED'),fault
                if label=='collidingKeysRelabelled':
                    assert fault['message']=='current native project/production output differs from retained readback',fault
                assert hashlib.sha256((packet/'0000.blend').read_bytes()).hexdigest()==native_hash
                report['checks'].append({'case':'captured/'+label,'accepted':False,'positive':False,
                    'fault':fault,'bothReadbacksReplaced':True,'nativeBytesUnchanged':True});write()
        finally:
            for path,value in saved.items():path.write_bytes(value)
        with location_context({'blender':args.blender}):assert _verify(packet)['verified']
        report['checks'].append({'case':'captured/restoredVersion2Positive','accepted':True,'positive':True});write()
    try:
        packet = out/'authored'; run(material_document(inputs), packet, executable=args.blender, timeout=240)
        with location_context({'blender':args.blender}): assert verify(packet)['verified']
        red = "bpy.data.materials['red']"
        node = red+".node_tree.nodes['colour']"
        exercise('authored',packet,{
            'subsurface':(node+".inputs['Subsurface Weight'].default_value=.75",False),
            'distribution':(node+".distribution='GGX'",False),
            'sheen':(node+".inputs['Sheen Weight'].default_value=.8",False),
            'materialSurfacePolicy':(red+".surface_render_method='BLENDED'",False),
            'materialBackface':(red+'.use_backface_culling=True',False),
            'cyclesEmissionSampling':(red+".cycles.emission_sampling='NONE'",False),
            'cyclesBumpCorrection':(red+'.cycles.use_bump_map_correction=False',False),
            'cyclesVolumeStep':(red+'.cycles.volume_step_rate=2',False),
            'lineArtMask':(red+'.lineart.use_material_mask=True',False),
            'readCyclesDefaults':("tuple(getattr("+red+".cycles,k) for k in ('emission_sampling','use_bump_map_correction','volume_step_rate'))",True),
            'normalSpace':(red+".node_tree.nodes['normal'].space='WORLD'",False),
            'normalConvention':(red+".node_tree.nodes['normal'].convention='DIRECTX'",False),
            'imageProjection':(red+".node_tree.nodes['texture'].projection='BOX'",False),
            'nestedSubsurface':("bpy.data.node_groups['InnerShader'].nodes['shader'].inputs['Subsurface Weight'].default_value=.5",False),
            'nodeMute':(node+'.mute=True',False),
            'previewActiveImage':(red+".node_tree.nodes.active="+red+".node_tree.nodes['texture']",False),
            'presentationLayout':(node+".location.x+=150;"+node+".label='artist layout';"+node+'.select=False',True)})
        consumer = out/'captured'
        source = out/'asset-source.blend'
        native(args.blender, 'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(packet/"0000.blend")!r},use_scripts=False)\n'+
               "for image in bpy.data.images:\n if image.source=='FILE':image.pack()\n"+
               f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n')
        run({'version':'schemaxis.blender.production/1','prepareOnly':True,
             'production':{'assets':[{'id':'source','file':str(source),'format':'blend'}]}},
            consumer, executable=args.blender, timeout=240)
        dependencies = json.loads((consumer/'reopened.json').read_text())['production'][0]['assets'][0]['fidelity']['dependencies']
        trees = [dependencies['Material:'+name]['tree'] for name in ('red','blue')]
        assert len(set(trees))==2 and all(name in dependencies for name in trees), trees
        report['embeddedOwnerTreeIds'] = trees; write()
        exercise('captured',consumer,{
            'secondEmbeddedShader':("bpy.data.materials['blue'].node_tree.nodes['colour'].inputs['Color'].default_value=[0,1,0,1]",False),
            'cyclesEmissionSampling':("bpy.data.materials['blue'].cycles.emission_sampling='NONE'",False),
            'cyclesVolumeStep':("bpy.data.materials['blue'].cycles.volume_step_rate=2",False),
            'lineArtMask':("bpy.data.materials['blue'].lineart.mat_occlusion=3",False),
            'nestedShader':("bpy.data.node_groups['InnerShader'].nodes['shader'].inputs['Subsurface Weight'].default_value=.6",False)})
        receipt_versions(consumer)
        assert source_fingerprint('blender')==fingerprint and hashlib.sha256(runtime_archive()).hexdigest()==archive
        report['status']='passed'
    finally:
        if report['status']=='running': report['status']='failed'
        write()


if __name__=='__main__': main()
