# Copyright (C) 2026 David L F Gaden
"""Host-only Add catalogue projected from adaptor declarations and literal schemas.

Unlike curated recipes these entries promise authoring coverage, not executable
fixtures: required data and native qualification are shown explicitly.
"""
import copy
from .adaptors import registry
from .schema import document_schema


def catalogue(provider, version=None):
    meta = registry.metadata(provider)
    version = version or meta['version']
    if version not in meta['routes']:
        from .errors import fail
        fail('UNKNOWN_VERSION', 'choose a registered adaptor route', 'version')
    route = meta['routes'][version]
    from .studio_guidance import enrich, load
    guidance = load(provider)
    schema = literal_schema(enrich(registry.binding(route['schema'])(), provider, version, guidance))
    definitions = schema.get('$defs', {})
    node_schema = schema.get('properties', {}).get('nodes', {}).get('items', {})
    nodes = node_schema.get('oneOf', [node_schema] if node_schema.get('properties', {}).get('filter', {}).get('const') else [])
    declarations = registry.declarations(provider)
    items = []
    from .capabilities import CapabilityCatalogue, operation_id
    discovery = CapabilityCatalogue([provider])
    context = discovery._metadata[provider]
    purposes = context.get('operations', {})
    for name, declaration in declarations.items():
        decorate_options(definitions.get('options-' + name, {}), declaration['options'])
    for node in nodes:
        name = node['properties']['filter']['const']
        declaration = declarations[name]
        if not declaration['inputs']:
            node['properties'].pop('inputs', None)
        if not declaration.get('commands'):
            node['properties'].pop('onVisit', None)
        files = any(binding.get('constructor') and ('vtkSMFileListDomain' in binding.get('nativeDomains', [])
                    or any(part in ('FileName', 'FileNames', 'Filename') for part in binding.get('path', [])))
                    for binding in declaration['options'].values())
        group = 'inputs' if files else 'filters' if declaration['inputs'] else 'sources'
        native = declaration.get('native', name)
        items.append({'id': 'operation:' + name, 'operation': name, 'title': name if native == name else name + ' · ' + native,
                      'group': group, 'schema': node, 'at': '/nodes/-',
                      'description': purposes.get(name, {}).get('purpose', declaration.get('summary', 'Add ' + declaration.get('native', name) + '.')),
                      'coverage': declaration.get('coverage', {}),
                      'ports': declaration['inputs'],
                      'commands': declaration.get('commands', {}),
                      'bindings': declaration['options']})
    scene = schema.get('properties', {}).get('scenes', {}).get('items', {})
    exports = scene.get('properties', {}).get('exports', {}).get('items', {}).get('oneOf', [])
    for writer in exports:
        name = writer['properties']['writer']['const']
        declaration = declarations[name]
        writer['properties']['node']['x-studio-reference'] = {'kind': 'data', 'multiple': False}
        items.append({'id': 'operation:' + name, 'operation': name, 'title': name,
                      'group': 'outputs', 'schema': writer, 'at': '/scenes/{scene}/exports/-',
                      'targets': [{'name': 'scene', 'collection': '/scenes', 'label': 'Target scene'}],
                      'description': 'Publish with ' + declaration.get('native', name) + '.',
                      'coverage': declaration.get('coverage', {}), 'ports': declaration['inputs'],
                      'bindings': declaration['options']})
    for key, specification in schema.get('properties', {}).items():
        if key in ('version', 'nodes'):
            continue
        is_array = specification.get('type') == 'array'
        items.append({'id': 'document:' + key, 'title': 'Scene' if key == 'scenes' else key,
                      'group': 'presentation', 'description': 'Configure document ' + key + '.',
                      'at': '/' + key + ('/-' if is_array and key in ('scenes', 'axes') else ''),
                      'schema': specification['items'] if is_array and key in ('scenes', 'axes') else specification})
    # A document's declared operation selector chooses analysis without creating
    # a graph node. Project only choices actually present in this route schema.
    selector = schema.get('properties', {}).get('operation', {})
    choices = [selector] + selector.get('anyOf', []) + selector.get('oneOf', [])
    names = {c['const'] for c in choices if isinstance(c.get('const'), str)}
    names.update(selector.get('enum', []))
    for name in sorted(names & declarations.keys()):
        items.append({'id': 'operation:' + name, 'operation': name, 'title': name,
                      'group': 'filters', 'at': '/operation',
                      'description': purposes.get(name, {}).get('purpose', 'Select ' + name + '.'),
                      'schema': {**{k: v for k, v in selector.items() if k not in ('anyOf', 'oneOf', 'enum')}, 'const': name}})
    hook = meta.get('studioCatalogue')
    if hook and version == meta['version']:
        items.extend(registry.binding(hook)(schema))
    for item in items:
        if item.get('operation'):
            item['capabilityId'] = operation_id(provider, item['operation'])
            item['searchText'] = discovery.operation_search_text(provider, item['operation'])
            item['guidance'] = {**guidance['operations'].get(item['operation'], {'status': 'pending', 'question': 'Explain what this operation produces and when to choose it.'}),
                'provider': provider, 'version': version, 'operation': item['operation']}
            # Cards and form headers lead with the decision-oriented explanation;
            # the application's own summary stays searchable and visible.
            if item['guidance']['status'] != 'pending' and item['guidance'].get('explanation'):
                if item.get('description') and item['description'] != item['guidance']['explanation']:
                    item['nativeDescription'] = item['description']
                item['description'] = item['guidance']['explanation']
        else:
            item['guidance'] = item['schema'].get('x-studio-guide', {'status': 'pending'})
    return copy.deepcopy({'items': items, 'definitions': definitions,
        'requirements': context.get('requirements', []), 'references': context.get('references', [])})


def literal_schema(value):
    """Keep forms literal; runtime expressions remain available in the JSON editor."""
    if isinstance(value, list):
        return [literal_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: literal_schema(item) for key, item in value.items()}
    for keyword in ('anyOf', 'oneOf'):
        if keyword in result:
            branches = [branch for branch in result[keyword] if branch.get('$ref') != '#/$defs/runtime']
            if len(branches) == 1:
                result = {**branches[0], **{key: item for key, item in result.items() if key != keyword}}
            elif branches:
                result[keyword] = branches
    return result


def decorate_options(schema, bindings):
    """Explain native bindings without inventing scientific semantics."""
    for name, binding in bindings.items():
        option = schema.get('properties', {}).get(name)
        if option is None:
            continue
        summary = binding['value'].get('summary', binding['value'].get('title'))
        description = summary or 'Assigns native ' + '.'.join(map(str, binding.get('path', [name]))) + '.'
        if binding.get('constructor'):
            description += ' Fixed at construction; cannot vary per visit.'
        if binding.get('tupleSize'):
            description += f" Complete tuples of {binding['tupleSize']} values."
        option['x-studio-technical'] = description
        if not option.get('x-studio-guide', {}).get('explanation'):
            option['description'] = description
        for branch in option.get('anyOf', []) + option.get('oneOf', []):
            choice = branch.get('properties', {}).get('type', {}).get('enum', [None])[0]
            nested = binding.get('proxyChoices', {}).get(choice)
            if nested:
                branch['title'] = choice
                decorate_options(branch['properties'].get('options', {}), nested['options'])
