# Copyright (C) 2026 David L F Gaden
"""Native saved-scene rendering, imported only inside Blender."""
import hashlib
import json
import time as clock
from pathlib import Path
import bpy
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .native import snapshot, configure_render, render_observation, frame


def execute(directory):
    directory = Path(directory)
    prepared = json.loads((directory/'plan.json').read_text())
    started = clock.monotonic()
    bpy.ops.wm.open_mainfile(filepath=str(directory/'source.blend'), use_scripts=False)
    load_seconds = clock.monotonic()-started
    if bpy.data.libraries or any(image.source == 'FILE' and not image.packed_file for image in bpy.data.images):
        fail('UNSUPPORTED_RESOURCE', 'saved-scene rendering requires self-contained scenes with packed images')
    scene = bpy.context.scene
    names = json.loads(scene.get('schemaxisNodes', '[]'))
    visible = json.loads(scene.get('schemaxisVisible', '[]'))
    if not names or not visible or scene.camera is None:
        fail('UNSUPPORTED_RESOURCE', 'render input must be a saved Schemaxis scene with geometry metadata')
    def geometry():
        state = snapshot(names,include_render=False)
        state.pop('camera')
        # Production roots and collection instances need the same evaluated
        # geometry used by neutral exports; they need not be DAG node names.
        from .production_output_native import geometry_snapshot
        roots=[]
        for name in visible:
            obj=bpy.data.objects.get(name)
            if obj is None:fail('VERIFICATION_FAILED','visible saved-scene root is absent',name)
            roots.append(obj)
        state['visibleGeometry']=geometry_snapshot(roots)
        return state
    before = geometry()
    bounds = before['visibleGeometry']['bounds']
    # Replace the known Schemaxis lighting, avoiding duplicate lamps on a reopened scene.
    lamp = bpy.data.objects.get('__schemaxis_light')
    if lamp:
        data = lamp.data
        bpy.data.objects.remove(lamp, do_unlink=True)
        if data.users == 0:
            bpy.data.lights.remove(data)
    devices = configure_render(scene, prepared['render'])
    receipt = {'status': 'incomplete', 'framingVersion':3, 'sourceSha256': hashlib.sha256((directory/'source.blend').read_bytes()).hexdigest(),
               'loadSeconds': load_seconds, 'renderSeconds': 0, 'before': before, 'bounds': bounds, 'devices': devices, 'artifacts': []}
    for index, camera in enumerate(prepared['cameras']):
        actual = frame(scene.camera, camera, bounds, prepared['size'])
        path = directory/f'{index:04d}.png'
        scene.render.filepath = str(path)
        started = clock.monotonic()
        from .render_writers_native import suppress
        with suppress(scene):
            bpy.ops.render.render(write_still=True)
        receipt['renderSeconds'] += clock.monotonic()-started
        from .production_outputs import image_snapshot
        if image_snapshot(path)['size'] != prepared['size']:
            fail('VERIFICATION_FAILED', 'render has wrong dimensions', str(path))
        receipt['artifacts'].append({'file': str(path), 'kind': 'image', 'units': 'Blender units', 'cameraIndex': index,
            'camera': actual, 'size': prepared['size'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        atomic_json(directory/'verification.json', receipt)
    receipt.update(status='succeeded', after=geometry(), render=render_observation())
    atomic_json(directory/'verification.json', receipt)
