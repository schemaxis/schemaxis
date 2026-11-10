"""Reusable presentation tasks lowered to editable native scene controls."""
import json
import math

import bpy

from schemaxis.errors import fail
from .production_intents import verify_intents


def _curves(control):
    if not control.animation_data or not control.animation_data.action:
        fail('VERIFICATION_FAILED', 'presentation control has no action')
    if control.animation_data.drivers:
        fail('VERIFICATION_FAILED', 'presentation control may not contain undeclared drivers')
    if control.constraints or control.animation_data.nla_tracks or control.animation_data.action_blend_type != 'REPLACE' or control.animation_data.action_influence != 1:
        fail('VERIFICATION_FAILED', 'presentation control contains undeclared motion composition')
    result = []
    for layer in control.animation_data.action.layers:
        for strip in layer.strips:
            bag = strip.channelbag(control.animation_data.action_slot)
            if bag: result.extend(bag.fcurves)
    return sorted(result, key=lambda c: c.array_index)


def _geometry(objects):
    from .production_output_native import _resolved_geometry
    points = []
    for evaluated, world in _resolved_geometry(objects):
        mesh = evaluated.to_mesh()
        try:
            if len(points)+len(mesh.vertices) > 1_000_000:
                fail('RESOURCE_BUDGET_EXCEEDED', 'presentation framing exceeds one million vertices')
            points.extend(list(world @ v.co) for v in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    if not points:
        fail('INVALID_INTENT', 'turntable needs geometric objects or a root containing geometry')
    return [op(p[i] for p in points) for i in range(3) for op in (min, max)]


def _root_objects(selected):
    roots = []
    for obj in selected:
        ancestor = obj.parent
        while ancestor and ancestor not in selected:
            ancestor = ancestor.parent
        if ancestor is None:
            if obj.parent is not None:
                fail('INVALID_INTENT', 'select the existing hierarchy root; turntable cannot discard an external parent', obj.name)
            roots.append(obj)
    return roots


def apply_intents(spec, objects):
    created = []
    scene, frame, subframe = bpy.context.scene, bpy.context.scene.frame_current, bpy.context.scene.frame_subframe
    for intent in spec:
        name = 'SX_INTENT_'+intent['id']
        if bpy.data.objects.get(name):
            fail('INVALID_INTENT', 'generated presentation control name already exists', name)
        selected = [objects[n] for n in intent['objects']]
        roots = _root_objects(selected)
        if any((o.animation_data and o.animation_data.action) or o.constraints or o.rigid_body for o in roots):
            fail('INVALID_INTENT', 'turntable roots must not have competing motion; use an unanimated hierarchy root')
        scene.frame_set(intent['startFrame'])
        bpy.context.view_layer.update()
        bounds = _geometry(selected)
        pivot = [(bounds[i]+bounds[i+1])/2 for i in (0, 2, 4)] if intent['pivot'] == 'boundsCentre' else intent['pivot']
        control = bpy.data.objects.new(name, None)
        scene.collection.objects.link(control)
        created.append(control)
        control.location = pivot
        control.rotation_mode = 'XYZ'
        bpy.context.view_layer.update()
        before = {n: [list(row) for row in objects[n].matrix_world] for n in intent['objects'] if objects[n] in roots}
        control['schemaxisIntentBounds'] = json.dumps(bounds)
        control['schemaxisIntentBefore'] = json.dumps(before)
        for obj in roots:
            matrix = obj.matrix_world.copy()
            obj.parent = control
            obj.matrix_world = matrix
        for at, angle in [(intent['startFrame'], 0), (intent['endFrame'], math.radians(intent['angleDegrees']))]:
            control.rotation_euler = [angle if i == 'XYZ'.index(intent['axis']) else 0 for i in range(3)]
            control.keyframe_insert(data_path='rotation_euler', frame=at, group='Presentation')
        for curve in _curves(control):
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
        scene.frame_set(frame, subframe=subframe)
        bpy.context.view_layer.update()
    observed = observe_intents(spec, objects)
    verify_intents(spec, observed)
    return {'created': created, 'readback': observed}


def observe_intents(spec, objects):
    records, scene = [], bpy.context.scene
    frame, subframe = scene.frame_current, scene.frame_subframe
    try:
        for intent in spec:
            control = bpy.data.objects.get('SX_INTENT_'+intent['id'])
            if control is None or control.type != 'EMPTY':
                fail('VERIFICATION_FAILED', 'presentation control missing or wrong type', intent['id'])
            scene.frame_set(intent['startFrame'])
            bpy.context.view_layer.update()
            # Derive the baseline from current native geometry at the neutral
            # first frame; custom properties are not trusted verification evidence.
            selected = [objects[n] for n in intent['objects']]
            before = {n: [list(row) for row in objects[n].matrix_world]
                      for n in intent['objects'] if objects[n].parent == control}
            if not before:
                fail('VERIFICATION_FAILED', 'presentation has no selected controlled roots', intent['id'])
            records.append({'id': intent['id'], 'control': control.name, 'selected': intent['objects'],
                'parent': control.parent.name if control.parent else None, 'rotationMode': control.rotation_mode,
                'scale': list(control.scale), 'pivot': list(control.location),
                'beforeBounds': _geometry(selected),
                'roots': list(before), 'beforeWorld': before,
                'rootParents': {n: objects[n].parent.name if objects[n].parent else None for n in before},
                'curves': [{'index': c.array_index, 'path': c.data_path,
                    'muted': bool(c.mute), 'modifiers': len(c.modifiers), 'extrapolation': c.extrapolation,
                    'keys': [list(p.co) for p in c.keyframe_points],
                    'interpolation': [p.interpolation for p in c.keyframe_points]} for c in _curves(control)],
                'samples': []})
            for f in [intent['startFrame'], (intent['startFrame']+intent['endFrame'])/2, intent['endFrame']]:
                scene.frame_set(math.floor(f), subframe=f % 1)
                bpy.context.view_layer.update()
                records[-1]['samples'].append({'frame': f,
                    'world': {n: [list(row) for row in objects[n].matrix_world] for n in before}})
    finally:
        scene.frame_set(frame, subframe=subframe)
        bpy.context.view_layer.update()
    return records
