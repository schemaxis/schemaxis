"""Native layer ownership for the closed, normalized render-bundle contract.

Captured collection-instance internals are not LayerCollection occurrences.
Selecting one requires the separately reviewed projection variant; never emulate
per-layer isolation by mutating a shared source Collection's global visibility.
"""
import bpy
from schemaxis.errors import fail
from .render_bundles import PASSES


MAX_OCCURRENCES = 16384
MAX_DEPTH = 128


def _tree(layer):
    result = []
    def visit(item, path=(), depth=0):
        if depth > MAX_DEPTH or len(result) >= MAX_OCCURRENCES:
            fail('RESOURCE_BUDGET_EXCEEDED', 'render layer collection occurrences exceed their bound', layer.name)
        result.append((path, item))
        for child in item.children:
            visit(child, (*path, child.collection.name), depth + 1)
    visit(layer.layer_collection)
    return result


def _target(selector, objects, collections, projections):
    if selector['kind'] == 'collection':
        collection = collections.get(selector['collection'])
        if collection is None:
            fail('UNKNOWN_REFERENCE', 'render collection is absent', selector['collection'])
        return collection
    root = objects.get(selector['asset'])
    if root is None:
        fail('UNKNOWN_REFERENCE', 'render asset carrier is absent', selector['asset'])
    if selector.get('path'):
        target=projections.get((selector['asset'],tuple(selector['path'])))
        if target is not None:return target['collection']
        fail('UNSUPPORTED_RENDER_PROJECTION',
             'nested captured collection masks require an explicit trusted layer projection',
             selector['asset'], path=selector['path'], requiredVariant='captured per-part layer projection')
    owners = list(root.users_collection)
    if len(owners) != 1:
        fail('AMBIGUOUS_RENDER_COLLECTION', 'asset needs one owned carrier collection', selector['asset'])
    return owners[0]


def _rules(layer, rules, objects, collections, projections=None):
    projections=projections or {}
    tree = _tree(layer)
    resolved = []
    for rule in rules:
        collection = _target(rule['target'], objects, collections,projections)
        matches = [(path, item) for path, item in tree if item.collection == collection]
        selector=rule['target']
        if selector['kind']=='asset' and selector.get('path'):
            target=projections[(selector['asset'],tuple(selector['path']))]
            matches=[(path,item) for path,item in matches if path[-len(target['suffix']):]==target['suffix']]
        if len(matches) != 1:
            fail('AMBIGUOUS_RENDER_COLLECTION',
                 'render mask needs exactly one reachable collection occurrence',
                 layer.name, collection=collection.name, occurrences=len(matches))
        path, item = matches[0]
        if any(other == path for other, _, _ in resolved):
            fail('INVALID_RENDER_MEMBERSHIP', 'render policies resolve to the same collection occurrence', layer.name)
        resolved.append((path, item, rule['mode']))
    for path, item, mode in resolved:
        for ancestor, _, parent_mode in resolved:
            if (len(ancestor) < len(path) and path[:len(ancestor)] == ancestor
                    and parent_mode != 'include' and mode not in ('exclude', parent_mode)):
                fail('INVALID_RENDER_MEMBERSHIP',
                     'a descendant cannot undo an ancestor exclusion or mask',
                     layer.name, ancestor=list(ancestor), descendant=list(path))
    return tree, resolved


def _pass_properties(layer):
    return [p.identifier for p in layer.bl_rna.properties
            if p.identifier.startswith('use_pass_') and p.type == 'BOOLEAN' and not p.is_readonly]


def collection_flags(tree, rules):
    """Expected native flags, including Blender's recursive exclude setter.

    Holdout and indirect-only belong to their own occurrence. Exclusion also
    sets every descendant's raw flag; its inherited value is not an undeclared
    policy and must not be mistaken for a submitted edit.
    """
    modes = {path: mode for path, _, mode in rules}
    excluded = [path for path, _, mode in rules if mode == 'exclude']
    return [(item, any(path[:len(parent)] == parent for parent in excluded),
             modes.get(path) == 'holdout', modes.get(path) == 'indirectOnly')
            for path, item in tree]


def apply_collection_rules(tree, rules):
    # The exclude setter recursively clears as well as sets descendants.
    # Apply ancestors before descendants, independent of declaration order.
    for _, item in tree:
        item.exclude = item.holdout = item.indirect_only = False
    for _, item, mode in sorted(rules, key=lambda rule: (len(rule[0]), rule[0])):
        item.exclude = mode == 'exclude'
        item.holdout = mode == 'holdout'
        item.indirect_only = mode == 'indirectOnly'


def _configure(layer, spec, materials, worlds):
    for key in _pass_properties(layer):
        setattr(layer, key, False)
    layer.use = spec['enabled']
    layer.samples = spec['samples']
    layer.pass_alpha_threshold = spec['alphaThreshold']
    layer.material_override = materials[spec['materialOverride']] if spec['materialOverride'] else None
    layer.world_override = worlds[spec['worldOverride']] if spec['worldOverride'] else None
    for key in spec['passes']:
        owner, attribute, _, _, _ = PASSES[key]
        target = layer if owner == 'layer' else getattr(layer, owner)
        setattr(target, attribute, True)
    for kind in ('object', 'material', 'asset'):
        setattr(layer, 'use_pass_cryptomatte_' + kind, spec['cryptomatte'][kind])
    layer.use_pass_cryptomatte_accurate = spec['cryptomatte']['accurate']
    layer.pass_cryptomatte_depth = spec['cryptomatte']['levels']
    layer.cycles.denoising_store_passes = spec['denoisingData']


def build(spec, objects, collections, materials, worlds=None,projections=None):
    state = {}
    try:
        return _build(spec, objects, collections, materials, worlds, state,projections)
    except Exception:
        if state:
            restore(state)
        raise


def _build(spec, objects, collections, materials, worlds, state,projections):
    """Create exact layers; return reversible ownership for production visits."""
    if not spec.get('viewLayers'):
        return None
    scene = bpy.context.scene
    worlds = worlds or {}
    if len(scene.view_layers) != 1:
        fail('UNSUPPORTED_RENDER_LAYER_SOURCE',
             'fresh production layer construction requires its single base layer')
    first = scene.view_layers[0]
    if len(first.aovs) or len(first.lightgroups):
        fail('UNSUPPORTED_RENDER_LAYER_SOURCE', 'base layer already has undeclared AOV or lightgroup ownership')
    keys = [*_pass_properties(first), 'use', 'samples', 'pass_alpha_threshold',
            'use_pass_cryptomatte_accurate', 'pass_cryptomatte_depth']
    previous = {key: getattr(first, key) for key in keys}
    state.update({'first': first, 'firstName': first.name, 'settings': previous,
             'material': first.material_override, 'world': first.world_override,
             'denoisingData': first.cycles.denoising_store_passes,
             'created': [], 'trees': [], 'lightgroups': [], 'worldLightgroups': []})
    aovs = {a['id']: a for a in spec['renderAovs']}
    for index, authored in enumerate(spec['viewLayers']):
        layer = first if index == 0 else scene.view_layers.new(authored['id'])
        if index:
            state['created'].append(layer)
        else:
            layer.name = authored['id']
        _configure(layer, authored, materials, worlds)
        tree, rules = _rules(layer, authored['collections'], objects, collections,projections)
        if index == 0:
            state['trees'] = [(item, item.exclude, item.holdout, item.indirect_only) for _, item in tree]
        apply_collection_rules(tree, rules)
        for identity in authored['aovs']:
            aov = layer.aovs.add()
            aov.name = identity
            aov.type = 'COLOR' if aovs[identity]['type'] == 'colour' else 'VALUE'
            if not aov.is_valid:
                fail('INVALID_RENDER_AOV', 'AOV conflicts with a native pass', identity)
        for identity in authored['lightgroups']:
            layer.lightgroups.add(name=identity)
        layer.update_render_passes()
    for group in spec['renderLightgroups']:
        for name in group['lights']:
            light = objects[name]
            if light.type != 'LIGHT':
                fail('TYPE_MISMATCH', 'lightgroup target is not a Light', name)
            state['lightgroups'].append((light, light.lightgroup))
            light.lightgroup = group['id']
        if group['world']:
            targets = set(worlds.values()) | ({scene.world} if scene.world else set())
            for world in targets:
                state['worldLightgroups'].append((world, world.lightgroup))
                world.lightgroup = group['id']
    return state


def observe(spec, objects, collections, materials, worlds=None,projections=None):
    """Read current native identities and controls, never a submitted witness."""
    if not spec.get('viewLayers'):
        return []
    scene, worlds = bpy.context.scene, worlds or {}
    if [layer.name for layer in scene.view_layers] != [layer['id'] for layer in spec['viewLayers']]:
        fail('VERIFICATION_FAILED', 'native render layer membership or order differs')
    records = []
    for authored in spec['viewLayers']:
        layer = scene.view_layers[authored['id']]
        if (layer.material_override != materials.get(authored['materialOverride'])
                or layer.world_override != worlds.get(authored['worldOverride'])):
            fail('VERIFICATION_FAILED', 'render layer override pointer differs', layer.name)
        tree, rules = _rules(layer, authored['collections'], objects, collections,projections)
        for item, exclude, holdout, indirect in collection_flags(tree, rules):
            if (item.exclude, item.holdout, item.indirect_only) != (
                    exclude, holdout, indirect):
                fail('VERIFICATION_FAILED', 'render collection occurrence policy differs', layer.name)
        records.append({'id': layer.name, 'enabled': layer.use, 'samples': layer.samples,
                        'alphaThreshold': layer.pass_alpha_threshold,
                        'materialOverride': layer.material_override.name if layer.material_override else None,
                        'worldOverride': layer.world_override.name if layer.world_override else None,
                        'passes': {key: getattr(layer, key) for key in _pass_properties(layer)},
                        'aovs': [{'id': a.name, 'type': a.type, 'valid': a.is_valid} for a in layer.aovs],
                        'lightgroups': [g.name for g in layer.lightgroups],
                        'worldLightgroups': [{'world': world.name, 'group': world.lightgroup}
                                             for world in sorted(set(worlds.values()) | ({scene.world} if scene.world else set()), key=lambda world: world.name)],
                        'cryptomatteLevels': layer.pass_cryptomatte_depth,
                        'denoisingData': layer.cycles.denoising_store_passes,
                        'collections': [{'path': list(path), 'collection': item.collection.name,
                                         'exclude': item.exclude, 'holdout': item.holdout,
                                         'indirectOnly': item.indirect_only} for path, item in tree]})
    return records


def restore(state):
    if state is None:
        return
    scene = bpy.context.scene
    first = state['first']
    if bpy.context.window is not None:
        bpy.context.window.view_layer = first
    for layer in reversed(state['created']):
        scene.view_layers.remove(layer)
    for item in list(first.aovs):
        first.aovs.remove(item)
    for item in list(first.lightgroups):
        first.lightgroups.remove(item)
    first.name = state['firstName']
    for key, value in state['settings'].items():
        setattr(first, key, value)
    first.material_override, first.world_override = state['material'], state['world']
    first.cycles.denoising_store_passes = state['denoisingData']
    for item, exclude, holdout, indirect in state['trees']:
        item.exclude, item.holdout, item.indirect_only = exclude, holdout, indirect
    for light, value in state['lightgroups']:
        light.lightgroup = value
    for world, value in state['worldLightgroups']:
        world.lightgroup = value
