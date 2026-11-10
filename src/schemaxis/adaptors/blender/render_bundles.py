"""Closed view-layer/pass/publication intent, without importing native Blender.

Public production routes share this declaration with native construction,
fresh source authority and bounded publication verification.
"""
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from schemaxis.pipeline import name
from schemaxis.schema import arguments_schema
from .node_catalogue import boolean, choice, integer, number, text
from .spline import array as _array, record, settings, union, variant


ID = {'type': 'string', 'minLength': 1, 'maxLength': 48}
REFERENCE = {'type': 'string', 'minLength': 1, 'maxLength': 128}
ENGINES = ('cycles', 'eevee', 'workbench')


def array(item, maximum=4096, minimum=0):
    return {**_array(item, maximum, minimum), **({'default': []} if minimum == 0 else {})}


# Semantic key -> native layer owner/property, RLayers socket, component kind,
# engine availability. Exact socket names were observed at fixed 5.2.3 LTS.
# Socket availability is not a replacement for each variant's render oracle.
PASSES = {
    'combined': ('layer', 'use_pass_combined', 'Image', 'colour', ENGINES),
    'alpha': ('layer', 'use_pass_combined', 'Alpha', 'number', ENGINES),
    'depth': ('layer', 'use_pass_z', 'Depth', 'number', ENGINES),
    'mist': ('layer', 'use_pass_mist', 'Mist', 'number', ('cycles', 'eevee')),
    'position': ('layer', 'use_pass_position', 'Position', 'vector', ('cycles', 'eevee')),
    'normal': ('layer', 'use_pass_normal', 'Normal', 'vector', ('cycles', 'eevee')),
    'motion': ('layer', 'use_pass_vector', 'Vector', 'vector4', ('cycles', 'eevee')),
    'uv': ('layer', 'use_pass_uv', 'UV', 'vector', ('cycles',)),
    'objectIndex': ('layer', 'use_pass_object_index', 'Object Index', 'number', ('cycles',)),
    'materialIndex': ('layer', 'use_pass_material_index', 'Material Index', 'number', ('cycles',)),
    'emission': ('layer', 'use_pass_emit', 'Emission', 'colour', ('cycles', 'eevee')),
    'environment': ('layer', 'use_pass_environment', 'Environment', 'colour', ('cycles', 'eevee')),
    'ambientOcclusion': ('layer', 'use_pass_ambient_occlusion', 'Ambient Occlusion', 'colour', ('cycles', 'eevee')),
    'diffuseDirect': ('layer', 'use_pass_diffuse_direct', 'Diffuse Direct', 'colour', ('cycles', 'eevee')),
    'diffuseIndirect': ('layer', 'use_pass_diffuse_indirect', 'Diffuse Indirect', 'colour', ('cycles',)),
    'diffuseColour': ('layer', 'use_pass_diffuse_color', 'Diffuse Color', 'colour', ('cycles', 'eevee')),
    'specularDirect': ('layer', 'use_pass_glossy_direct', 'Glossy Direct', 'colour', ('cycles', 'eevee')),
    'specularIndirect': ('layer', 'use_pass_glossy_indirect', 'Glossy Indirect', 'colour', ('cycles',)),
    'specularColour': ('layer', 'use_pass_glossy_color', 'Glossy Color', 'colour', ('cycles', 'eevee')),
    'transmissionDirect': ('layer', 'use_pass_transmission_direct', 'Transmission Direct', 'colour', ('cycles',)),
    'transmissionIndirect': ('layer', 'use_pass_transmission_indirect', 'Transmission Indirect', 'colour', ('cycles',)),
    'transmissionColour': ('layer', 'use_pass_transmission_color', 'Transmission Color', 'colour', ('cycles',)),
    'shadow': ('layer', 'use_pass_shadow', 'Shadow', 'colour', ('eevee',)),
}
COMPONENTS = {'number': 1, 'vector': 3, 'vector4': 4, 'colour': 4}

COLLECTION = union([
    variant('collection', {'collection': {**REFERENCE, 'required': True}}),
    variant('asset', {'asset': {**REFERENCE, 'required': True},
                      'path': array(REFERENCE, 64)}),
])
RULE = record({'target': COLLECTION,
               'mode': choice('include', ['include', 'exclude', 'holdout', 'indirectOnly'])}, ['target'])
CRYPTO = settings({'object': boolean(), 'material': boolean(), 'asset': boolean(),
                 'levels': integer(6, minimum=2, maximum=16), 'accurate': boolean(True)})
LAYER = record({'id': ID, 'enabled': boolean(True), 'samples': integer(0, minimum=0, maximum=4096),
                'collections': array(RULE, 256), 'materialOverride': text(), 'worldOverride': text(),
                'passes': {**array({'type': 'enum', 'values': list(PASSES)}, 32, 1), 'default': ['combined']},
                'aovs': array(ID, 32), 'lightgroups': array(ID, 32), 'cryptomatte': CRYPTO,
                'alphaThreshold': number(.5, minimum=0, maximum=1), 'denoisingData': boolean()}, ['id'])
AOV = record({'id': ID, 'type': choice('colour', ['colour', 'value'])}, ['id'])
LIGHTGROUP = record({'id': ID, 'lights': array(REFERENCE, 4096), 'world': boolean()}, ['id'])
PASS_REFERENCE = union([
    variant('pass', {'layer': {**ID, 'required': True},
                     'pass': {**choice('combined', list(PASSES)), 'required': True}}),
    variant('aov', {'layer': {**ID, 'required': True}, 'aov': {**ID, 'required': True}}),
    variant('lightgroup', {'layer': {**ID, 'required': True}, 'lightgroup': {**ID, 'required': True}}),
    variant('cryptomatte', {'layer': {**ID, 'required': True},
                           'matte': choice('object', ['object', 'material', 'asset'])}),
    variant('denoising', {'layer': {**ID, 'required': True},
                          'pass': choice('noisy', ['noisy', 'albedo', 'specularAlbedo', 'normal', 'roughness', 'depth'])}),
])
SOURCE = union(PASS_REFERENCE['options'] + [
    variant('compositor', {'node': {**REFERENCE, 'required': True},
                           'socket': {**REFERENCE, 'required': True}}),
])
ENCODING = union([
    variant('png', {'depth': choice('8', ['8', '16']),
                    'channels': choice('rgba', ['rgb', 'rgba']),
                    'compression': integer(15, minimum=0, maximum=100)}),
    variant('exr', {'precision': choice('float', ['half', 'float']),
                    'compression': choice('zip', ['none', 'zips', 'zip'])}),
])
# Declaration defaults are detached, not recursively normalized when omitted.
# Compile the selected branch once so omitted encoding has the same complete
# intent as an explicit {kind: png}, without duplicating its field defaults.
ENCODING['default'] = validate_arguments({'encoding': ENCODING},
                                         {'encoding': {'kind': 'png'}})['encoding']
OUTPUT = union([
    variant('image', {'id': {**ID, 'required': True}, 'source': {**SOURCE, 'required': True}, 'encoding': ENCODING}),
    variant('multilayer', {'id': {**ID, 'required': True},
                           'layers': {**array(record({'id': ID, 'source': SOURCE}, ['id', 'source']), 64, 1), 'required': True},
                           'precision': choice('float', ['half', 'float']),
                           'compression': choice('zip', ['none', 'zips', 'zip'])}),
])
BUNDLE = record({'id': ID, 'frames': array({'type': 'integer', 'minimum': 0, 'maximum': 1000000}, 128),
                 'camera': text(), 'outputs': {**array(OUTPUT, 64, 1), 'required': True}}, ['id'])
OPTIONS = {'viewLayers': array(LAYER, 16), 'renderAovs': array(AOV, 32),
           'renderLightgroups': array(LIGHTGROUP, 32), 'renderBundles': array(BUNDLE, 16)}


def schema_properties():
    return arguments_schema(OPTIONS)['properties']


def _distinct(records, location):
    ids = [item['id'] for item in records]
    for identity in ids:
        name(identity, location + '.' + identity)
    if len(set(ids)) != len(ids):
        fail('DUPLICATE_ID', 'render identities must be distinct within their namespace', location)
    return {item['id']: item for item in records}


def _references(values, known, location):
    if len(set(values)) != len(values):
        fail('DUPLICATE_ID', 'render references must be distinct', location)
    if any(item not in known for item in values):
        fail('UNKNOWN_REFERENCE', 'render reference is absent', location)


def validate(value, *, kinds, materials, collections, assets, worlds=(), where='production'):
    """Normalize references without touching caller records or importing bpy."""
    result = validate_arguments(OPTIONS, {k: value[k] for k in OPTIONS if k in value}, location=where)
    for field in OPTIONS:
        result.setdefault(field, [])
    layers = _distinct(result['viewLayers'], where + '.viewLayers')
    aovs = _distinct(result['renderAovs'], where + '.renderAovs')
    groups = _distinct(result['renderLightgroups'], where + '.renderLightgroups')
    _distinct(result['renderBundles'], where + '.renderBundles')
    if result['renderBundles'] and not any(layer['enabled'] for layer in layers.values()):
        fail('INVALID_RENDER_BUNDLE', 'render bundles require an enabled explicit view layer', where + '.viewLayers')
    # Pass sockets and lightgroup sockets share the same native name namespace.
    reserved = {p[2] for p in PASSES.values()}
    reserved |= {'Noisy Image', 'Denoising Albedo', 'Denoising Normal', 'Denoising Depth',
                 'Denoising Specular Albedo', 'Denoising Roughness', 'Grease Pencil'}
    if set(aovs) & reserved or any(name.startswith(('CryptoObject', 'CryptoMaterial', 'CryptoAsset', 'Combined_')) for name in aovs):
        fail('INVALID_RENDER_BUNDLE', 'AOV identity conflicts with a native render pass', where + '.renderAovs')
    assigned = set()
    for group in groups.values():
        loc = where + '.renderLightgroups.' + group['id']
        _references(group['lights'], kinds, loc + '.lights')
        if any(kinds[ref] != 'light' for ref in group['lights']):
            fail('TYPE_MISMATCH', 'lightgroups require declared Light objects', loc)
        targets = set(group['lights']) | ({'__world__'} if group['world'] else set())
        if assigned & targets:
            fail('INVALID_RENDER_BUNDLE', 'a Light or World can belong to only one lightgroup', loc)
        assigned |= targets
    for layer in layers.values():
        loc = where + '.viewLayers.' + layer['id']
        _references(layer['passes'], PASSES, loc + '.passes')
        _references(layer['aovs'], aovs, loc + '.aovs')
        _references(layer['lightgroups'], groups, loc + '.lightgroups')
        if layer['materialOverride'] and layer['materialOverride'] not in materials:
            fail('UNKNOWN_REFERENCE', 'layer material override is absent', loc + '.materialOverride')
        if layer['worldOverride'] and layer['worldOverride'] not in worlds:
            fail('UNKNOWN_REFERENCE', 'layer world override is absent', loc + '.worldOverride')
        seen = set()
        for rule in layer['collections']:
            target = rule['target']
            if target['kind'] == 'collection':
                ref, known = target['collection'], collections
                key = ('collection', ref)
            else:
                ref, known = target['asset'], assets
                key = ('asset', ref, tuple(target.get('path', [])))
            if ref not in known:
                fail('UNKNOWN_REFERENCE', 'layer collection target is absent', loc + '.collections')
            if key in seen:
                fail('INVALID_RENDER_BUNDLE', 'declare one policy for each collection occurrence', loc + '.collections')
            seen.add(key)
        crypto = layer['cryptomatte']
        if crypto['levels'] % 2:
            fail('INVALID_RENDER_BUNDLE', 'Cryptomatte levels must be an even coverage count', loc + '.cryptomatte.levels')
    start, end, current = value.get('frameStart', 1), value.get('frameEnd', 250), value.get('currentFrame', value.get('frameStart', 1))
    if (any(type(v) is not int or not 0 <= v <= 1000000 for v in (start, end, current))
            or not start <= current <= end):
        fail('INVALID_TIMELINE', 'render bundle needs an ordered bounded timeline', where)
    for bundle in result['renderBundles']:
        loc = where + '.renderBundles.' + bundle['id']
        bundle['frames'] = bundle['frames'] or [current]
        _references(bundle['frames'], range(start, end + 1), loc + '.frames')
        if bundle['camera'] and kinds.get(bundle['camera']) != 'camera':
            fail('TYPE_MISMATCH', 'bundle camera requires a declared Camera', loc + '.camera')
        _distinct(bundle['outputs'], loc + '.outputs')
        for output in bundle['outputs']:
            sources = output['layers'] if output['kind'] == 'multilayer' else [{'source': output['source']}]
            if output['kind'] == 'multilayer':
                _distinct(output['layers'], loc + '.outputs.' + output['id'] + '.layers')
            for item in sources:
                source = item['source']
                if source['kind'] == 'compositor':
                    graph = value.get('compositor', {})
                    node = next((n for n in graph.get('nodes', []) if n.get('id') == source['node']), None)
                    if node is None:
                        fail('UNKNOWN_REFERENCE', 'compositor output node is absent', loc)
                    from .node_groups import descriptor
                    groups_by_id = {g['id']: g for g in value.get('nodeGroups', [])}
                    desc = descriptor(node, 'compositor', groups_by_id)
                    port = desc['outputs'].get(source['socket'])
                    if port is None or port['kind'] not in ('image', 'colour', 'number', 'integer', 'vector', 'vector2', 'vector4'):
                        fail('TYPE_MISMATCH', 'publication needs a reviewed image or data output port', loc)
                    continue
                layer = layers.get(source['layer'])
                if layer is None or not layer['enabled']:
                    fail('UNKNOWN_REFERENCE', 'output needs an enabled declared view layer', loc)
                if source['kind'] == 'pass' and source['pass'] not in layer['passes']:
                    fail('INVALID_RENDER_BUNDLE', 'output pass is not enabled on its layer', loc)
                if source['kind'] == 'aov' and source['aov'] not in layer['aovs']:
                    fail('INVALID_RENDER_BUNDLE', 'output AOV is not enabled on its layer', loc)
                if source['kind'] == 'lightgroup' and source['lightgroup'] not in layer['lightgroups']:
                    fail('INVALID_RENDER_BUNDLE', 'output lightgroup is not enabled on its layer', loc)
                if source['kind'] == 'cryptomatte' and not layer['cryptomatte'][source['matte']]:
                    fail('INVALID_RENDER_BUNDLE', 'output Cryptomatte coverage is not enabled', loc)
                if source['kind'] == 'denoising' and not layer['denoisingData']:
                    fail('INVALID_RENDER_BUNDLE', 'output denoising data is not enabled', loc)
    return result


def validate_engine(spec, engine, *, motion_blur=False, where='render'):
    if engine not in ENGINES:
        fail('INVALID_RENDERER', 'unknown render bundle engine', where)
    for layer in spec['viewLayers']:
        loc = where + '.viewLayers.' + layer['id']
        if any(engine not in PASSES[p][4] for p in layer['passes']):
            fail('UNSUPPORTED_RENDER_PASS', 'pass is unavailable on the selected engine', loc)
        if engine != 'cycles' and (layer['lightgroups'] or layer['denoisingData'] or any(r['mode'] in ('holdout', 'indirectOnly') for r in layer['collections'])):
            fail('UNSUPPORTED_RENDER_PASS', 'lightgroups, denoising and collection masks require the qualified Cycles contract', loc)
        if engine == 'workbench' and (layer['aovs'] or any(layer['cryptomatte'][k] for k in ('object', 'material', 'asset'))):
            fail('UNSUPPORTED_RENDER_PASS', 'Workbench does not provide AOV or Cryptomatte passes', loc)
        if engine == 'workbench' and (layer['samples'] or layer['materialOverride'] or layer['worldOverride'] or layer['alphaThreshold'] != .5):
            fail('INEFFECTIVE_RENDER_SETTING', 'layer sampling, overrides and alpha threshold are not Workbench controls', loc)
        if motion_blur and 'motion' in layer['passes']:
            fail('INEFFECTIVE_RENDER_SETTING', 'motion vector pass is disabled by native motion blur', loc)
    return spec


def source_components(spec, source):
    """Float buffers are charged conservatively for compositor port references."""
    kind = source['kind']
    if kind == 'pass':
        return COMPONENTS[PASSES[source['pass']][3]]
    if kind == 'aov':
        aov = next(a for a in spec['renderAovs'] if a['id'] == source['aov'])
        return 4 if aov['type'] == 'colour' else 1
    if kind == 'denoising':
        return 1 if source['pass'] in ('roughness', 'depth') else 3 if source['pass'] == 'normal' else 4
    if kind == 'cryptomatte':
        return 4 * source_slots(spec, source)
    return 4


def source_slots(spec, source):
    """One logical matte family preserves every enabled coverage-rank pair."""
    if source.get('kind') == 'cryptomatte':
        layer = next(layer for layer in spec['viewLayers'] if layer['id'] == source['layer'])
        return layer['cryptomatte']['levels'] // 2
    return 1


def budget(spec, size, where='renderBundles'):
    """Bound native float work buffers and all uncompressed publication bytes.

    Every enabled layer is charged for every requested frame, even when a graph
    could prune one. Unknown compositor dependencies never reduce the estimate.
    Limits are this finite profile's admission policy, not native renderer caps.
    """
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or any(type(v) is not int or not 1 <= v <= 2048 for v in size)):
        fail('INVALID_RENDER_BUNDLE', 'bundle dimensions must be bounded integers', where)
    pixels = size[0] * size[1]
    layer_components = 0
    for layer in spec['viewLayers']:
        if not layer['enabled']:
            continue
        components = 4 + sum(COMPONENTS[PASSES[p][3]] for p in layer['passes'])
        components += sum(4 if next(a for a in spec['renderAovs'] if a['id'] == ref)['type'] == 'colour' else 1 for ref in layer['aovs'])
        components += 4 * len(layer['lightgroups'])
        components += 4 * (layer['cryptomatte']['levels'] // 2) * sum(layer['cryptomatte'][k] for k in ('object', 'material', 'asset'))
        if layer['denoisingData']:
            components += 4 + 4 + 4 + 3 + 1 + 1
        layer_components += components
    working_peak, output_bytes, publications, layer_frames = 0, 0, 0, 0
    enabled = sum(layer['enabled'] for layer in spec['viewLayers'])
    for bundle in spec['renderBundles']:
        output_components = 0
        for output in bundle['outputs']:
            sources = [r['source'] for r in output['layers']] if output['kind'] == 'multilayer' else [output['source']]
            channels = sum(source_components(spec, source) for source in sources)
            if channels > 128:
                fail('RESOURCE_BUDGET_EXCEEDED', 'EXR output exceeds 128 channels', where + '.' + bundle['id'])
            encoding = output.get('encoding', output)
            is_png = output['kind'] == 'image' and encoding['kind'] == 'png'
            identifiers = any(s['kind'] == 'cryptomatte' or s['kind'] == 'pass'
                              and s['pass'] in ('objectIndex', 'materialIndex') for s in sources)
            if identifiers and (is_png or encoding['precision'] != 'float'):
                fail('INVALID_RENDER_BUNDLE', 'matte identifiers require FLOAT EXR components', where + '.' + bundle['id'])
            if is_png:
                channels = 4 if encoding['channels'] == 'rgba' else 3
                component_bytes = 1 if encoding['depth'] == '8' else 2
            else:
                component_bytes = 2 if encoding['precision'] == 'half' else 4
            file_bytes = pixels * channels * component_bytes
            if file_bytes > 256 * 1024**2:
                fail('RESOURCE_BUDGET_EXCEEDED', 'render output decoded planes exceed 256 MiB', where + '.' + bundle['id'])
            output_bytes += file_bytes * len(bundle['frames'])
            output_components += channels
        # Four float buffers per native component cover producer/compositor/
        # denoise intermediates, plus two buffers per publication component.
        working_peak = max(working_peak, pixels * 4 * (4 * layer_components + 2 * output_components))
        publications += len(bundle['outputs']) * len(bundle['frames'])
        layer_frames += enabled * len(bundle['frames'])
    observed = {'estimatedWorkingBytes': working_peak, 'uncompressedOutputBytes': output_bytes,
                'publications': publications, 'layerFrames': layer_frames}
    if working_peak > 512 * 1024**2 or output_bytes > 512 * 1024**2 or publications > 4096 or layer_frames > 2048:
        fail('RESOURCE_BUDGET_EXCEEDED', 'aggregate render bundle envelope is exceeded', where, **observed)
    return observed
