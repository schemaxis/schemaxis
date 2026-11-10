#!/usr/bin/env python3
"""Independent analytic frame-exchange qualification; run within bounded_run."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def native(workspace, reopen=False):
    import math
    import bpy
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
    from schemaxis.adaptors.blender.production_output_native import publish_outputs, readback_outputs
    from schemaxis.adaptors.blender.production_outputs import validate_outputs, verify_outputs
    workspace = Path(workspace).resolve()
    if reopen:
        bpy.ops.wm.open_mainfile(filepath=str(workspace/'source.blend'), use_scripts=False)
        report = json.loads((workspace/'native.json').read_text())
        assert readback_outputs(report['records']) == [r['after'] for r in report['records']]
        assert bpy.context.scene.frame_current == 2
        assert math.isclose(bpy.data.objects['Cube'].scale.x, 2)
        (workspace/'reopened.json').write_text(json.dumps({'verified': True, 'outputs': len(report['records'])}))
        return
    scene, cube = bpy.context.scene, bpy.data.objects['Cube']
    cube.scale = (2, 3, .5)
    cube.rotation_euler[2] = math.pi/6
    cube.location = (0, 0, 0)
    cube.keyframe_insert('location', frame=1)
    cube.location = (4, 0, 0)
    cube.keyframe_insert('location', frame=3)
    scene.frame_set(2)
    scene.render.engine = 'CYCLES'
    scene.cycles.device, scene.cycles.samples = 'CPU', 2
    scene.render.resolution_x = scene.render.resolution_y = 32
    scene.render.resolution_percentage = 100
    production = {'frameStart': 1, 'frameEnd': 3, 'currentFrame': 2,
        'exports': [{'id': f'{format}{frame}', 'format': format, 'objects': ['cube'], 'frame': frame}
                    for frame in (1, 3) for format in ('obj', 'ply', 'stl', 'glb', 'usd')],
        'renderFrames': [1, 3]}
    production.update(validate_outputs(production, {'cube'}))
    prior = {obj.as_pointer() for obj in bpy.data.objects}
    records = publish_outputs(scene, {'cube': cube}, production, workspace, 'visit')
    assert scene.frame_current == 2
    assert prior == {obj.as_pointer() for obj in bpy.data.objects}, 'publication leaked scene objects'
    verify_outputs(records, production, workspace, 'visit')
    for record in records:
        if record['format'] == 'png':
            assert record['after']['size'] == [32, 32]
            continue
        # Literal rectangular-solid oracle; the Z rotation changes neither area
        # nor volume, and the two authored frames have independent known centres.
        for measured in ('before', 'after'):
            actual = record[measured]
            assert math.isclose(actual['area'], 68, rel_tol=2e-5)
            assert math.isclose(actual['signedVolume'], 24, rel_tol=2e-5)
            assert math.isclose(actual['surfaceCentre'][0], 0 if record['frame'] == 1 else 4, abs_tol=2e-6)
    # Unit variant: GLB/USD use physical metres; geometry-only formats retain
    # numerical source units explicitly, avoiding OBJ's fixed-decimal precision loss.
    unit_production = {**production, 'units': 'millimetres', 'renderFrames': []}
    unit_records = publish_outputs(scene, {'cube': cube}, unit_production, workspace, 'millimetres')
    verify_outputs(unit_records, unit_production, workspace, 'millimetres')
    for record in unit_records:
        factor = .001 if record['format'] in ('glb', 'usd') else 1.0
        assert math.isclose(record['after']['area'], 68*factor**2, rel_tol=2e-5)
        assert math.isclose(record['after']['signedVolume'], 24*factor**3, rel_tol=2e-5)
    records.extend(unit_records)
    report = {'verified': True, 'nativeVersion': bpy.app.version_string, 'production': production,
              'records': records, 'independentOracle': '4x6x1 cuboid, area68, volume24, centreX0/4'}
    (workspace/'native.json').write_text(json.dumps(report, indent=2)+'\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(workspace/'source.blend'), check_existing=False)


def main():
    argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', type=Path)
    parser.add_argument('--output-directory', type=Path)
    parser.add_argument('--native-workspace', type=Path)
    parser.add_argument('--reopen-workspace', type=Path)
    args = parser.parse_args(argv)
    if args.native_workspace or args.reopen_workspace:
        native(args.native_workspace or args.reopen_workspace, bool(args.reopen_workspace))
        return
    if not args.blender or not args.output_directory:
        parser.error('--blender and --output-directory are required')
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = [str(args.blender.resolve()), '--background', '--factory-startup', '--disable-autoexec',
               '--python-exit-code', '1', '--python', str(Path(__file__).resolve()), '--']
    for label, flag in [('build', '--native-workspace'), ('reopen', '--reopen-workspace')]:
        run = subprocess.run([*command, flag, str(output)], capture_output=True, text=True, timeout=240)
        (output/f'{label}.log').write_text(run.stdout+run.stderr)
        if run.returncode:
            raise RuntimeError(f'{label} native worker failed; inspect {output/label}')
    report = json.loads((output/'native.json').read_text())
    summary = {'verified': True, 'nativeVersion': report['nativeVersion'], 'outputs': len(report['records']),
               'freshReopen': json.loads((output/'reopened.json').read_text())['verified']}
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
