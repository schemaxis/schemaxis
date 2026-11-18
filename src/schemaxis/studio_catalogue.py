# Copyright (C) 2026 David L. F. Gaden.
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
    from .studio_guidance import enrich, fields, load
    guidance = load(provider)
    schema = literal_schema(enrich(registry.binding(route['schema'])(), provider, version, guidance))
    definitions = schema.get('$defs', {})
    node_schema = schema.get('properties', {}).get('nodes', {}).get('items', {})
    nodes = [node for node in node_schema.get('oneOf', [node_schema])
             if node.get('properties', {}).get('filter', {}).get('const')]
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
        items.append({'id': 'operation:' + name, 'operation': name, 'title': node.get('title') or (name if native == name else name + ' · ' + native),
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
        if key == 'version' or key == 'nodes' and nodes:
            continue
        is_array = specification.get('type') == 'array'
        items.append({'id': 'document:' + key, 'title': 'Scene' if key == 'scenes' else key,
                      'group': 'presentation', 'description': 'Configure document ' + key + '.',
                      'at': '/' + key + ('/-' if is_array and key in ('scenes', 'sweeps') else ''),
                      'schema': specification['items'] if is_array and key in ('scenes', 'sweeps') else specification})
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
    for path, spec in fields(schema):
        authoring = spec.get('x-studio-guide', {}).get('authoring')
        if authoring:
            validate_authoring_schema({'id': path, 'schema': spec, 'authoring': authoring}, definitions, nested=True)
    for item in items:
        if 'collectionLimit' in item:
            from .errors import fail
            fail('INVALID_STUDIO_CATALOGUE', 'collectionLimit is derived from the route schema, not supplied by hooks', item.get('id'))
        limit = collection_limit(schema, item.get('at'))
        if limit is not None:
            item['collectionLimit'] = limit
        if item.get('operation'):
            if item['at'] == '/nodes/-' and meta.get('studioInputOrder'):
                item['inputOrder'] = meta['studioInputOrder']
            projected_authoring = item['schema'].pop('x-studio-authoring', None)
            authoring = guidance['operations'].get(item['operation'], {}).get('authoring', projected_authoring)
            if authoring is not None:
                validate_authoring(authoring)
                if projected_authoring is authoring:
                    item['authoringBasis'] = 'adaptor Studio catalogue'
                item['authoring'] = copy.deepcopy(authoring)
                validate_authoring_schema(item, definitions)
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
            if item['at'] == '/scenes/-' and (authoring := item['guidance'].get('authoring')):
                item['authoring'] = copy.deepcopy(authoring)
                validate_authoring_schema(item, definitions)
    return copy.deepcopy({'items': items, 'definitions': definitions,
        'requirements': context.get('requirements', []), 'references': context.get('references', [])})


def literal_schema(value, *, _depth=0):
    """Keep forms literal; runtime expressions remain available in the JSON editor."""
    if _depth > 256:
        from .errors import fail
        fail('INVALID_STUDIO_SCHEMA', 'The literal schema exceeds the nesting limit.')
    if isinstance(value, list):
        return [literal_schema(item, _depth=_depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: literal_schema(item, _depth=_depth + 1) for key, item in value.items()}
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


def validate_authoring(value):
    """Bounded Studio-only policies; they never change execution declarations."""
    if not isinstance(value, dict) or not value or set(value) - {'naming', 'multiMode', 'instanceFields', 'identityPeers', 'identityStyle', 'identityField', 'when', 'uniqueFields'}:
        raise ValueError('authoring requires naming or multiMode policies')
    def pointer(path, *, instance=False):
        if not isinstance(path, str) or not path.startswith('/') or '~' in path:
            return False
        _, *segments = path.split('/')
        if instance:
            return 1 <= len(segments) <= 2 and all(segments)
        return len(segments) == 2 and all(segments) and segments[0] == 'options'
    fields = value.get('instanceFields')
    if 'identityField' in value:
        identity = value['identityField']
        if identity is False:
            if 'multiMode' not in value or {'naming', 'identityStyle', 'identityPeers'} & value.keys():
                raise ValueError('Unnamed members support multi-mode without Name policies')
        elif not isinstance(identity, str) or not identity.isidentifier():
            raise ValueError('identityField requires a declared member property or false')
    if 'identityStyle' in value and value['identityStyle'] not in ('label', 'lowercase', 'underscore'):
        raise ValueError('identityStyle must be label, lowercase or underscore when specified')
    gate = value.get('when')
    if 'when' in value and (not isinstance(gate, dict) or set(gate) - {'path', 'values', 'scope'}
            or gate.get('scope', 'document') not in ('document', 'member')
            or not isinstance(gate.get('path'), str) or not gate['path'].startswith('/')
            or not all(part.isidentifier() for part in gate['path'][1:].split('/'))
            or not isinstance(gate.get('values'), list) or not 1 <= len(gate['values']) <= 8
            or any(not isinstance(choice, str) or not choice for choice in gate['values'])):
        raise ValueError('when requires a document or member path and allowed literal values')
    peers = value.get('identityPeers')
    if 'identityPeers' in value and (not isinstance(peers, list) or not 1 <= len(peers) <= 4
            or any(not isinstance(peer, str) or not peer.isidentifier() for peer in peers)):
        raise ValueError('identityPeers requires one to four sibling collection names')
    if 'instanceFields' in value:
        if (not isinstance(fields, list) or not 1 <= len(fields) <= 4 or any(
                not isinstance(field, dict) or set(field) - {'path', 'label', 'style', 'nameField'}
                or not pointer(field.get('path'), instance=True)
                or not isinstance(field.get('label'), str) or not field['label'].strip()
                or field.get('style', 'literal') not in ('literal', 'lastSegment', 'count', 'omit')
                or ('nameField' in field and (not isinstance(field['nameField'], str)
                    or not field['nameField'].isidentifier() or field.get('style') in ('count', 'omit'))) for field in fields)
                or len({field['path'] for field in fields}) != len(fields)):
            raise ValueError('instanceFields requires 1 to 4 distinct member field paths with labels and optional naming styles')
    unique = value.get('uniqueFields')
    if 'uniqueFields' in value and (not isinstance(unique, list) or not 1 <= len(unique) <= 4
            or not fields or any(path not in [field['path'] for field in fields] for path in unique)):
        raise ValueError('uniqueFields must identify declared instance fields')
    if 'naming' in value:
        policy = value['naming']
        if (not isinstance(policy, dict) or set(policy) - {'path', 'style', 'prefix'}
                or (bool({'path', 'style'} & policy.keys()) or not fields)
                and (not pointer(policy.get('path')) or policy.get('style') not in ('literal', 'lastSegment'))
                or ('prefix' in policy and (not isinstance(policy['prefix'], str) or not policy['prefix']))):
            raise ValueError('naming requires an option path, literal/lastSegment style and optional prefix')
    if 'multiMode' in value:
        policy = value['multiMode']
        if not isinstance(policy, dict) or not isinstance(policy.get('rationale'), str) or not policy['rationale'].strip():
            raise ValueError('multiMode requires a rationale')
        if fields:
            if set(policy) - {'batchPath', 'rationale', 'validatePlan'} or ('batchPath' in policy and
                    policy['batchPath'] not in [field['path'] for field in fields]):
                raise ValueError('multiMode batchPath must identify one declared instance field')
            if 'validatePlan' in policy and policy['validatePlan'] is not True:
                raise ValueError('multiMode validatePlan must be true when specified')
        elif (set(policy) != {'path', 'label', 'grouping', 'rationale'}
                or not pointer(policy.get('path')) or policy.get('grouping') != 'exact-list'
                or not isinstance(policy.get('label'), str) or not policy['label'].strip()):
            raise ValueError('multiMode requires an option path, label, exact-list grouping and rationale')



def validate_authoring_schema(item, definitions, *, nested=False):
    """Refuse broken policies before the frontend attempts to build row controls."""
    from .errors import fail
    policy = item['authoring']
    def resolve(spec):
        reference = spec.get('$ref', '')
        if reference.startswith('#/$defs/'):
            return definitions.get(reference[len('#/$defs/'):], {})
        return spec
    def types(spec):
        pending = [spec]
        seen, result = set(), set()
        while pending:
            current = resolve(pending.pop())
            if id(current) in seen:
                continue
            seen.add(id(current))
            if isinstance(current.get('type'), str):
                result.add(current['type'])
            pending.extend(current.get('oneOf', []) + current.get('anyOf', []))
        return result
    def alternatives(spec):
        node = resolve(spec)
        return [node, *node.get('anyOf', []), *node.get('oneOf', [])]
    properties = resolve(item['schema']).get('properties', {})
    identity = policy.get('identityField', 'name' if nested and 'id' not in properties else 'id')
    if (identity is not False and identity not in properties) or (not nested and item.get('at') not in ('/nodes/-', '/scenes/-')):
        fail('INVALID_STUDIO_GUIDANCE', 'element authoring policies require ordinary named elements', item['id'])
    if not nested and {'identityPeers', 'identityStyle', 'identityField', 'when', 'uniqueFields'} & policy.keys():
        fail('INVALID_STUDIO_GUIDANCE', 'nested identity, uniqueness and conditions belong to nested collections', item['id'])
    kind = properties.get('kind')
    planned = policy.get('multiMode', {}).get('validatePlan')
    if nested and kind and 'multiMode' in policy and not planned and 'const' not in kind and len(kind.get('enum', ())) != 1:
        fail('INVALID_STUDIO_GUIDANCE', 'nested authoring policies require a fixed member kind', item['id'])
    if 'multiMode' in policy and item.get('collectionLimit', {}).get('maxItems') == 1:
        fail('INVALID_STUDIO_GUIDANCE', 'A singleton collection cannot have multi-mode', item['id'])
    paths = [(field['path'], {'array', 'object', 'string', 'number', 'integer', 'boolean'}, 'instanceFields')
             for field in policy.get('instanceFields', [])]
    if 'naming' in policy and 'path' in policy['naming']:
        paths.append((policy['naming']['path'], {'array', 'string'}, 'naming'))
    if 'multiMode' in policy:
        multi = policy['multiMode']
        batch = multi.get('batchPath', multi.get('path'))
        if batch:
            paths.append((batch, {'array'}, 'multiMode'))
    for path, allowed, name in paths:
        if identity is not False and path == '/' + identity:
            fail('INVALID_STUDIO_GUIDANCE', 'The Name is edited separately from the instance fields.', item['id'] + path)
        if item.get('at') == '/nodes/-' and path.split('/')[1] not in ('options', 'inputs'):
            fail('INVALID_STUDIO_GUIDANCE', 'node authoring needs a declared input or option path', item['id'] + path)
        spec = item['schema']
        for part in path.split('/')[1:]:
            spec = resolve(spec).get('properties', {}).get(part, {})
        if 'const' in resolve(spec):
            fail('INVALID_STUDIO_GUIDANCE', 'Instance fields must be editable.', item['id'] + path)
        matches = types(spec) & allowed
        if not matches and not (name == 'instanceFields' and (spec.get('enum') or resolve(spec).get('enum'))):
            fail('INVALID_STUDIO_GUIDANCE', f'{name} path must identify a declared {" or ".join(sorted(allowed))} field',
                 item['id'] + path)
    for field in policy.get('instanceFields', []):
        if 'nameField' not in field and field.get('style') != 'count':
            continue
        spec = item['schema']
        for part in field['path'].split('/')[1:]:
            spec = resolve(spec).get('properties', {}).get(part, {})
        variants = alternatives(spec)
        if field.get('style') == 'count':
            if any(resolve(branch).get('type') == 'array' for branch in variants):
                continue
        else:
            for branch in variants:
                member = resolve(branch)
                if member.get('type') == 'array':
                    member = resolve(member.get('items', {}))
                if any(field['nameField'] in resolve(choice).get('properties', {}) for choice in alternatives(member)):
                    break
            else:
                fail('INVALID_STUDIO_GUIDANCE', 'nameField must identify a declared property of the selected record',
                     item['id'] + field['path'])
            continue
        fail('INVALID_STUDIO_GUIDANCE', 'Count naming requires an array', item['id'] + field['path'])


def collection_limit(schema, at):
    """Project a literal array parent's declared bound, never the inserted item schema.

    Local references preserve conjunctive maxItems constraints. Structural
    siblings need a schema intersection solver and are refused rather than merged.
    Other composed or unknown paths supply no cardinality claim.
    """
    if not isinstance(at, str) or not at.startswith('/') or not at.endswith('/-'):
        return None
    from .errors import fail
    import math
    def maximum(value):
        if (type(value) not in (int, float)
                or type(value) is float and (not math.isfinite(value) or not value.is_integer())
                or not 0 <= value <= 9007199254740991):
            fail('INVALID_STUDIO_CATALOGUE', 'maxItems must be a nonnegative safe integer', at)
        return int(value)
    definitions = schema.get('$defs', {})
    annotations = {'title', 'description', '$comment', 'default', 'examples', 'deprecated', 'readOnly', 'writeOnly'}
    def resolve(spec):
        seen = set()
        while isinstance(spec, dict) and '$ref' in spec:
            ref = spec['$ref']
            if not isinstance(ref, str) or not ref.startswith('#/$defs/') or ref in seen:
                return {}
            seen.add(ref)
            key = ref[len('#/$defs/'):].replace('~1', '/').replace('~0', '~')
            target = definitions.get(key)
            if not isinstance(target, dict):
                return {}
            siblings = {k: v for k, v in spec.items() if k != '$ref'}
            unsupported = set(siblings) - annotations - {'maxItems'}
            unsupported = {k for k in unsupported if not k.startswith('x-')}
            if unsupported:
                fail('INVALID_STUDIO_CATALOGUE',
                     'collection limit cannot project structural $ref siblings: ' + ', '.join(sorted(unsupported)), at)
            bounds = [maximum(part['maxItems']) for part in (target, siblings) if 'maxItems' in part]
            spec = {**target, **siblings}
            if bounds:
                spec['maxItems'] = min(bounds)
        return spec if isinstance(spec, dict) else {}
    spec = schema
    for part in at.split('/')[1:-1]:
        spec = resolve(spec)
        if any(key in spec for key in ('allOf', 'anyOf', 'oneOf', 'if')):
            return None
        part = part.replace('~1', '/').replace('~0', '~')
        if spec.get('type') == 'array' and (part.isdecimal() or part.startswith('{') and part.endswith('}')):
            spec = spec.get('items', {})
        else:
            spec = spec.get('properties', {}).get(part, {})
    spec = resolve(spec)
    if spec.get('type') != 'array' or 'maxItems' not in spec:
        return None
    if any(key in spec for key in ('allOf', 'anyOf', 'oneOf', 'if')):
        return None
    return {'path': at[:-2], 'maxItems': maximum(spec['maxItems'])}
