# Copyright (C) 2026 David L F Gaden
"""Native Blender binding. Imported only inside the selected Blender process."""
import hashlib
import json
import math
import time as clock
from pathlib import Path
import bpy
from mathutils import Vector, Matrix
from schemaxis.adaptors.blender.adaptor import plan
from schemaxis.pipeline import RuntimeClosure, evaluate
from schemaxis.camera import camera_values
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from schemaxis.adaptors.blender.operations import PRIMITIVES, MODIFIERS


MATERIAL_SOCKETS = {'roughness': 'Roughness', 'metallic': 'Metallic', 'ior': 'IOR',
                    'transmission': 'Transmission Weight', 'coat': 'Coat Weight',
                    'coatRoughness': 'Coat Roughness', 'emissionStrength': 'Emission Strength'}


class Backend:
    def __init__(self, sources=None):
        self.records = {}
        self.sources = sources or {}

    def create(self, node, declaration, inputs, constructor):
        kind = declaration['id']
        if kind in ('readSTL','readPLY'):
            from .extended_native import import_mesh
            obj=import_mesh(node,kind,constructor,self.sources)
        elif kind == 'readGltf':
            path = Path(self.sources.get(node, {}).get('retained', constructor['file']))
            if not path.is_file():
                fail('RESOURCE_NOT_FOUND', 'glTF source file is absent', str(path))
            document = json.loads(path.read_text())
            if document.get('asset', {}).get('version') != '2.0' or len(document.get('meshes', [])) != 1:
                fail('UNSUPPORTED_RESOURCE', 'initial glTF reader requires one mesh in a glTF 2.0 JSON file', str(path))
            for resource in [*document.get('buffers', []), *document.get('images', [])]:
                if 'uri' in resource and not resource['uri'].startswith('data:'):
                    fail('UNSUPPORTED_RESOURCE', 'initial glTF reader requires embedded resources', str(path))
            before = set(bpy.data.objects)
            outcome = bpy.ops.import_scene.gltf(filepath=str(path))
            imported = set(bpy.data.objects) - before
            meshes = [item for item in imported if item.type == 'MESH']
            if outcome != {'FINISHED'} or len(meshes) != 1:
                for item in imported:
                    bpy.data.objects.remove(item, do_unlink=True)
                fail('UNSUPPORTED_RESOURCE', 'glTF must instantiate exactly one mesh object', str(path))
            obj = meshes[0]
            matrix = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = matrix
            for item in imported - {obj}:
                bpy.data.objects.remove(item, do_unlink=True)
            obj.name = node
            obj['schemaxisSourceSha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif kind == 'material':
            obj = bpy.data.materials.new(node)
            obj.use_nodes = True
        else:
            mesh = bpy.data.meshes.new(node + '-mesh')
            if kind == 'cube':
                mesh.from_pydata([(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),
                                  (1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)], [],
                                 [tuple(reversed(face)) for face in
                                  [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]])
                mesh.materials.append(inputs['material'])
            obj = bpy.data.objects.new(node, mesh)
            bpy.context.scene.collection.objects.link(obj)
            if kind == 'bevel':
                modifier = obj.modifiers.new('schemaxis-bevel', 'BEVEL')
                modifier.affect = 'EDGES'
            if kind in MODIFIERS:
                modifier = obj.modifiers.new('schemaxis-operation', MODIFIERS[kind][0])
                if kind in ('twist','bend'):
                    modifier.deform_method=kind.upper()
                if kind == 'voxelRemesh':
                    modifier.mode='VOXEL'
                if kind == 'shrinkwrap':
                    modifier.target=inputs['target']
                if kind == 'boolean':
                    modifier.object = inputs['operand']
                    modifier.solver = 'EXACT'
            if kind in PRIMITIVES:
                mesh.materials.append(inputs['material'])
        if kind == 'curveFromCSV':
            source = self.sources.get(node, {}).get('retained', constructor['file'])
            from schemaxis.artifacts import file_digest
            obj['schemaxisSourceSha256'] = file_digest(source)
        self.records[obj.as_pointer()] = {'kind': kind, 'inputs': inputs, 'options': {}}
        if kind == 'curveFromCSV':self.records[obj.as_pointer()]['source'] = source
        return obj

    def configure(self, obj, declaration, changes):
        record = self.records[obj.as_pointer()]
        record['options'].update(changes)
        kind = record['kind']
        for key, value in changes.items():
            if kind in ('readSTL','readPLY','shadeSmooth','voxelRemesh') or kind in PRIMITIVES and key != 'centre' or kind == 'transform':
                continue  # Geometry and transforms are applied at the update boundary.
            if kind in MODIFIERS:
                modifier = obj.modifiers['schemaxis-operation']
                native_key = MODIFIERS[kind][1][key][0]
                setattr(modifier, native_key, value)
                if kind == 'subdivision' and key == 'levels':
                    modifier.render_levels = value
                from schemaxis.adaptors.blender.settings import matching
                actual = getattr(modifier, native_key)
                if isinstance(value, list): actual = list(actual)
                if not matching(actual, value):
                    fail('NATIVE_VALUE_MISMATCH', 'modifier did not retain requested property', key)
                continue
            if kind == 'material' and (key in MATERIAL_SOCKETS or key == 'emissionColour'):
                from .settings import matching
                shader = obj.node_tree.nodes['Principled BSDF']
                prop = 'Emission Color' if key == 'emissionColour' else MATERIAL_SOCKETS[key]
                expected = [*value, 1] if key == 'emissionColour' else value
                shader.inputs[prop].default_value = expected
                actual = shader.inputs[prop].default_value
                if key == 'emissionColour': actual = list(actual)
                if not matching(actual, expected):
                    fail('NATIVE_VALUE_MISMATCH', 'material did not retain requested property', key)
                continue
            if key == 'file':
                continue  # Constructor-only; source digest is retained on the native object.
            if key == 'colour':
                obj.diffuse_color = value
                shader = obj.node_tree.nodes['Principled BSDF']
                shader.inputs['Base Color'].default_value = value
                shader.inputs['Alpha'].default_value = value[3]
                actual = list(obj.diffuse_color)
            elif key == 'size':
                obj.scale = [value / 2] * 3
                actual = obj.scale.x * 2
            elif key == 'centre':
                obj.location = value
                actual = list(obj.location)
            elif key in ('width', 'segments'):
                setattr(obj.modifiers['schemaxis-bevel'], key, value)
                actual = getattr(obj.modifiers['schemaxis-bevel'], key)
            else:
                fail('UNKNOWN_ARGUMENT', 'Blender property is not bound', key)
            left = actual if isinstance(actual, list) else [actual]
            right = value if isinstance(value, list) else [value]
            if any(abs(a-b) > 1e-6 * max(1,abs(b)) for a,b in zip(left,right)):
                fail('NATIVE_VALUE_MISMATCH', 'Blender did not retain property', key)

    def update(self, obj, time):
        record = self.records[obj.as_pointer()]
        if record['kind'] in PRIMITIVES:
            from schemaxis.adaptors.blender.meshes import populate
            options = record['options']
            if record['kind'] == 'curveFromCSV':options = {**options, 'file': record['source']}
            populate(obj.data, record['kind'], options)
        if record['kind']=='join':
            from .extended_native import join_meshes
            join_meshes(obj,record['inputs']['inputs'])
        if record['kind'] in {'bevel', 'transform', 'assignMaterial', 'shadeSmooth', 'applyTransform', *MODIFIERS}:
            source = record['inputs']['input']
            graph = bpy.context.evaluated_depsgraph_get()
            evaluated = source.evaluated_get(graph)
            mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=graph)
            old = obj.data
            obj.data = mesh
            obj.matrix_world = source.matrix_world.copy()
            if record['kind'] == 'transform':
                from schemaxis.adaptors.blender.meshes import transform
                obj.matrix_world = transform(record['options']) @ source.matrix_world
            if record['kind']=='applyTransform':
                mesh.transform(source.matrix_world)
                obj.matrix_world=Matrix.Identity(4)
            if record['kind'] == 'assignMaterial':
                mesh.materials.clear()
                mesh.materials.append(record['inputs']['material'])
                for face in mesh.polygons:
                    face.material_index = 0
            if record['kind']=='shadeSmooth':
                for face in mesh.polygons:face.use_smooth=record['options']['enabled']
            if record['kind']=='voxelRemesh':
                from .extended_native import check_voxel_budget
                check_voxel_budget(mesh,record['options']['voxelSize'])
                from .settings import matching
                modifier=obj.modifiers['schemaxis-operation']
                for key,(prop,_) in MODIFIERS['voxelRemesh'][1].items():
                    setattr(modifier,prop,record['options'][key])
                    if not matching(getattr(modifier,prop),record['options'][key]):
                        fail('NATIVE_VALUE_MISMATCH','remesher setting differs',key)
            if old.users == 0:
                bpy.data.meshes.remove(old)
        bpy.context.view_layer.update()

    def observe(self, obj):
        if isinstance(obj, bpy.types.Material):
            return {'kind': 'material', 'colour': list(obj.diffuse_color),
                    'shaderColour': list(obj.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value),
                    'shaderAlpha': obj.node_tree.nodes['Principled BSDF'].inputs['Alpha'].default_value,
                    'roughness': obj.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value,
                    'metallic': obj.node_tree.nodes['Principled BSDF'].inputs['Metallic'].default_value,
                    'ior': obj.node_tree.nodes['Principled BSDF'].inputs['IOR'].default_value,
                    **{key: obj.node_tree.nodes['Principled BSDF'].inputs[prop].default_value
                       for key, prop in MATERIAL_SOCKETS.items()},
                    'emissionColour': list(obj.node_tree.nodes['Principled BSDF'].inputs['Emission Color'].default_value)[:3]}
        graph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            points = [list(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices]
            bounds = [f(p[i] for p in points) for i in range(3) for f in (min, max)] if points else [0]*6
            volume = 0.0
            for face in mesh.polygons:
                vertices = [Vector(points[i]) for i in face.vertices]
                for i in range(1, len(vertices)-1):
                    volume += vertices[0].dot(vertices[i].cross(vertices[i+1])) / 6
            return {'kind': 'mesh', 'signedVolume': volume, 'points': len(points), 'cells': len(mesh.polygons), 'bounds': bounds,
                    'transform': [list(row) for row in evaluated.matrix_world],
                    'geometrySha256': hashlib.sha256(json.dumps({'points': points,
                        'faces': [list(p.vertices) for p in mesh.polygons]}, sort_keys=True).encode()).hexdigest()}
        finally:
            evaluated.to_mesh_clear()

    def delete(self, obj):
        self.records.pop(obj.as_pointer(), None)
        if isinstance(obj, bpy.types.Material):
            bpy.data.materials.remove(obj)
        else:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            materials = list(mesh.materials)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            for material in materials:
                if material and material.users == 0 and material.as_pointer() not in self.records:
                    bpy.data.materials.remove(material)


def shading_snapshot(obj):
    graph=bpy.context.evaluated_depsgraph_get()
    evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh()
    try:
        return hashlib.sha256(json.dumps({'smooth':[p.use_smooth for p in mesh.polygons],
            'normals':[list(n.vector) for n in mesh.corner_normals]},sort_keys=True).encode()).hexdigest()
    finally:evaluated.to_mesh_clear()


def snapshot(names):
    backend = Backend()
    result = {}
    for name in names:
        if name in bpy.data.objects:
            obj = bpy.data.objects[name]
            result[name] = {**backend.observe(obj), 'matrix': [list(row) for row in obj.matrix_world],
                            'materials': [m.name if m else None for m in obj.data.materials],
                            'hidden': obj.hide_render, 'shading': shading_snapshot(obj)}
        elif name in bpy.data.materials:
            result[name] = backend.observe(bpy.data.materials[name])
        else:
            fail('VERIFICATION_FAILED', 'saved object is absent', name)
    camera = bpy.context.scene.camera
    result['camera'] = {'matrix': [list(row) for row in camera.matrix_world],
                        'type': camera.data.type, 'scale': camera.data.ortho_scale, 'clipStart':camera.data.clip_start, 'clipEnd':camera.data.clip_end}
    result['render'] = render_observation()
    return result


def frame(camera, settings, bounds, size):
    bounds = settings.get('bounds', bounds)
    centre = Vector(settings.get('focalPoint', [(bounds[i]+bounds[i+1])/2 for i in (0,2,4)]))
    diagonal = math.hypot(*(bounds[i+1]-bounds[i] for i in (0,2,4)))
    direction = Vector(settings['direction']).normalized()
    camera.location = centre + direction * settings.get('distance', diagonal*2)
    forward = -direction
    right = forward.cross(Vector(settings['up'])).normalized()
    up = right.cross(forward).normalized()
    rotation = Matrix((right, up, -forward)).transposed()
    camera.rotation_euler = rotation.to_euler()
    camera.data.type = 'ORTHO' if settings['parallel'] else 'PERSP'
    camera.data.sensor_fit = 'HORIZONTAL'
    camera.data.ortho_scale = settings.get('scale', diagonal * (1+settings['padding']) * max(1, size[0]/size[1]))
    from .settings import clipping
    camera.data.clip_start,camera.data.clip_end=clipping(diagonal,settings.get('distance',diagonal*2))
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    bpy.context.view_layer.update()
    actual_forward = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    actual_up = camera.matrix_world.to_quaternion() @ Vector((0, 1, 0))
    if (actual_forward - forward).length > 1e-5 or (actual_up - up).length > 1e-5:
        fail('VERIFICATION_FAILED', 'native camera orientation differs')
    if settings['parallel'] and 'scale' not in settings and 'focalPoint' not in settings:
        from bpy_extras.object_utils import world_to_camera_view
        from itertools import product
        for corner in product(*[(bounds[i], bounds[i+1]) for i in (0, 2, 4)]):
            projected = world_to_camera_view(scene, camera, Vector(corner))
            if not camera.data.clip_start <= projected.z <= camera.data.clip_end:
                fail('VERIFICATION_FAILED','automatic camera depth clipping crops requested bounds')
            if not (-1e-5 <= projected.x <= 1+1e-5 and -1e-5 <= projected.y <= 1+1e-5):
                fail('VERIFICATION_FAILED', 'automatic camera framing crops requested bounds')
    return {'position': list(camera.location), 'forward': list(actual_forward), 'up': list(actual_up),
            'focalPoint': list(centre),
            'viewAngle': math.degrees(2*math.atan(max(abs(v.y/v.z) for v in camera.data.view_frame(scene=scene)))) if camera.data.type != 'ORTHO' else 0,
            'projectionScaleY': camera.data.ortho_scale/2*size[1]/size[0],
            'parallel': camera.data.type == 'ORTHO', 'scale': camera.data.ortho_scale, 'clipStart':camera.data.clip_start,'clipEnd':camera.data.clip_end}


def execute(directory):
    directory = Path(directory)
    master, selection, prepared = plan(json.loads((directory / 'input.json').read_text()))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    settings = prepared['renderSettings']
    devices = configure_render(scene, settings)
    camera = bpy.data.objects.new('__schemaxis_camera', bpy.data.cameras.new('__schemaxis_camera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    sources=json.loads((directory/'sources.json').read_text()) if (directory/'sources.json').exists() else {}
    backend = Backend(sources)
    active = RuntimeClosure(master, backend)
    active.activate(selection.roots)
    spec = master.document['scenes'][0]
    writer = spec['images'][0]
    scene['schemaxisNodes'] = json.dumps(selection.order)
    scene['schemaxisVisible'] = json.dumps(spec['visible'])
    receipt = {'status': 'incomplete', 'receiptVersion': 3, 'framingVersion': 3, 'planDigest': master.to_dict()['digest'], 'states': [], 'artifacts': []}
    receipt.update(renderSettings=settings, devices=devices, sourceCaptureVersion=1)
    def artifact(path):
        receipt['artifacts'].append({'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    try:
        for index, visit in enumerate(selection.visits()):
            started = clock.monotonic()
            state = active.apply(visit)
            state['timings'] = {'applySeconds': clock.monotonic()-started, 'renderSeconds': 0}
            state['objectIds'] = {name: str(obj.as_pointer()) for name, obj in active.handles.items()}
            for name, obj in active.handles.items():
                if isinstance(obj, bpy.types.Object):
                    obj.hide_render = name not in spec['visible']
            data = [state['observations'][name]['bounds'] for name in spec['visible']]
            bounds = [min(b[i] for b in data) if i%2 == 0 else max(b[i] for b in data) for i in range(6)]
            for ci, authored in enumerate(writer['cameras']):
                settings = camera_values(evaluate(authored, visit['axes'], state['observations'], visit['time'], 'camera'), 'camera')
                actual_camera = frame(camera, settings, bounds, writer['size'])
                if spec.get('prepareOnly'):
                    continue
                path = directory / f'{index:04d}-{ci:03d}.png'
                scene.render.filepath = str(path)
                started = clock.monotonic()
                bpy.ops.render.render(write_still=True)
                state['timings']['renderSeconds'] += clock.monotonic()-started
                image = bpy.data.images.load(str(path), check_existing=False)
                try:
                    if list(image.size) != writer['size'] or len(set(list(image.pixels)[::4])) < 2:
                        fail('VERIFICATION_FAILED', 'render is empty or has wrong dimensions', str(path))
                finally:
                    bpy.data.images.remove(image)
                artifact(path)
                receipt['artifacts'][-1].update(camera=actual_camera, effectiveCamera=settings, state=index, cameraIndex=ci, kind='image', units='Blender units')
            from .export_native import publish
            for mesh_node in spec.get('meshes',[]):
                exported=publish(active.handles[mesh_node],directory/f'{index:04d}-{mesh_node}.stl')
                receipt['artifacts'].append({**exported,'state':index,'node':mesh_node,
                    'data': state['observations'][mesh_node],
                    'spatial': {'state': 'known', 'frame': 'native-world', 'units': 'Blender units',
                                'bounds': state['observations'][mesh_node]['bounds'],
                                'boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax'],
                                'transformConvention': {'storage':'row-major nested rows',
                                    'vector':'homogeneous column', 'composition':'world = sourceObjectTransform @ local',
                                    'translationUnits':'Blender units', 'application':'already baked into exported vertices'},
                                'sourceObjectTransform': state['observations'][mesh_node]['transform'],
                                'coordinateRepresentation': 'world coordinates baked into STL'}})
            path = directory / f'{index:04d}.blend'
            started = clock.monotonic()
            bpy.ops.wm.save_as_mainfile(filepath=str(path))
            state['timings']['saveSeconds'] = clock.monotonic()-started
            artifact(path)
            receipt['artifacts'][-1].update(state=index, kind='scene',
                spatial={'state': 'known', 'frame': 'native-world', 'units': 'Blender units',
                         'bounds': bounds, 'boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax'],
                         'transformConvention': {'storage':'row-major nested rows','vector':'homogeneous column',
                            'composition':'world = objectTransform @ local','translationUnits':'Blender units'},
                         'objectTransforms': {name: state['observations'][name].get('transform') for name in spec['visible']}})
            state['snapshot'] = snapshot(selection.order)
            state['blend'] = str(path)
            receipt['states'].append(state)
            atomic_json(directory / 'verification.json', receipt)
        active.close()
        receipt.update(status='succeeded', events=active.events)
        atomic_json(directory / 'verification.json', receipt)
    finally:
        if not active.closed:
            active.close()


def reopen(directory):
    directory = Path(directory)
    receipt = json.loads((directory / 'verification.json').read_text())
    states = []
    for state in receipt['states']:
        bpy.ops.wm.open_mainfile(filepath=state['blend'])
        states.append(snapshot(list(state['effective'])))
    from .export_native import readback
    meshes=[readback(Path(a['file'])) for a in receipt['artifacts'] if a.get('kind')=='geometry']
    atomic_json(directory / 'reopened.json', {'states': states,'meshes':meshes})


def configure_render(scene, settings):
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU' if settings['device'] == 'CPU' else 'GPU'
    devices = []
    if settings['device'] != 'CPU':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        try:
            prefs.compute_device_type = settings['device']
            prefs.get_devices()
        except (TypeError, RuntimeError) as error:
            fail('DEVICE_UNAVAILABLE', 'requested Cycles backend is unavailable', device=settings['device'], reason=str(error))
        for device in prefs.devices:
            device.use = device.type == settings['device']
            if device.use:
                devices.append({'name': device.name, 'type': device.type})
        if not devices:
            fail('DEVICE_UNAVAILABLE', 'no device supports requested Cycles backend', device=settings['device'])
    scene['schemaxisDevice'] = settings['device']
    scene.cycles.samples = settings['samples']
    scene.cycles.use_denoising = settings['denoise']
    scene.cycles.seed = settings['seed']
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = settings['threads']
    scene.render.film_transparent = settings['transparent']
    scene.render.image_settings.file_format = 'PNG'
    world = bpy.data.worlds.new('__schemaxis_world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = [*settings['worldColour'], 1]
    world.node_tree.nodes['Background'].inputs[1].default_value = settings['worldStrength']
    scene.world = world
    light = bpy.data.lights.new('__schemaxis_light', 'AREA')
    light.energy = settings['lightEnergy']
    light.size = settings['lightSize']
    lamp = bpy.data.objects.new('__schemaxis_light', light)
    scene.collection.objects.link(lamp)
    lamp.location = settings['lightPosition']
    lamp.rotation_euler = (-lamp.location).to_track_quat('-Z','Y').to_euler()
    return devices


def render_observation():
    scene = bpy.context.scene
    lamp = bpy.data.objects['__schemaxis_light']
    expected_device = 'CPU' if scene.get('schemaxisDevice', 'CPU') == 'CPU' else 'GPU'
    if scene.render.engine != 'CYCLES' or scene.cycles.device != expected_device:
        fail('VERIFICATION_FAILED', 'native render engine/device changed')
    background = scene.world.node_tree.nodes['Background']
    # GPU backend is retained explicitly because Blender preferences are not saved
    # in .blend files; the selected physical devices are separately in the receipt.
    return {'device': scene.get('schemaxisDevice', 'CPU'), 'samples': scene.cycles.samples,
            'threads': scene.render.threads, 'denoise': scene.cycles.use_denoising,
            'transparent': scene.render.film_transparent, 'seed': scene.cycles.seed,
            'worldColour': list(background.inputs[0].default_value)[:3],
            'worldStrength': background.inputs[1].default_value,
            'lightEnergy': lamp.data.energy, 'lightPosition': list(lamp.location), 'lightSize': lamp.data.size}
