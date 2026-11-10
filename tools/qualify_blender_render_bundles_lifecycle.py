"""Scientific bundle/source lifecycle and refreshed semantic attack controls.

Requires a passed public A/B/C suite. EXR-only mutants deliberately keep native
witnesses unchanged: there is no persisted decoded-data authority to coforge.
Native mutations replace BOTH complete actual readbacks where structurally valid.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import textwrap
import threading
from unittest.mock import patch

from schemaxis.adaptors.blender.adaptor import run, verify
from schemaxis.captured_inputs import adopt
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.publication_metadata import finalise, MANIFEST
from schemaxis.workflow import execute
from schemaxis.png import read as read_png
from blender_surface_evidence import identity, verify_identity
from qualify_blender_render_bundles import fixture, bundle, digest, analysis_oracle, assembly_oracle, native, EXAMPLES
import blender_bundle_oracles as O


def decode_multilayer(executable, paths, folder):
    """Exercise the fixed SDK's selected Image-node pass, including baseline.

    Multilayer Image.size/pixels without a selected pass is not a format oracle.
    This empty four-pixel SDK scene only composites retained image data; it does
    not reopen or rerender the source geometry.
    """
    folder = Path(folder)
    code = ('import bpy,json\nfrom pathlib import Path\n'
        'bpy.ops.wm.read_factory_settings(use_empty=True)\ns=bpy.context.scene\n'
        's.render.engine="CYCLES";s.cycles.device="CPU";s.cycles.samples=1\n'
        's.cycles.use_denoising=False;s.cycles.use_adaptive_sampling=False\n'
        's.render.resolution_x=4;s.render.resolution_y=4;s.render.resolution_percentage=100\n'
        's.render.threads_mode="FIXED";s.render.threads=2\n'
        'c=bpy.data.cameras.new("sdk-camera");o=bpy.data.objects.new("sdk-camera",c)\n'
        's.collection.objects.link(o);s.camera=o\n'
        's.view_settings.view_transform="Standard";s.view_settings.look="None"\n'
        's.view_settings.exposure=0;s.view_settings.gamma=1\n'
        f'paths={[str(p) for p in paths]!r}\nrecords=[]\n'
        'for index,path in enumerate(paths):\n'
        ' image=bpy.data.images.load(path,check_existing=False)\n'
        ' tree=bpy.data.node_groups.new("sdk-decode-"+str(index),"CompositorNodeTree")\n'
        ' tree.interface.new_socket(name="Image",in_out="OUTPUT",socket_type="NodeSocketColor")\n'
        ' s.compositing_node_group=tree\n'
        ' source=tree.nodes.new("CompositorNodeImage");source.image=image;bpy.context.view_layer.update()\n'
        ' output=source.outputs.get("combined");assert output is not None and output.enabled\n'
        ' root=tree.nodes.new("NodeGroupOutput");tree.links.new(output,root.inputs["Image"])\n'
        ' writer=tree.nodes.new("CompositorNodeOutputFile")\n'
        f' writer.directory={str(folder)!r};writer.file_name="decode-"+str(index)+"-####"\n'
        ' writer.format.media_type="IMAGE";writer.format.file_format="PNG"\n'
        ' writer.format.color_depth="8";writer.format.color_mode="RGBA";writer.save_as_render=True\n'
        ' writer.file_output_items.new("RGBA","image");tree.links.new(output,writer.inputs["image"])\n'
        ' assert len(s.objects)==1 and bpy.ops.render.render(write_still=False)=={"FINISHED"}\n'
        ' records.append({"input":path,"output":"decode-"+str(index)+"-0001image.png"})\n'
        ' s.compositing_node_group=None;bpy.data.node_groups.remove(tree);bpy.data.images.remove(image)\n'
        f'open({str(folder/"decoded.json")!r},"w").write(json.dumps(records))\n')
    native(executable, code, folder)
    records = json.loads((folder/'decoded.json').read_text())
    decoded = []
    for row in records:
        image = read_png(folder/row['output']);assert image[:2] == (128, 128)
        decoded.append(image)
        row['inputSHA256'] = digest(row['input'])
        row['decodedPNG_SHA256'] = digest(folder/row['output'])
    assert len(records) == len(paths) == 3 and all(image == decoded[0] for image in decoded)
    return {'fixedRuntimeSelectedPass': True, 'baselineAndMutantBeautyPixelsIdentical': True, 'records': records}


def saved_packet(packet, extra=()):
    return {p: p.read_bytes() for p in [packet/'0000.blend', packet/'verification.json', packet/'reopened.json',
        packet/MANIFEST, *packet.rglob('*.metadata.json'), *extra]}


def restore(saved):
    for path, content in saved.items():
        if not path.is_file() or path.read_bytes() != content: path.write_bytes(content)
    assert all(path.is_file() and path.read_bytes() == content for path, content in saved.items())


def refresh_hash(packet, path):
    receipt = packet/'verification.json'; value = json.loads(receipt.read_text())
    entries = [a for a in value['artifacts'] if a['file'] == str(path)]; assert len(entries) == 1
    entries[0]['sha256'] = digest(path); receipt.write_text(json.dumps(value)); finalise(packet)


def refused(call, message=None):
    try: call()
    except SchemaxisError as error:
        fault = error.fault.to_dict()
        assert fault['code'] == 'VERIFICATION_FAILED', fault
        if message is not None: assert fault['message'] == message, fault
        return fault
    raise AssertionError('public verification accepted the semantic mutant')


class NativeOpenAudit:
    """Instrument actual host launches, including isolated provider runners.

    Retaining and replacing the wm module is necessary: bpy.ops otherwise
    creates a throwaway module wrapper on attribute access. A successful public
    verification must demonstrate that this instrumentation sees candidate opens
    before its absence can establish an EXR-first refusal.
    """
    def __init__(self, executable, log):
        self.executable = Path(executable).resolve()
        self.log = Path(log)
        self.original_popen = subprocess.Popen
        self.scripts = []

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def __call__(self, command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and command and Path(command[0]).resolve() == self.executable and '--python' in command:
            script = Path(command[command.index('--python')+1]); code = script.read_text()
            if 'from schemaxis.adaptors.blender.native import reopen' in code:
                audit = ('import bpy as _a,json as _j,hashlib as _h\nfrom pathlib import Path as _P\n'
                    '_had_wm="wm" in vars(_a.ops)\n_old_wm=vars(_a.ops).get("wm")\n'
                    '_wm=_a.ops.wm\n_open=_wm.open_mainfile\ndef _audit(*args,**kwargs):\n'
                    ' p=str(kwargs.get("filepath",args[0] if args else ""))\n'+
                    f' with open({str(self.log)!r},"a") as stream:stream.write(_j.dumps({{"path":p,"sha256":_h.sha256(_P(p).read_bytes()).hexdigest()}})+"\\n")\n'+
                    ' return _open(*args,**kwargs)\n_wm.open_mainfile=_audit\n_a.ops.wm=_wm\n')
                combined = audit+'try:\n'+textwrap.indent(code, '    ')+'finally:\n    if _had_wm:_a.ops.wm=_old_wm\n    else:delattr(_a.ops,"wm")\n'
                ast.parse(combined, filename=str(script)); compile(combined, str(script), 'exec')
                self.scripts.append({'path': str(script), 'originalSha256': digest(script),
                    'auditedSha256': hashlib.sha256(combined.encode()).hexdigest()})
                script.write_text(combined)
        return self.original_popen(command, *args, **kwargs)


def actual_readback_script(packet, reference_directory, witness, mutation):
    """Fresh nominate/admit before edit; observe an actual RENDER after edit."""
    return ('import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'+
        'from schemaxis.adaptors.blender.adaptor import plan\nfrom schemaxis.adaptors.blender.production_references_native import references\n'+
        f'master,selection,prepared=plan(json.loads(open({str(packet/"input.json")!r}).read()))\n'+
        f'sources=json.loads(open({str(packet/"sources.json")!r}).read())\n'+
        f'fresh=references(master,selection,prepared,next(iter(selection.visits())),sources,reference_directory={str(reference_directory)!r})\n'+
        f'bpy.ops.wm.open_mainfile(filepath={str(packet/"0000.blend")!r},use_scripts=False)\n'+
        'from schemaxis.adaptors.blender.render_features_native import Features\nfrom schemaxis.adaptors.blender.shader_budget_native import ShaderBudget\n'+
        'spec=master.document["scenes"][0]["production"];budget=ShaderBudget()\n'+
        'features=Features.current(spec,fresh["featureBindings"],shader_budget=budget)\n'+
        'features.admit_source(fresh["featureShading"])\n'+mutation+'\n'+
        'from schemaxis.adaptors.blender.render_writers_native import suppress\n'+
        'with suppress(bpy.context.scene),features.capture_render():\n    assert bpy.ops.render.render(write_still=False)=={"FINISHED"}\n'+
        'bpy.context.preferences.filepaths.save_version=0\n'+
        f'bpy.ops.wm.save_as_mainfile(filepath={str(packet/"0000.blend")!r})\n'+
        'from schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+
        f'open({str(witness)!r},"w").write(json.dumps({{"state":snapshot(selection.order,features=features),"production":observe(spec,objects=features.production.objects,shader_budget=budget,features=features)}}))\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True); parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--examples', type=Path, default=EXAMPLES)
    args = parser.parse_args(); suite = args.suite.absolute(); out = args.output.absolute(); out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', **identity(out, args.blender), 'checks': [], 'restoration': []}; target = out/'summary.json'
    def write(): target.write_text(json.dumps(report, indent=2)+'\n')
    def record(case, **facts):
        report['checks'].append({'case': case, **facts}); write(); print(case+' PASS', flush=True)
    def positive(packet):
        with location_context({'blender': args.blender}): assert verify(packet)['verified']
    def scientific_attack(packet, path, mutant, label, expected_message):
        saved = saved_packet(packet, [path]); baseline_native = digest(packet/'0000.blend'); log = out/(label+'-native-opens.jsonl')
        audit = NativeOpenAudit(args.blender, log)
        try:
            with patch.object(subprocess, 'Popen', audit), location_context({'blender': args.blender}):
                assert verify(packet)['verified']
                positive_opens = audit.records()
                assert audit.scripts and any(row['sha256'] == baseline_native for row in positive_opens), 'native-open audit lacks an actual candidate-byte positive control'
                (out/(label+'-positive-native-opens.jsonl')).write_bytes(log.read_bytes())
                log.write_text('')
                path.write_bytes(mutant.read_bytes()); refresh_hash(packet, path)
                fault = refused(lambda: verify(packet), expected_message)
            opens = audit.records()
            assert not any(Path(row['path']) == packet/'0000.blend' or row['sha256'] == baseline_native for row in opens), opens
            assert digest(packet/'0000.blend') == baseline_native
            for name in ('reopened.json',): assert (packet/name).read_bytes() == saved[packet/name]
            mutant_dir = out/'mutants'/label; mutant_dir.mkdir(parents=True)
            for p in saved:
                # Runtime ZIPs never enter this set; keep exactly the attacked
                # EXR/native/readback/metadata originals for reproducibility.
                destination = mutant_dir/p.relative_to(packet); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(p.read_bytes())
            record(label, publicFault=fault, nativeWitnessesUnchanged=True, decodedWitnesses='not present by contract',
                   nativeSHAUnchanged=baseline_native, refreshedArtifactAndCommonMetadata=True, candidateOpened=False, nativeOpens=opens)
            report['checks'][-1].update(positiveNativeOpens=positive_opens, auditedScripts=audit.scripts); write()
        finally:
            restore(saved); report['restoration'].append({'case': label, 'exact': True}); write()
        positive(packet); record(label+'-restored-public-positive')
    def native_attack(packet, mutation, label, complete_witness=True):
        saved = saved_packet(packet); folder = out/label; witness = folder/'actual.json'
        try:
            if complete_witness:
                code = actual_readback_script(packet, folder/'trusted-reference', witness, mutation)
            else:
                code = ('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(packet/"0000.blend")!r},use_scripts=False)\n'+
                    mutation+'\nbpy.context.preferences.filepaths.save_version=0\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(packet/"0000.blend")!r})\n')
            native(args.blender, code, folder, timeout=180)
            receipt, reopened = packet/'verification.json', packet/'reopened.json'
            if complete_witness:
                current = json.loads(witness.read_text()); prior = json.loads(saved[receipt])['states'][0]['production']
                current['production']['meshEditBaselines'] = prior['meshEditBaselines']
                assert current['production'].keys() == prior.keys()
                assert current['production']['renderFeatures'] != prior['renderFeatures']
                value = json.loads(saved[receipt]); value['states'][0].update(snapshot=current['state'], production=current['production']); receipt.write_text(json.dumps(value))
                value = json.loads(saved[reopened]); value['states'][0] = current['state']; value['production'][0] = current['production']; reopened.write_text(json.dumps(value))
            refresh_hash(packet, packet/'0000.blend')
            with location_context({'blender': args.blender}): fault = refused(lambda: verify(packet))
            assert fault['message'] != 'fresh-process scene state differs', fault
            mutant = folder/'mutant'; mutant.mkdir()
            for p in saved:
                destination = mutant/p.relative_to(packet); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(p.read_bytes())
            record(label, candidateNativeSHA256=digest(packet/'0000.blend'), publicFault=fault, bothCompleteActualWitnessesReplaced=complete_witness,
                   oldWitnessesRetainedForStructuralRefusal=not complete_witness)
        finally:
            restore(saved); report['restoration'].append({'case': label, 'exact': True}); write()
        positive(packet); record(label+'-restored-public-positive')
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt('bounded termination')))
    try:
        prior = json.loads((suite/'summary.json').read_text()); assert prior['status'] == 'passed'
        assert prior.get('phase') == 'all' and {'analysis','artist','assembly-source','assembly'} <= set(prior['fixtures']), 'lifecycle needs a complete A/B/C suite'
        assert prior['sourceFingerprint'] == report['sourceFingerprint'] and prior['runtimeArchiveSha256'] == report['runtimeArchiveSha256']
        # A declared NONE variant permits exact sample-byte edits without
        # pretending a compressed payload tail is a meaningful EXR mutation.
        document = fixture('analysis', args.examples)
        document['production']['renderBundles'][0]['outputs'][1]['compression'] = 'none'
        packet = out/'scientific-none'; run(document, packet, executable=args.blender, timeout=300); positive(packet)
        path = bundle(packet, 'science', 'numeric', 1); record('NONE-scientific-literal', oracle=analysis_oracle(path, 1))
        sample, manifest = out/'sample.exr', out/'manifest.exr'
        O.mutate_none_sample(path, sample, 'temperature.V', [70, 50], 301)
        O.mutate_manifest_member(path, manifest, 'objectMatte_matte', 'panel', 'hello', '248bfa47')
        # A second independent native decoder admits both complete image files.
        decoded = decode_multilayer(args.blender, (path, sample, manifest), out/'valid-mutant-native-decode')
        record('both-complete-EXR-mutants-format-valid', native=decoded)
        scientific_attack(packet, path, sample, 'valid-scientific-sample', 'scientific render planes differ from fresh trusted source reconstruction')
        scientific_attack(packet, path, manifest, 'valid-Cryptomatte-membership', 'scientific render metadata differs from fresh trusted source reconstruction')
        artist = Path(prior.get('reusedArtist', {}).get('directory', suite/'artist'))
        native_attack(artist, "bpy.context.scene.view_layers['beauty'].pass_alpha_threshold=.25", 'coforged-layer-threshold')
        native_attack(artist, "next(n for n in bpy.data.worlds['studio'].node_tree.nodes if n.bl_idname=='ShaderNodeBackground').inputs['Color'].default_value=(.7,.2,.1,1)", 'coforged-World-shader')
        native_attack(artist, "bpy.context.scene.view_layers['inspection'].world_override=bpy.data.worlds['studio']", 'structural-World-pointer', False)
        native_attack(artist, "next(n for n in bpy.data.worlds['studio'].node_tree.nodes if n.bl_idname=='ShaderNodeOutputAOV').aov_name='wrongTag'", 'structural-AOV-pointer', False)
        # Reopen the untouched saved compositor and inspect its literal managed
        # relative paths without executing inherited writers.
        source_native = suite/'assembly-source/0000.blend'; source_sha = digest(source_native)
        writer_native = artist/'0000.blend'; writer_sha = digest(writer_native)
        native(args.blender, 'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(writer_native)!r},use_scripts=False)\n'+
            'tree=bpy.context.scene.compositing_node_group\nwriters=[n for n in tree.nodes if n.bl_idname=="CompositorNodeOutputFile"]\nassert len(writers)==2\n'+
            'assert all(n.directory=="//renders/bundles" and "####" in n.file_name for n in writers)\n', out/'relative-writer-reopen')
        assert digest(writer_native) == writer_sha; record('untouched-relative-writer-fresh-reopen', nativeSHA=writer_sha)
        pinned = adopt(source_native, out/'adopted-source'); document = fixture('assembly', args.examples)
        for asset in document['production']['assets']: asset['file'] = pinned['reference']
        workflow = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'assembly', 'document': document}]}
        held = source_native.parent.with_name(source_native.parent.name+'-retired-by-bundle-qualifier')
        assert not held.exists(); source_native.parent.rename(held)
        try:
            result = execute(workflow, out/'retired-workflow', blender=args.blender, timeout=300); assert result['verified']
            consumer = Path(result['jobs'][0]['directory']); positive(consumer)
            record('adopted-whole-producer-retired-Engine', oracle=assembly_oracle(bundle(consumer, 'assembly', 'parts', 1), fixture('assembly-source', args.examples), 1))
            resumed = execute(workflow, out/'retired-workflow', blender=args.blender, timeout=300, resume=True)
            assert resumed['verified'] and any(job.get('reused') for job in resumed['jobs']), resumed
            record('retired-source-verified-workflow-reuse')
        finally:
            restored = False
            try:
                if not source_native.parent.exists() and held.is_dir(): held.rename(source_native.parent)
                restored = source_native.is_file() and digest(source_native) == source_sha and not held.exists()
            except Exception as error:
                report['retirementRestorationError'] = repr(error)
            report['restoration'].append({'case': 'producer-retirement', 'exact': restored}); write()
        assert restored, 'producer was not restored exactly; unknown replacement paths are never overwritten'
        cancel = threading.Event(); cancel.set()
        with allocation({}, cancel):
            try: run(fixture('analysis', args.examples), out/'cancelled', executable=args.blender)
            except SchemaxisError as error: assert error.fault.code == 'RUNNER_CANCELLED'; record('cancelled-incomplete', fault=error.fault.to_dict())
            else: raise AssertionError('pre-cancelled bundle run accepted')
        assert json.loads((out/'cancelled/result.json').read_text())['verified'] is False
        try: run(fixture('analysis', args.examples), out/'deadline', executable=args.blender, timeout=.001)
        except SchemaxisError as error: assert error.fault.code == 'RUNNER_TIMED_OUT'; record('deadline-incomplete', fault=error.fault.to_dict())
        else: raise AssertionError('expired bundle run accepted')
        assert json.loads((out/'deadline/result.json').read_text())['verified'] is False
        recovery = out/'recovery'; run(fixture('analysis', args.examples), recovery, executable=args.blender, timeout=300); positive(recovery)
        record('fresh-bundle-recovery', oracle=analysis_oracle(bundle(recovery, 'science', 'numeric', 12), 12))
        assert all(row['exact'] for row in report['restoration']); verify_identity(report, args.blender); report['status'] = 'passed'
    finally:
        if report['status'] == 'running': report['status'] = 'failed'
        signal.signal(signal.SIGTERM, previous); write()


if __name__ == '__main__': main()
