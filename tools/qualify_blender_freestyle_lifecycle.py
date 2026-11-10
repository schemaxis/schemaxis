"""Public NPR edit, coforged-source authority, pinned PLY and recovery controls.

Requires the completed public raster suite from qualify_blender_freestyle.py.
Every producer modification is qualifier-owned and restored in finally; adopted
snapshots remain present while their original paths and producer are retired.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import threading

from schemaxis.adaptors.blender.adaptor import run, verify
from schemaxis.captured_inputs import adopt
from schemaxis.configuration import location_context
from schemaxis.dispatch import allocation
from schemaxis.errors import SchemaxisError
from schemaxis.publication_metadata import finalise, MANIFEST
from schemaxis.workflow import execute
from blender_surface_evidence import identity, verify_identity
from qualify_blender_freestyle import fixture, image, plate_oracle, sphere_oracle


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refused(call, codes):
    try:
        call()
    except SchemaxisError as error:
        assert error.fault.code in codes, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('expected structured refusal')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True); parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); out = args.output.absolute(); out.mkdir(parents=True, exist_ok=False)
    suite = args.suite.absolute(); baseline = suite/'material-sphere'
    report = {'status': 'running', **identity(out, args.blender), 'checks': [], 'restoration': []}
    target = out/'summary.json'; sequence = 0
    def write(): target.write_text(json.dumps(report, indent=2)+'\n')
    def record(case, **value):
        report['checks'].append({'case': case, **value}); write(); print(case+' PASS', flush=True)
    def native(code, label):
        nonlocal sequence
        sequence += 1; folder = out/f'{sequence:02d}-{label}'; folder.mkdir()
        script = folder/'check.py'; script.write_text(code)
        result = subprocess.run([args.blender, '--background', '--factory-startup', '--disable-autoexec',
            '--threads', '2', '--python-exit-code', '1', '--python', str(script)],
            timeout=90, capture_output=True, text=True)
        (folder/'stdout.log').write_text(result.stdout); (folder/'stderr.log').write_text(result.stderr)
        assert result.returncode == 0, (label, result.returncode, result.stdout[-4000:], result.stderr[-4000:])
    def coforge(packet, mutation, label, render_edit=False, actual_witness=True):
        blend = packet/'0000.blend'; receipt = packet/'verification.json'; reopened = packet/'reopened.json'
        paths = [blend, receipt, reopened, packet/MANIFEST, *packet.glob('*.metadata.json')]
        saved = {p: p.read_bytes() for p in paths}
        witness = out/(label+'-observed.json'); rendered = out/(label+'-edited.png')
        try:
            render = (f'bpy.context.scene.render.filepath={str(rendered)!r}\nbpy.ops.render.render(write_still=True)\n'
                      if render_edit else '')
            reference = ('from schemaxis.adaptors.blender.adaptor import plan\n'+
                'from schemaxis.adaptors.blender.production_references_native import references\n'+
                f'master,selection,prepared=plan(json.loads(open({str(packet/"input.json")!r}).read()))\n'+
                f'sources=json.loads(open({str(packet/"sources.json")!r}).read())\n'+
                'fresh=references(master,selection,prepared,next(iter(selection.visits())),sources)\n'
                if actual_witness else '')
            readback = ('from schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+
                'from schemaxis.adaptors.blender.render_features_native import Features\nfrom schemaxis.adaptors.blender.shader_budget_native import ShaderBudget\n'+
                'spec=master.document["scenes"][0]["production"]\nbudget=ShaderBudget()\n'+
                'features=Features.current(spec,fresh["featureBindings"],shader_budget=budget)\n'+
                f'open({str(witness)!r},"w").write(json.dumps({{"state":snapshot(selection.order),"production":observe(spec,objects=features.production.objects,shader_budget=budget,features=features)}}))\n'
                if actual_witness else '')
            native('import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'+reference+
                f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+
                'bpy.context.preferences.filepaths.save_version=0\n'+mutation+'\n'+render+
                f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+
                readback, label)
            if render_edit:
                from schemaxis.png import read
                record(label+'-literal-native-edit', independentRaster=sphere_oracle(read(rendered), 6))
                reopened_image = out/(label+'-fresh-reopen.png')
                native('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+
                    f'bpy.context.scene.render.filepath={str(reopened_image)!r}\nbpy.ops.render.render(write_still=True)\n', label+'-fresh-reopen')
                record(label+'-fresh-native-reopen', independentRaster=sphere_oracle(read(reopened_image), 6))
            observed = (json.loads(witness.read_text()) if actual_witness else
                        {'state': json.loads(saved[receipt])['states'][0]['snapshot'],
                         'production': json.loads(saved[receipt])['states'][0]['production']})
            # Other owners' original mesh-edit baselines remain exact. They do
            # not authorise NPR. Width/priority cases replace both witnesses
            # from actual readback; the structurally invalid pointer case keeps
            # the old witnesses because the native observer itself refuses it.
            if 'meshEditBaselines' in json.loads(saved[receipt])['states'][0]['production']:
                observed['production']['meshEditBaselines'] = json.loads(saved[receipt])['states'][0]['production']['meshEditBaselines']
            if actual_witness:
                old_production = json.loads(saved[receipt])['states'][0]['production']
                assert observed['production'].keys() == old_production.keys()
                assert observed['production']['renderFeatures']['npr'] != old_production['renderFeatures']['npr']
            value = json.loads(saved[receipt]); value['states'][0].update(snapshot=observed['state'], production=observed['production'])
            next(a for a in value['artifacts'] if a['file'] == str(blend))['sha256'] = digest(blend)
            receipt.write_text(json.dumps(value))
            value = json.loads(saved[reopened]); value['states'][0] = observed['state']; value['production'][0] = observed['production']
            reopened.write_text(json.dumps(value)); finalise(packet)
            with location_context({'blender': args.blender}): fault = refused(lambda: verify(packet), {'VERIFICATION_FAILED'})
            mutant = out/'mutants'/label; mutant.mkdir(parents=True)
            for path in saved: (mutant/path.name).write_bytes(path.read_bytes())
            record(label, publicFault=fault, bothWitnessesReplacedWithActualReadback=actual_witness, nativeSHAAndPublicationRefreshed=True)
        finally:
            restoration = {'case': label, 'restored': False}
            try:
                for path, content in saved.items(): path.write_bytes(content)
                restoration['restored'] = all(path.read_bytes() == content for path, content in saved.items())
            except Exception as error:
                restoration['error'] = repr(error)
            report['restoration'].append(restoration); write()
        assert restoration['restored'], restoration
        with location_context({'blender': args.blender}): assert verify(packet)['verified']
        record(label+'-restored-public-positive')
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame): raise KeyboardInterrupt('bounded supervisor terminated NPR lifecycle')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        # The suite must be from this exact provider, never merely self-reported.
        suite_report = json.loads((suite/'summary.json').read_text())
        assert suite_report['status'] == 'passed'
        assert suite_report['sourceFingerprint'] == report['sourceFingerprint']
        assert suite_report['runtimeArchiveSha256'] == report['runtimeArchiveSha256']
        with location_context({'blender': args.blender}): assert verify(baseline)['verified']
        sphere_oracle(image(baseline)); record('baseline-current-public-positive')
        coforge(baseline, "bpy.data.linestyles['__schemaxis_npr_style_0'].thickness=6", 'coforged-width', True)
        coforge(baseline, "bpy.context.scene.view_layers['technical'].freestyle_settings.linesets[0].linestyle=bpy.data.linestyles['__schemaxis_npr_style_1']", 'refreshed-style-pointer', actual_witness=False)
        coforge(baseline, "bpy.data.materials['lower'].line_priority=0", 'coforged-material-priority')
        # A native unchanged save may alter container bytes, but not source intent.
        blend = baseline/'0000.blend'; before = blend.read_bytes()
        saved_metadata = {p: p.read_bytes() for p in [baseline/'verification.json', baseline/'reopened.json', baseline/MANIFEST, *baseline.glob('*.metadata.json')]}
        try:
            native('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+
                'bpy.context.preferences.filepaths.save_version=0\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n', 'unchanged-save')
            receipt = baseline/'verification.json'; value = json.loads(receipt.read_text())
            next(a for a in value['artifacts'] if a['file'] == str(blend))['sha256'] = digest(blend)
            receipt.write_text(json.dumps(value)); finalise(baseline)
            with location_context({'blender': args.blender}): assert verify(baseline)['verified']
            record('native-unchanged-save-public-positive')
        finally:
            blend.write_bytes(before)
            for path, content in saved_metadata.items(): path.write_bytes(content)
        assert blend.read_bytes() == before
        # Pin a real PLY input through the common captured-input Engine boundary.
        inputs = out/'inputs'; inputs.mkdir(); original = inputs/'plate.ply'
        original.write_text('ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n-2 0 -1.5\n2 0 -1.5\n2 0 1.5\n-2 0 1.5\n4 0 1 2 3\n')
        source = adopt(original, out/'pinned-plate'); report['adoption'] = source
        d = fixture(); p = copy.deepcopy(d['production']); p['objects'] = p['objects'][1:]
        p['materialBindings'] = [{'object': 'source', 'material': 'white'}]
        p['npr']['layers'][0]['lineSets'][1]['scope'] = {'kind': 'objects', 'objects': ['source']}
        document = {'version': 'schemaxis.blender/1', 'nodes': [
            {'id': 'source', 'filter': 'readPLY', 'options': {'file': source['reference']}}],
            'scenes': [{'id': 'main', 'visible': ['source', 'occluder'], 'production': p,
                        'render': d['render'], 'images': [{'id': 'preview', 'size': d['size'], 'cameras': d['cameras']}]}]}
        workflow = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'drawing', 'document': document}]}
        producer = out/'pinned-workflow'
        result = execute(workflow, producer, blender=args.blender, timeout=240); assert result['verified']
        packet = Path(result['jobs'][0]['directory']); record('pinned-ply-public-engine', independentRaster=plate_oracle(image(packet)))
        retained_artifacts = json.loads((packet/'verification.json').read_text())['artifacts']
        producer_pins = {Path(item['file']): digest(item['file']) for item in retained_artifacts}
        producer_pins.update({packet/name: digest(packet/name) for name in ('authored.json', 'input.json')})
        original_bytes = original.read_bytes(); held = original.with_suffix('.held')
        producer_held = out/'pinned-workflow-held'; original.rename(held)
        try:
            with location_context({'blender': args.blender}): assert verify(packet)['verified']
            record('original-ply-absent-public-verify', snapshotRetained=True)
            result = execute(workflow, producer, blender=args.blender, timeout=240, resume=True)
            assert result['verified'] and any(job.get('reused') for job in result['jobs']), result
            record('original-ply-absent-workflow-resume', verifiedReuse=True)
            producer.rename(producer_held)
            result = execute(workflow, out/'retired-new-consumer', blender=args.blender, timeout=240)
            assert result['verified']; record('whole-original-producer-retired-new-consumer', independentRaster=plate_oracle(image(Path(result['jobs'][0]['directory']))))
        finally:
            if producer_held.exists() and not producer.exists(): producer_held.rename(producer)
            if held.exists() and not original.exists(): held.rename(original)
            restored = (original.is_file() and original.read_bytes() == original_bytes and producer.is_dir()
                        and all(path.is_file() and digest(path) == expected for path, expected in producer_pins.items()))
            report['restoration'].append({'case': 'pinned-ply-retirement', 'restored': restored,
                                          'actualProducerArtifactAndIntentSHA256': {str(path): digest(path) if path.is_file() else None for path in producer_pins},
                                          'expectedProducerArtifactAndIntentSHA256': {str(path): value for path, value in producer_pins.items()}}); write()
        assert restored
        cancel = threading.Event(); cancel.set()
        with allocation({}, cancel): fault = refused(lambda: run(fixture(), out/'cancelled', executable=args.blender), {'RUNNER_CANCELLED'})
        assert json.loads((out/'cancelled/result.json').read_text())['verified'] is False
        record('cancelled-incomplete', fault=fault)
        fault = refused(lambda: run(fixture(), out/'timedout', executable=args.blender, timeout=.001), {'RUNNER_TIMED_OUT'})
        assert json.loads((out/'timedout/result.json').read_text())['verified'] is False
        record('deadline-incomplete', fault=fault)
        run(fixture(), out/'recovered', executable=args.blender, timeout=240)
        with location_context({'blender': args.blender}): assert verify(out/'recovered')['verified']
        record('fresh-recovery', independentRaster=plate_oracle(image(out/'recovered')))
        assert all(entry['restored'] for entry in report['restoration'])
        verify_identity(report, args.blender); report['status'] = 'passed'
    finally:
        if report['status'] == 'running': report['status'] = 'failed'
        signal.signal(signal.SIGTERM, previous); write()


if __name__ == '__main__': main()
