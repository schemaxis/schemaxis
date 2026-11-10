"""Deterministic file/channel layout compiled from closed render-bundle intent.

All native socket identifiers below come from reviewed descriptors. Authored
input selects logical passes and ports, never native socket strings or paths.
"""
import re

from schemaxis.errors import fail
from .render_bundles import PASSES, source_slots


KINDS = {'number': ('FLOAT', 1), 'integer': ('FLOAT', 1),
         'vector': ('VECTOR', 3), 'vector2': ('VECTOR', 2),
         'vector4': ('VECTOR', 4), 'colour': ('RGBA', 4), 'image': ('RGBA', 4)}
DENOISING = {'noisy': ('Noisy Image', 'colour'), 'albedo': ('Denoising Albedo', 'colour'),
             'specularAlbedo': ('Denoising Specular Albedo', 'colour'),
             'normal': ('Denoising Normal', 'vector'),
             'roughness': ('Denoising Roughness', 'number'), 'depth': ('Denoising Depth', 'number')}
CRYPTO = {'object': 'CryptoObject', 'material': 'CryptoMaterial', 'asset': 'CryptoAsset'}


def slots(spec, identity, source):
    """Compile all coverage ranks, with canonical alias+00/01 channel names."""
    kind = source['kind']
    if kind == 'cryptomatte':
        # Native metadata extraction strips ALL trailing digits. End the group
        # in letters so logical names such as part1 and part2 stay distinct.
        group = identity + '_matte'
        return [{'id': group + str(rank).zfill(2), 'socketType': 'RGBA', 'components': 4,
                 'source': {'kind': 'layer', 'layer': source['layer'],
                            'socket': CRYPTO[source['matte']] + str(rank).zfill(2)},
                 'scientific': True, 'identifiers': True, 'cryptoGroup': group}
                for rank in range(source_slots(spec, source))]
    if kind == 'compositor':
        from .node_groups import descriptor
        graph = spec['compositor']
        node = next(n for n in graph['nodes'] if n['id'] == source['node'])
        port = descriptor(node, 'compositor', {g['id']: g for g in spec.get('nodeGroups', [])})['outputs'][source['socket']]
        native_kind, components = KINDS[port['kind']]
        description = descriptor(node, 'compositor', {g['id']: g for g in spec.get('nodeGroups', [])})
        reference = {'kind': 'compositor', 'node': source['node'], 'type': description['native'], 'socket': port['native']}
        scientific = port['kind'] not in ('image', 'colour')
    else:
        if kind == 'pass':
            _, _, socket, component_kind, _ = PASSES[source['pass']]
            scientific = source['pass'] != 'combined'
        elif kind == 'aov':
            aov = next(a for a in spec['renderAovs'] if a['id'] == source['aov'])
            socket, component_kind, scientific = source['aov'], 'colour' if aov['type'] == 'colour' else 'number', True
        elif kind == 'lightgroup':
            socket, component_kind, scientific = 'Combined_' + source['lightgroup'], 'colour', True
        elif kind == 'denoising':
            socket, component_kind = DENOISING[source['pass']]
            scientific = source['pass'] != 'noisy'
        else:
            fail('INVALID_RENDER_BUNDLE', 'render source has no reviewed output layout', kind)
        native_kind, components = KINDS[component_kind]
        reference = {'kind': 'layer', 'layer': source['layer'], 'socket': socket}
    return [{'id': identity, 'socketType': native_kind, 'components': components,
             'source': reference, 'scientific': scientific,
             'identifiers': kind == 'pass' and source['pass'] in ('objectIndex', 'materialIndex')}]


def definitions(spec, prefix='0000'):
    """File stems are generated; no user-selected destination is accepted."""
    if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', prefix):
        fail('INVALID_RENDER_BUNDLE', 'publication prefix must be a bounded filename component')
    result = []
    for bundle in spec['renderBundles']:
        for output in bundle['outputs']:
            items = output['layers'] if output['kind'] == 'multilayer' else [{'id': 'image', 'source': output['source']}]
            records = [slot for item in items for slot in slots(spec, item['id'], item['source'])]
            names = [record['id'] for record in records]
            if len(names) != len(set(names)):
                fail('OUTPUT_SLOT_COLLISION', 'logical output and matte rank names collide; choose distinct logical names', output['id'])
            if len(records) > 64 or sum(record['components'] for record in records) > 128:
                fail('RESOURCE_BUDGET_EXCEEDED', 'render output exceeds 64 native slots or 128 channels', output['id'])
            from .cryptomatte_output import layer_identifier
            groups = {record['cryptoGroup'] for record in records if 'cryptoGroup' in record}
            if len({layer_identifier(group) for group in groups}) != len(groups):
                fail('OUTPUT_SLOT_COLLISION', 'matte group metadata identifiers collide; choose distinct logical names', output['id'])
            encoding = output['encoding'] if output['kind'] == 'image' else {
                'kind': 'exr', 'precision': output['precision'], 'compression': output['compression']}
            png = output['kind'] == 'image' and encoding['kind'] == 'png'
            if png and any(record['identifiers'] for record in records):
                fail('INVALID_RENDER_BUNDLE', 'matte identifiers require FLOAT EXR components', output['id'])
            if not png and encoding['precision'] != 'float' and any(record['identifiers'] for record in records):
                fail('INVALID_RENDER_BUNDLE', 'matte identifiers require FLOAT EXR components', output['id'])
            for record in records:
                # PNG is an encoded display/preview publication. Scientific
                # plane identity is asserted only for raw EXR publications.
                record['scientific'] = record['scientific'] and not png
            result.append({'bundle': bundle['id'], 'output': output['id'],
                           'stem': prefix + '-bundle-' + bundle['id'] + '-' + output['id'],
                           'format': 'png' if png else 'exr', 'encoding': dict(encoding), 'slots': records})
    return result


def jobs(spec, prefix='0000'):
    files = definitions(spec, prefix)
    result = []
    for bundle in spec['renderBundles']:
        for frame in bundle['frames']:
            for definition in files:
                if definition['bundle'] != bundle['id']:
                    continue
                # Native IMAGE writers append the image item's name. Native
                # multilayer EXRs use a single container and omit that suffix.
                suffix = 'image.png' if definition['format'] == 'png' else '.exr'
                result.append({**definition, 'frame': frame,
                               'file': definition['stem'] + '-' + str(frame).zfill(4) + suffix})
    return result


def channels(definition):
    """Expected raw EXR planes, independently matched against decoded headers."""
    result = {}
    for slot in definition['slots']:
        # Native cryptomatte writer metadata selects lowercase channel suffixes;
        # ordinary colour outputs use uppercase RGBA at this fixed baseline.
        suffixes = tuple('rgba') if 'cryptoGroup' in slot else ('V',) if slot['socketType'] == 'FLOAT' else tuple('RGBA') if slot['socketType'] == 'RGBA' else tuple('XYZW'[:slot['components']])
        for suffix in suffixes:
            result[slot['id'] + '.' + suffix] = {'scientific': slot['scientific'], 'identifiers': slot['identifiers']}
    return result
