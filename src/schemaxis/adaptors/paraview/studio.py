# Copyright (C) 2026 David L F Gaden
"""ParaView-owned insertion targets for scene and publication controls."""


def inspection_document(document, node):
    """Prune unfinished downstream stages; retain actual upstream dependencies."""
    import copy
    from schemaxis.documents import resolve_document
    from schemaxis.pipeline import DefinitionGraph, input_reference, markers
    from schemaxis.errors import fail
    from .filters import catalogue as declarations
    result = copy.deepcopy(document)
    nodes = result.get('nodes')
    if not isinstance(nodes, list):
        fail('INVALID_DOCUMENT', 'Add an input to the pipeline first', '$.nodes')
    available = {}
    for item in nodes:
        if isinstance(item, dict) and isinstance(item.get('id'), str):
            if item['id'] in available:
                fail('DUPLICATE_NODE', 'Node names must be unique before inspection', item['id'])
            available[item['id']] = item
    required, resolved_nodes = set(), {}
    def resolve_at(value, pointer):
        def selected_only(item, path, visit):
            if path == '': return True, visit(value, pointer)
            return False, None
        return resolve_document(document, marker_resolver=selected_only)[0]

    def include(identity):
        if identity in required: return
        if identity not in available:
            fail('UNKNOWN_REFERENCE', 'Choose an existing input node', 'node', node=identity)
        required.add(identity)
        raw = available[identity]
        index = next(i for i, item in enumerate(nodes) if item is raw)
        item = resolve_at(raw, '/nodes/' + str(index))
        declaration = declarations().get(item.get('filter'), {})
        options = item.get('options', {})
        if isinstance(options, dict):
            item['options'] = {key: value for key, value in options.items() if not (
                key in declaration.get('options', {}) and not declaration['options'][key]['value'].get('required')
                and any('$fill' in marker for marker in markers(value)))}
        resolved_nodes[identity] = item
        for value in item.get('inputs', {}).values():
            for source in value if isinstance(value, list) else [value]:
                include(input_reference(source, identity + '.inputs'))
        for value in markers(item.get('options', {})):
            for key in ('$observe', '$sample'):
                if key in value: include(value[key])
    include(node)
    result = {'version': document.get('version'), 'nodes': [resolved_nodes[item['id']] for item in nodes
              if isinstance(item, dict) and item.get('id') in required], 'scenes': []}
    for key in ('axes', 'times', 'maxStates'):
        if key in document: result[key] = resolve_at(document[key], '/' + key)
    master = DefinitionGraph(result, declarations())
    selection = master.select([node])
    if selection.count != 1 or len(selection.order) > 200:
        fail('INSPECTION_LIMIT', 'Select one time/parameter state and at most 200 upstream nodes for interactive inspection')
    if any(master.declarations[master.nodes[key]['filter']].get('nativeDependencies') for key in selection.order):
        fail('UNSUPPORTED_INSPECTION', 'Interactive inspection does not load native plugins')
    return result


def inspect_input(document, node, executable, directory, *, port=0, prepare=False, geometry=False):
    from .live import LiveSession
    prepared = inspection_document(document, node)
    with LiveSession(executable, directory, timeout=120) as session:
        if prepare:
            return session.request('prepare-input', document=prepared, node=node)
        for index, item in enumerate(prepared['nodes']):
            if item['filter'] == 'foam':
                reader = session.request('prepare-input', document=prepared, node=item['id'])
                prepared['nodes'][index] = reader['value']
                if 'times' not in prepared and reader.get('times'): prepared['times'] = reader['times']
        return session.request('inspect', document=prepared, node=node, port=port, geometry=geometry)


def catalogue(schema):
    for node in schema['properties']['nodes']['items']['oneOf']:
        if node['properties']['filter']['const'] == 'foam':
            node['x-studio-prepare'] = ('Add the reader without loading data. Load names reads case headers only; Live data preview opens just this reader and its upstream dependencies. '
                                      'Choose explicit names, all available names, or a deferred regular expression for regions and arrays.')
            options = schema['$defs']['options-foam']['properties']
            for key in ('regions', 'cellArrays'):
                options[key]['x-studio-control'] = {'kind': 'reader-selection', 'field': key}
    scene = schema['properties']['scenes']['items']['properties']
    items = []
    targets = [{'name': 'scene', 'collection': '/scenes', 'label': 'Target scene'}]
    for key, spec in scene.items():
        if key in ('id', 'exports', 'images', 'visible'):
            continue
        items.append({'id': 'scene:' + key, 'title': 'Scene ' + key, 'group': 'presentation',
                      'description': 'Configure ' + key + ' for a selected scene.',
                      'at': '/scenes/{scene}/' + key, 'targets': targets, 'schema': spec})
    image = scene['images']['items']
    items.append({'id': 'scene:image', 'title': 'Image', 'group': 'outputs',
                  'description': 'Add an image publication with camera and size settings.',
                  'at': '/scenes/{scene}/images/-', 'targets': targets, 'schema': image})
    items.append({'id': 'scene:camera', 'title': 'Camera', 'group': 'presentation',
                  'description': 'Add a camera to an existing image publication.',
                  'at': '/scenes/{scene}/images/{image}/cameras/-',
                  'targets': targets + [{'name': 'image', 'collection': '/scenes/{scene}/images', 'label': 'Target image'}],
                  'schema': image['properties']['cameras']['items']})
    items.append({'id': 'scene:appearance', 'title': 'Appearance', 'group': 'presentation',
                  'description': 'Set representation, colour, opacity, lighting, textures and scalar bars for a node.',
                  'at': '/scenes/{scene}/visible/{node}',
                  'targets': targets + [{'name': 'node', 'collection': '/nodes', 'label': 'Visible node', 'identity': True}],
                  'schema': scene['visible']['additionalProperties']})
    return items


def peek_input(document, node):
    """Best-effort names from bounded OpenFOAM headers, never native loading."""
    import gzip
    import re
    from pathlib import Path
    from schemaxis.documents import resolve_document
    from schemaxis.errors import fail
    target = next((item for item in document.get('nodes', []) if item.get('id') == node), None)
    if not target or target.get('filter') != 'foam':
        fail('UNSUPPORTED_INSPECTION', 'Metadata preview is available for OpenFOAM readers; use live data for this node', node)
    # Resolve only this node, with the document retained as reference context.
    def only(value, path, visit):
        if path == '': return True, visit(target, '/nodes/' + str(document['nodes'].index(target)))
        return False, None
    target, _ = resolve_document(document, marker_resolver=only)
    filename = target.get('options', {}).get('file')
    if not isinstance(filename, str):
        fail('UNAVAILABLE_METADATA', 'Choose a case marker path before previewing metadata', node)
    case = Path(filename).expanduser().resolve().parent
    if not case.is_dir(): fail('RESOURCE_NOT_FOUND', 'The case folder does not exist', filename)
    def header(path):
        if not path.exists(): path = Path(str(path) + '.gz')
        if not path.exists(): return ''
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', errors='replace') as stream: return stream.read(65536)
    processors = sorted(path for path in case.glob('processor*') if path.is_dir() and re.fullmatch(r'processors?\d+(?:_\d+-\d+)?', path.name))
    data = processors[0] if processors else case
    text = header(data / 'constant/polyMesh/boundary')
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    regions = ['internalMesh'] if text else []
    regions += ['patch/' + name.strip('"') for name in re.findall(r'(?:^|[}\n])\s*("[^"\n]+"|[A-Za-z_][\w.:-]*)\s*\{[^{}]*?\bnFaces\b', text)]
    times = []
    for path in data.iterdir():
        if path.is_dir():
            try:
                value = float(path.name)
                if value == value and abs(value) != float('inf'): times.append((value, path))
            except ValueError: pass
    times.sort(key=lambda pair: pair[0])
    if target.get('options', {}).get('skipZero'): times = [pair for pair in times if pair[0] != 0]
    arrays = []
    if times:
        for path in sorted(times[-1][1].iterdir()):
            if path.is_file() and re.search(r'\bclass\s+vol\w*Field\s*;', header(path)):
                arrays.append(path.name.removesuffix('.gz'))
    if not regions and not arrays:
        fail('UNAVAILABLE_METADATA', 'No readable standard OpenFOAM headers were found. Use live data for binary or multi-region layouts.', node)
    return {'node': node, 'regions': regions, 'cellArrays': sorted(set(arrays)), 'availableTimes': [pair[0] for pair in times],
            'scope': 'Case header preview only; no mesh loaded. Names may be incomplete for binary, collated or multi-region cases.',
            'caseType': 'Decomposed Case' if processors else 'Reconstructed Case'}
