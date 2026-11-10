"""Closed World constructors from captured image handles and typed intent.

Production-owned. Full hidden state comes from the fresh AOV shader reader;
the base guard keeps that full signature separate from auxiliary tap topology.
"""
import bpy
from schemaxis.errors import fail
from .settings import matching


NAMES = {'background': 'SXWorldBackground', 'output': 'SXWorldOutput', 'environment': 'SXWorldEnvironment'}


def build(specs, images, shader_budget):
    worlds = {};created = []
    try:
        # Predict exact root allocations before constructing nodes. The final
        # aggregate is rebuilt because Material and World share the same limit.
        from .shader_budget import admit
        roots = {key: list(value) for key, value in shader_budget.roots.items()}
        for index, spec in enumerate(specs):
            roots['newWorld:' + str(index)] = [None] * (3 if spec['lighting']['kind'] == 'environment' else 2)
        admit(roots, shader_budget.groups, 'production.worlds')
        for spec in specs:
            world = bpy.data.worlds.new(spec['id']);created.append(world);world.use_nodes = True;world.use_fake_user=True
            worlds[spec['id']] = world;tree = world.node_tree;tree.nodes.clear()
            background = tree.nodes.new('ShaderNodeBackground');background.name = NAMES['background']
            output = tree.nodes.new('ShaderNodeOutputWorld');output.name = NAMES['output']
            output.target = 'ALL';output.is_active_output = True
            tree.links.new(background.outputs['Background'], output.inputs['Surface'])
            lighting = spec['lighting'];background.inputs['Strength'].default_value = lighting['strength']
            if lighting['kind'] == 'environment':
                image = images.get(lighting['image'])
                if not isinstance(image, bpy.types.Image):
                    fail('UNKNOWN_REFERENCE', 'World environment needs its captured native image handle', spec['id'])
                environment = tree.nodes.new('ShaderNodeTexEnvironment');environment.name = NAMES['environment']
                environment.image = image
                environment.projection = {'equirectangular': 'EQUIRECTANGULAR', 'mirrorBall': 'MIRROR_BALL'}[lighting['projection']]
                environment.interpolation = {'nearest': 'Closest', 'linear': 'Linear', 'cubic': 'Cubic'}[lighting['interpolation']]
                # Rotate the environment's implicit World direction. No Object,
                # camera, generated-geometry or untyped mapping dependency.
                environment.texture_mapping.rotation = lighting['rotation']
                tree.links.new(environment.outputs['Color'], background.inputs['Color'])
            else:background.inputs['Color'].default_value = [*lighting['colour'], 1]
            for key, value in spec['visibility'].items():setattr(world.cycles_visibility, key, value)
            world.cycles.sampling_method = spec['sampling'].upper()
            world.cycles.sample_map_resolution = spec['samplingResolution']
            mist = spec['mist'];world.mist_settings.use_mist = mist['kind'] != 'none'
            if mist['kind'] != 'none':
                world.mist_settings.start = mist['start'];world.mist_settings.depth = mist['depth']
                world.mist_settings.height = mist['height']
                world.mist_settings.falloff = {'linear': 'LINEAR', 'quadratic': 'QUADRATIC', 'inverseQuadratic': 'INVERSE_QUADRATIC'}[mist['falloff']]
            verify_base(world, spec, images)
        return worlds, shader_budget.rebuilt(owners=worlds.values())
    except BaseException:
        for world in reversed(created):bpy.data.worlds.remove(world, do_unlink=True)
        raise


def verify_base(world, spec, images, *, auxiliary_nodes=0, auxiliary_links=0):
    """Exact immutable base; caller must separately verify every auxiliary edge."""
    if not isinstance(world, bpy.types.World) or not world.use_nodes or world.library is not None:
        fail('VERIFICATION_FAILED', 'World resource class or local shader ownership differs', spec['id'])
    tree = world.node_tree;lighting = spec['lighting'];environment = lighting['kind'] == 'environment'
    background = tree.nodes.get(NAMES['background']);output = tree.nodes.get(NAMES['output'])
    if (world.animation_data or tree.animation_data or background is None or output is None
            or background.bl_idname != 'ShaderNodeBackground' or output.bl_idname != 'ShaderNodeOutputWorld'
            or background.mute or output.mute or output.target != 'ALL' or not output.is_active_output
            or len(tree.nodes) != 2 + environment + auxiliary_nodes
            or len(tree.links) != 1 + environment + auxiliary_links):
        fail('VERIFICATION_FAILED', 'World resource base shader topology differs', spec['id'])
    expected = {(background, 'Background', output, 'Surface')}
    if not matching(background.inputs['Strength'].default_value, lighting['strength']):
        fail('VERIFICATION_FAILED', 'World background strength differs', spec['id'])
    if environment:
        texture = tree.nodes.get(NAMES['environment'])
        if (texture is None or texture.bl_idname != 'ShaderNodeTexEnvironment' or texture.mute
                or texture.image != images.get(lighting['image'])
                or texture.projection != {'equirectangular': 'EQUIRECTANGULAR', 'mirrorBall': 'MIRROR_BALL'}[lighting['projection']]
                or texture.interpolation != {'nearest': 'Closest', 'linear': 'Linear', 'cubic': 'Cubic'}[lighting['interpolation']]
                or not matching(list(texture.texture_mapping.rotation), lighting['rotation'])):
            fail('VERIFICATION_FAILED', 'World environment interpretation or actual image pointer differs', spec['id'])
        expected.add((texture, 'Color', background, 'Color'))
    elif not matching(list(background.inputs['Color'].default_value), [*lighting['colour'], 1]):
        fail('VERIFICATION_FAILED', 'World constant colour differs', spec['id'])
    base = {background, output} | ({texture} if environment else set())
    incident = [link for link in tree.links if link.to_node in base]
    if (len(incident) != len(expected) or any(link.is_muted for link in incident)
            or {(link.from_node, link.from_socket.name, link.to_node, link.to_socket.name) for link in incident} != expected):
        fail('VERIFICATION_FAILED', 'World base inputs gained an undeclared source', spec['id'])
    if any(getattr(world.cycles_visibility, key) != value for key, value in spec['visibility'].items()):
        fail('VERIFICATION_FAILED', 'World ray visibility differs', spec['id'])
    if world.cycles.sampling_method != spec['sampling'].upper() or world.cycles.sample_map_resolution != spec['samplingResolution']:
        fail('VERIFICATION_FAILED', 'World sampling policy differs', spec['id'])
    mist = spec['mist']
    if world.mist_settings.use_mist != (mist['kind'] != 'none'):
        fail('VERIFICATION_FAILED', 'World mist participation differs', spec['id'])
    if mist['kind'] != 'none':
        if (not matching([world.mist_settings.start, world.mist_settings.depth, world.mist_settings.height],
                         [mist['start'], mist['depth'], mist['height']])
                or world.mist_settings.falloff != {'linear': 'LINEAR', 'quadratic': 'QUADRATIC', 'inverseQuadratic': 'INVERSE_QUADRATIC'}[mist['falloff']]):
            fail('VERIFICATION_FAILED', 'World mist distance policy differs', spec['id'])
