# Copyright (C) 2026 David L. F. Gaden.
"""Adaptor-owned conceptual guidance, host-safe projection and honest coverage."""
import json
import re
from .adaptors import registry
from .errors import fail

VERSION = 'schemaxis.studio-guidance/1'
STATUSES = {'reviewed', 'reference', 'pending'}
PARTS = {'status', 'explanation', 'units', 'defaultMeaning', 'pitfalls', 'examples', 'sources', 'question', 'fileExtensions', 'label', 'control', 'authoring'}


def escape(part):
    return str(part).replace('~', '~0').replace('/', '~1')


def fields(schema):
    """Stable schema addresses, including alternatives, arrays and dynamic maps.

    References are inventoried at their definition once, rather than expanded.
    Validation keywords and literal defaults are never treated as schemas.
    """
    def visit(node, path='', depth=0):
        if not isinstance(node, dict):
            return
        if depth > 128:
            fail('INVALID_STUDIO_SCHEMA', 'The schema exceeds the nesting limit.', path)
        yield path, node
        for key in ('properties', '$defs', 'patternProperties'):
            for name, child in node.get(key, {}).items():
                yield from visit(child, path + '/' + key + '/' + escape(name), depth + 1)
        for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else'):
            if isinstance(node.get(key), dict):
                yield from visit(node[key], path + '/' + key, depth + 1)
        for key in ('oneOf', 'anyOf', 'allOf', 'prefixItems'):
            for index, child in enumerate(node.get(key, [])):
                yield from visit(child, path + '/' + key + '/' + str(index), depth + 1)
    return visit(schema)


def load(provider):
    path = registry.adaptor_files(provider).joinpath('guidance.json')
    if not path.is_file():
        return {'version': VERSION, 'operations': {}, 'routes': {}}
    try:
        value = json.loads(path.read_text())
        if set(value) != {'version', 'operations', 'routes'} or value['version'] != VERSION:
            raise ValueError('expected version, operations and routes')
        if (not isinstance(value['operations'], dict) or not isinstance(value['routes'], dict)
                or any(not isinstance(k, str) or not k for k in [*value['operations'], *value['routes']])):
            raise ValueError('operations and routes require named maps')
        records = list(value['operations'].values())
        for route in value['routes'].values():
            if set(route) != {'fields'} or not isinstance(route['fields'], dict):
                raise ValueError('each route requires a fields map')
            if any(not isinstance(k, str) or (k and not k.startswith('/')) or re.search(r'~(?![01])', k) for k in route['fields']):
                raise ValueError('field addresses must be RFC 6901 schema pointers')
            records.extend(route['fields'].values())
        for record in records:
            validate_record(record)
        return value
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        fail('INVALID_STUDIO_GUIDANCE', str(error), str(path))



def validate_record(record):
    if not isinstance(record, dict) or set(record) - PARTS or record.get('status') not in STATUSES:
        raise ValueError('invalid guidance record or status')
    for key in ('explanation', 'units', 'defaultMeaning', 'question', 'label'):
        if key in record and (not isinstance(record[key], str) or not record[key].strip()):
            raise ValueError(key + ' requires nonempty text')
    for key in ('pitfalls', 'sources', 'fileExtensions'):
        if key in record and (not isinstance(record[key], list) or any(not isinstance(x, str) or not x.strip() for x in record[key])):
            raise ValueError(key + ' requires a text array')
    if 'examples' in record and not isinstance(record['examples'], list):
        raise ValueError('examples requires an array')
    if 'authoring' in record:
        from .studio_catalogue import validate_authoring
        validate_authoring(record['authoring'])
    if 'control' in record:
        control = record['control']
        line = (isinstance(control, dict) and set(control) == {'kind', 'start', 'end'}
                and control['kind'] == 'line' and all(isinstance(control[k], str) and control[k]
                    for k in ('start', 'end')) and control['start'] != control['end'])
        blocks = (isinstance(control, dict) and set(control) == {'kind', 'input'}
                  and control['kind'] == 'blocks' and isinstance(control['input'], str) and bool(control['input']))
        reader = (isinstance(control, dict) and set(control) == {'kind', 'field'}
                  and control['kind'] == 'reader-selection' and control['field'] in ('regions', 'cellArrays'))
        arrays = (isinstance(control, dict) and set(control) == {'kind', 'input', 'association'}
                  and control['kind'] == 'dataset-arrays' and isinstance(control['input'], str) and bool(control['input'])
                  and control['association'] in ('POINTS', 'CELLS'))
        nodes = (isinstance(control, dict) and set(control) == {'kind', 'nodeKind'}
                 and control['kind'] == 'document-nodes' and isinstance(control['nodeKind'], str)
                 and bool(control['nodeKind']))
        assembly = (isinstance(control, dict) and set(control) == {'kind', 'input', 'assemblyOption', 'defaultAssembly'}
                    and control['kind'] == 'assembly-paths'
                    and all(isinstance(control[key], str) and bool(control[key])
                            for key in ('input', 'assemblyOption', 'defaultAssembly')))
        discrete = control in ({'kind': 'file-subset'}, {'kind': 'enum-subset'})
        collections = control.get('collection') if isinstance(control, dict) else None
        collections = [collections] if isinstance(collections, str) else collections
        roots = control.get('rootCollections', []) if isinstance(control, dict) else []
        entry_fields = control.get('field') if isinstance(control, dict) else None
        entry_fields = [entry_fields] if isinstance(entry_fields, str) else entry_fields
        match = control.get('match') if isinstance(control, dict) else None
        if match is not None and (not isinstance(match, dict) or not {'field', 'value'} <= set(match) or set(match) - {'field', 'value', 'invert'}
                or not isinstance(match['field'], str) or not match['field'].isidentifier()
                or not isinstance(match['value'], str) or not isinstance(match.get('invert', False), bool)):
            raise ValueError('match requires a field and literal text value')
        qualified = control.get('qualified') if isinstance(control, dict) else None
        if qualified is not None and (not isinstance(qualified, dict)
                or not {'ownerField', 'members', 'activeAt'} <= set(qualified)
                or set(qualified) - {'ownerField', 'members', 'activeAt', 'activeDepth', 'unqualified'}
                or type(qualified.get('activeDepth', 0)) is not int or not 0 <= qualified.get('activeDepth', 0) <= 12
                or not isinstance(qualified.get('unqualified', False), bool)
                or any(not isinstance(qualified[key], str) or not qualified[key].isidentifier()
                       for key in ('ownerField', 'members'))
                or not isinstance(qualified['activeAt'], list) or not 0 < len(qualified['activeAt']) <= 4
                or any(not isinstance(path, str) or not re.fullmatch(r'(?:/[A-Za-z][A-Za-z0-9_]*){1,8}', path)
                       for path in qualified['activeAt'])):
            raise ValueError('qualified choices require declared collection members and active owner pointers')
        entries = (isinstance(control, dict) and {'kind', 'collection', 'field'} <= set(control)
                   and set(control) <= {'kind', 'collection', 'field', 'scopeDepth', 'exclude', 'qualified', 'match', 'rootCollections'}
                   and control['kind'] == 'document-entries'
                   and isinstance(collections, list) and 0 < len(collections) <= 8
                   and isinstance(roots, list) and len(roots) <= 8
                   and all(isinstance(path, str) and re.fullmatch(r'(?:/[A-Za-z][A-Za-z0-9_]*){1,8}', path)
                           for path in collections + roots)
                   and isinstance(entry_fields, list) and 0 < len(entry_fields) <= 8
                   and all(isinstance(field, str) and field.isidentifier() for field in entry_fields)
                   and isinstance(control.get('exclude', []), list)
                   and all(isinstance(value, str) for value in control.get('exclude', []))
                   and type(control.get('scopeDepth', 0)) is int and 0 <= control.get('scopeDepth', 0) <= 8)
        inspected = (isinstance(control, dict) and {"kind", "source", "field"} <= set(control) <= {"kind", "source", "field", "native", "documentSource", "sourceLevels", "sourcePointer"}
                     and type(control.get("sourceLevels", 0)) is int and 0 <= control.get("sourceLevels", 0) <= 4
                     and all(type(control.get(key, False)) is bool for key in ("native", "documentSource", "sourcePointer"))
                     and control["kind"] == "inspected-entries"
                     and isinstance(control["source"], str) and control["source"].startswith("/")
                     and control["source"][1:].isidentifier()
                     and isinstance(control["field"], str) and control["field"].isidentifier())
        if not (line or blocks or reader or arrays or nodes or assembly or discrete or entries or inspected):
            raise ValueError('Use a supported Studio control and its declared settings')
    if record['status'] != 'pending' and not record.get('explanation'):
        raise ValueError('available guidance requires an explanation')
    if record['status'] != 'pending' and record['explanation'].strip().lower().startswith(('todo', 'tbd', 'replace scaffold', 'development scaffold')):
        raise ValueError('placeholder prose must remain pending')
    if record['status'] == 'reference' and not record.get('sources'):
        raise ValueError('reference guidance requires provenance')

def enrich(schema, provider, version, guidance=None):
    """Annotate a copy; authored validation constraints are unchanged."""
    # Schema builders reuse dictionaries. Each occurrence needs its own address
    # and explanation; deepcopy preserves those aliases and lets the last win.
    try:
        result = json.loads(json.dumps(schema))
    except (RecursionError, ValueError, TypeError):
        fail('INVALID_STUDIO_SCHEMA', 'The schema must be JSON with finite nesting.', version)
    guidance = load(provider) if guidance is None else guidance
    records = guidance.get('routes', {}).get(version, {}).get('fields', {})
    for path, node in fields(result):
        annotate(node, records.get(path, {'status': 'pending'}), path, provider, version)
    # Bindings belong in every projection (Properties, editor Help and Add), not
    # only the Add catalogue. These are API facts, not reviewed scientific prose.
    declarations = registry.declarations(provider)
    for name, declaration in declarations.items():
        annotate_bindings(result.get('$defs', {}).get('options-' + name, {}), declaration)
    for _, node in fields(result):
        name = node.get('properties', {}).get('filter', {}).get('const')
        declaration = declarations.get(name, {})
        for key, field in node.get('properties', {}).get('inputs', {}).get('properties', {}).items():
            port = declaration.get('inputs', {}).get(key, {})
            field['x-studio-reference'] = {'kind': port.get('kind', 'object'), 'multiple': bool(port.get('multiple')), 'port': key}
            native = port.get('native')
            if native:
                field['x-studio-guide']['binding'] = {'operation': declaration.get('native', name), 'property': native, 'key': key}
    return result


def enumerated_subset(node):
    items = node.get('items')
    values = items.get('enum') if isinstance(items, dict) else None
    return (node.get('type') == 'array' and node.get('uniqueItems') is True
            and isinstance(values, list) and bool(values)
            and all(isinstance(value, str) and value for value in values))


def annotate(node, guide, path, provider, version):
    node['x-studio-guide'] = {**guide, 'address': path, 'version': version, 'provider': provider}
    if guide.get('label'):
        node['title'] = guide['label']
    if guide.get('control'):
        node['x-studio-control'] = guide['control']
    elif enumerated_subset(node):
        node['x-studio-control'] = {'kind': 'enum-subset'}
    if guide.get('explanation'):
        if node.get('description'):
            node['x-studio-technical'] = node['description']
        node['description'] = guide['explanation']
    if 'fileExtensions' in guide:
        node['x-studio-file'] = {'extensions': guide['fileExtensions']}


# Shared Studio documents are not adaptors. Their embedded adaptor documents
# ($defs/pipelineN) keep each adaptor's own guidance; the workflow route owns
# the envelope and the shared authoring markers ($document, $expr, $value,
# $analytic, …), which design routes and authored adaptor schemas reuse.
SHARED = {'schemaxis.workflow/1': 'workflow', 'schemaxis.workflow-design/1': 'workflow-design',
          'schemaxis.workflow-design/2': 'workflow-design'}
MARKERS_ROUTE = 'schemaxis.workflow/1'


def marker_definitions():
    from .schema_authoring import composition_definitions
    # capturedInput is shared by every adaptor that admits captured inputs.
    return set(composition_definitions()) | {'capturedInput'}


def shared_schema(version, annotate_documents=None):
    if version == MARKERS_ROUTE:
        from .schema_authoring import workflow_schema
        return workflow_schema(authored=True, annotate=annotate_documents)
    from .studio_schemas import design_schema
    return design_schema(version, annotate=annotate_documents)


def owner(version, path, markers):
    """Return (route, address) owning a shared address, or None for adaptor-owned documents."""
    parts = path.split('/')
    if len(parts) > 2 and parts[1] == '$defs' and parts[2].startswith('pipeline'):
        # An embedded document's own copy of the shared marker definitions.
        if len(parts) > 4 and parts[3] == '$defs' and parts[4] in markers:
            return MARKERS_ROUTE, '/' + '/'.join(parts[3:])
        return None
    if len(parts) > 2 and parts[1] == '$defs' and parts[2] in markers:
        return MARKERS_ROUTE, path
    if version != MARKERS_ROUTE and path.startswith('/properties/workflow/'):
        return MARKERS_ROUTE, path[len('/properties/workflow'):]
    return version, path


def shared_fields(version, schema=None):
    """Addresses a shared route owns; reused workflow and marker addresses are excluded."""
    schema = shared_schema(version) if schema is None else schema
    markers = marker_definitions()
    return [(path, node) for path, node in fields(schema) if owner(version, path, markers) == (version, path)]


def document_annotator(version):
    provider = next((name for name, meta in registry.ADAPTORS.items() if version in meta['routes']), None)
    return (lambda schema: enrich(schema, provider, version)) if provider else None


def enrich_shared(version):
    """Shared document schema with adaptor and shared guidance projected."""
    # Builders reuse definition objects; annotate an independent copy.
    result = json.loads(json.dumps(shared_schema(version, document_annotator)))
    markers = marker_definitions()
    guides = {name: load(name)['routes'] for name in set(SHARED.values())}
    for path, node in fields(result):
        found = owner(version, path, markers)
        if found:
            route, address = found
            records = guides[SHARED[route]].get(route, {}).get('fields', {})
            annotate(node, records.get(address, {'status': 'pending'}), address, SHARED[route], route)
    return result


def enrich_markers(schema):
    """Return a copy with shared authoring-marker definitions annotated."""
    schema = json.loads(json.dumps(schema))
    records = load(SHARED[MARKERS_ROUTE])['routes'].get(MARKERS_ROUTE, {}).get('fields', {})
    markers = marker_definitions()
    for path, node in fields(schema):
        parts = path.split('/')
        if len(parts) > 2 and parts[1] == '$defs' and parts[2] in markers:
            annotate(node, records.get(path, {'status': 'pending'}), path, SHARED[MARKERS_ROUTE], MARKERS_ROUTE)
    return schema


def audit_shared(provider):
    guidance = load(provider)
    result = {'provider': provider, 'operations': {}, 'routes': {}, 'stale': [], 'counts': {key: 0 for key in STATUSES}}
    for version in [v for v, name in SHARED.items() if name == provider]:
        records = guidance['routes'].get(version, {}).get('fields', {})
        addresses = {path for path, _ in shared_fields(version)}
        statuses = {path: records.get(path, {'status': 'pending'})['status'] for path in sorted(addresses)}
        result['routes'][version] = statuses
        for status in statuses.values():
            result['counts'][status] += 1
        result['stale'].extend(version + ':' + path for path in records if path not in addresses)
    result['stale'].extend('route:' + version for version in guidance['routes'] if SHARED.get(version) != provider)
    result['complete'] = not result['counts']['pending'] and not result['stale']
    return result


def option_guidance(provider):
    """Map each declared operation's top-level option keys to their guidance records.

    Reference pages reuse the same conceptual text as Studio forms. Options are
    found through the operation's node variant or options definition in each
    route; unexplained options are simply absent from the result.
    """
    guidance = load(provider)
    result = {}
    def literal(node):
        for key in ('anyOf', 'oneOf'):
            branches = node.get(key) if isinstance(node, dict) else None
            if isinstance(branches, list) and len(branches) == 2:
                refs = [b for b in branches if isinstance(b, dict) and set(b) == {'$ref'}]
                if len(refs) == 1:
                    return literal(next(b for b in branches if b is not refs[0]))
        return node
    for version, route in registry.metadata(provider)['routes'].items():
        records = guidance['routes'].get(version, {}).get('fields', {})
        schema = registry.binding(route['schema'])()
        for path, node in fields(schema):
            properties = node.get('properties', {}) if isinstance(node, dict) else {}
            name = (properties.get('filter') or properties.get('operation') or {}).get('const')
            options = properties.get('options')
            if path.startswith('/$defs/options-') and path.count('/') == 2:
                name, options, base = path.split('/')[2][len('options-'):], node, path
            elif name and isinstance(options, dict) and '$ref' not in options:
                base = path + '/properties/options'
            else:
                continue
            for key in literal(options).get('properties', {}):
                address = base + '/properties/' + escape(key)
                record = records.get(address)
                if record and record.get('explanation'):
                    result.setdefault(name, {}).setdefault(key, record)
    return result


def annotate_bindings(schema, declaration, prefix=''):
    for key, binding in declaration.get('options', {}).items():
        field = schema.get('properties', {}).get(key)
        if field is None:
            continue
        path = '.'.join(map(str, binding.get('path', [])))
        if path:
            native = {'operation': declaration.get('native', declaration.get('id', '')),
                      'property': prefix + path, 'key': key, 'constructor': bool(binding.get('constructor'))}
            field.setdefault('x-studio-guide', {'status': 'pending'})['binding'] = native
        for branch in field.get('oneOf', []) + field.get('anyOf', []):
            names = branch.get('properties', {}).get('type', {}).get('enum', [])
            nested = binding.get('proxyChoices', {}).get(names[0]) if len(names) == 1 else None
            if nested:
                annotate_bindings(branch['properties'].get('options', {}),
                    {**nested, 'native': declaration.get('native', '')}, prefix + path + '.')


def audit_links(guidance, root):
    """Local provenance must resolve; native citations remain attributed data."""
    from .readiness import Audit
    link_audit = Audit(root)
    sources, stale = set(), []
    for records in [guidance['operations'], *(r['fields'] for r in guidance['routes'].values())]:
        for address, record in records.items():
            for source in record.get('sources', []):
                if source.startswith('guidance:'):
                    origin = source[len('guidance:'):]
                    exists = (origin[len('operation '):] in guidance['operations']
                              if origin.startswith('operation ') else origin in records)
                    if not exists:
                        stale.append({'source': source, 'address': address, 'status': 'fail', 'message': 'Derived guidance origin is absent.'})
                else:
                    sources.add(source)
    for source in sorted(sources):
        if source.startswith(('http:', 'https:', 'docs/', 'src/', 'tools/', 'tests/', 'examples/', 'verification/')):
            # A preserved citation may add a parenthesised explanation after
            # its address. Validate the address and retain the full attribution.
            link_audit.link(source.split(' (', 1)[0], 'guidance.source')
            link_audit.checks[-1]['citation'] = source
    issues = [c for c in link_audit.checks if c['status'] == 'fail' or (c['status'] == 'unknown' and c['required'])]
    return issues + stale


def audit(provider, *, root=None):
    guidance = load(provider)
    meta = registry.metadata(provider)
    result = {'provider': provider, 'operations': {}, 'routes': {}, 'stale': [], 'counts': {key: 0 for key in STATUSES}}
    declared = registry.declarations(provider)
    for name in declared:
        record = guidance['operations'].get(name, {'status': 'pending'})
        result['operations'][name] = record['status']
        result['counts'][record['status']] += 1
    result['stale'].extend('operation:' + name for name in guidance['operations'] if name not in declared)
    for version, route in meta['routes'].items():
        schema = registry.binding(route['schema'])()
        records = guidance['routes'].get(version, {}).get('fields', {})
        addresses = {path for path, _ in fields(schema)}
        statuses = {path: records.get(path, {'status': 'pending'})['status'] for path in sorted(addresses)}
        result['routes'][version] = statuses
        for status in statuses.values():
            result['counts'][status] += 1
        result['stale'].extend(version + ':' + path for path in records if path not in addresses)
    result['stale'].extend('route:' + version for version in guidance['routes'] if version not in meta['routes'])
    from .readiness import repository_root
    issues = audit_links(guidance, repository_root(provider) if root is None else root)
    if issues and root is None and repository_root(provider) != repository_root():
        # External adaptor guidance may also cite the shared framework in the core checkout.
        shared = {issue.get('citation') for issue in audit_links(guidance, repository_root())}
        issues = [issue for issue in issues if issue.get('citation') in shared]
    result['linkIssues'] = issues
    result['complete'] = not result['counts']['pending'] and not result['stale'] and not result['linkIssues']
    return result
