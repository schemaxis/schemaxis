# Copyright (C) 2026 David L F Gaden
"""Adaptor-owned conceptual guidance, host-safe projection and honest coverage."""
import json
import re
from .adaptors import registry
from .errors import fail

VERSION = 'schemaxis.studio-guidance/1'
STATUSES = {'reviewed', 'reference', 'pending'}
PARTS = {'status', 'explanation', 'units', 'defaultMeaning', 'pitfalls', 'examples', 'sources', 'question', 'fileExtensions', 'label', 'control'}


def escape(part):
    return str(part).replace('~', '~0').replace('/', '~1')


def fields(schema):
    """Stable schema addresses, including alternatives, arrays and dynamic maps.

    References are inventoried at their definition once, rather than expanded.
    Validation keywords and literal defaults are never treated as schemas.
    """
    def visit(node, path=''):
        if not isinstance(node, dict):
            return
        yield path, node
        for key in ('properties', '$defs', 'patternProperties'):
            for name, child in node.get(key, {}).items():
                yield from visit(child, path + '/' + key + '/' + escape(name))
        for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else'):
            if isinstance(node.get(key), dict):
                yield from visit(node[key], path + '/' + key)
        for key in ('oneOf', 'anyOf', 'allOf', 'prefixItems'):
            for index, child in enumerate(node.get(key, [])):
                yield from visit(child, path + '/' + key + '/' + str(index))
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
    if 'control' in record:
        control = record['control']
        line = (isinstance(control, dict) and set(control) == {'kind', 'start', 'end'}
                and control['kind'] == 'line' and all(isinstance(control[k], str) and control[k]
                    for k in ('start', 'end')) and control['start'] != control['end'])
        blocks = (isinstance(control, dict) and set(control) == {'kind', 'input'}
                  and control['kind'] == 'blocks' and isinstance(control['input'], str) and bool(control['input']))
        if not line and not blocks:
            raise ValueError('control requires line endpoint names or a blocks input port')
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
    result = json.loads(json.dumps(schema))
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


def annotate(node, guide, path, provider, version):
    node['x-studio-guide'] = {**guide, 'address': path, 'version': version, 'provider': provider}
    if guide.get('label'):
        node['title'] = guide['label']
    if guide.get('control'):
        node['x-studio-control'] = guide['control']
    if guide.get('explanation'):
        if node.get('description'):
            node['x-studio-technical'] = node['description']
        node['description'] = guide['explanation']
    if guide.get('fileExtensions'):
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
    return set(composition_definitions())


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
