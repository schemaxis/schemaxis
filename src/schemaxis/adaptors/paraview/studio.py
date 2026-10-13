"""ParaView-owned insertion targets for scene and publication controls."""


def inspection_document(document, node):
    """Prune unfinished downstream stages; retain actual upstream dependencies."""
    import copy
    from schemaxis.documents import resolve_document
    from schemaxis.pipeline import DefinitionGraph, input_reference, markers
    from schemaxis.errors import fail
    from .filters import catalogue as declarations
    result, _ = resolve_document(copy.deepcopy(document))
    nodes = result.get('nodes')
    if not isinstance(nodes, list):
        fail('INVALID_DOCUMENT', 'Add an input to the pipeline first', '$.nodes')
    available = {}
    for item in nodes:
        if isinstance(item, dict) and isinstance(item.get('id'), str):
            if item['id'] in available:
                fail('DUPLICATE_NODE', 'Node names must be unique before inspection', item['id'])
            available[item['id']] = item
    required = set()

    def include(identity):
        if identity in required:
            return
        if identity not in available:
            fail('UNKNOWN_REFERENCE', 'Choose an existing input node', 'node', node=identity)
        required.add(identity)
        item = available[identity]
        for value in item.get('inputs', {}).values():
            for source in value if isinstance(value, list) else [value]:
                include(input_reference(source, identity + '.inputs'))
        for value in markers(item.get('options', {})):
            for key in ('$observe', '$sample'):
                if key in value:
                    include(value[key])
    include(node)
    result['nodes'] = [item for item in nodes if isinstance(item, dict) and item.get('id') in required]
    result['scenes'] = []
    master = DefinitionGraph(result, declarations())
    selection = master.select([node])
    if selection.count != 1 or len(selection.order) > 200:
        fail('INSPECTION_LIMIT', 'Select one time/parameter state and at most 200 upstream nodes for interactive inspection')
    if any(master.declarations[master.nodes[key]['filter']].get('nativeDependencies') for key in selection.order):
        fail('UNSUPPORTED_INSPECTION', 'Interactive inspection does not load native plugins')
    return result


def inspect_input(document, node, executable, directory, *, port=0, prepare=False):
    from .live import LiveSession
    prepared = inspection_document(document, node)
    with LiveSession(executable, directory, timeout=120) as session:
        if prepare:
            return session.request('prepare-input', document=prepared, node=node)
        return session.request('inspect', document=prepared, node=node, port=port)


def catalogue(schema):
    for node in schema['properties']['nodes']['items']['oneOf']:
        if node['properties']['filter']['const'] == 'foam':
            node['x-studio-prepare'] = ('When added, Studio detects the case layout and loads all available mesh regions unless you choose regions explicitly. '
                                      'A pipeline without an explicit time uses the first available reader time. Reader settings remain editable.')
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
