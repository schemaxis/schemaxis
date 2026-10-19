"""JSON Schema export from Schemaxis's existing typed declarations.

This module projects expanded input and literal declarations; schema_authoring
adds authored syntax and all-format exports. Graph/native validation remains in plan/run.
No native application or third-party schema package is imported here.
"""
import copy
from schemaxis.core.declarations import validate_specification
from .errors import fail

DRAFT = 'https://json-schema.org/draft/2020-12/schema'
NAME = {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]*$'}


def object_schema(properties, required=()):
    result = {'type': 'object', 'properties': properties, 'additionalProperties': False}
    if required:
        result['required'] = list(required)
    return result


def argument_schema(specification, *, dynamic=False):
    """Project the closed declaration grammar; defaults are annotations only."""
    validate_specification(specification, 'schema')
    spec = copy.deepcopy(specification)
    kind = spec['type']
    if kind == 'union':
        result = {'anyOf': [argument_schema(s, dynamic=dynamic) for s in spec['options']]}
    elif kind == 'enum':
        result = {'enum': spec['values']}
    elif kind == 'object':
        result = arguments_schema(spec.get('properties', {}), dynamic=dynamic)
    else:
        result = {'type': kind}
        if kind == 'array':
            result['items'] = argument_schema(spec['items'], dynamic=dynamic)
        for key in ('minLength', 'maxLength', 'minItems', 'maxItems', 'uniqueItems'):
            if key in spec:
                result[key] = spec[key]
        for bound in ('minimum', 'maximum'):
            if bound in spec:
                exclusive = 'exclusive' + bound.title()
                result[exclusive if spec.get(exclusive) else bound] = spec[bound]
    if dynamic:
        result = {'anyOf': [result, {'$ref': '#/$defs/runtime'}]}
    for key in ('default', 'title'):
        if key in spec:
            result[key] = spec[key]
    if 'summary' in spec:
        result['description'] = spec['summary']
    return result


def arguments_schema(specifications, *, dynamic=False):
    return object_schema({k: argument_schema(v, dynamic=dynamic) for k, v in specifications.items()},
                         [k for k, v in specifications.items() if v.get('required')])


def declarations(provider):
    from .adaptors.registry import declarations as registered
    return registered(provider)


def option_schema(declaration, *, dynamic=False):
    properties = {k: argument_schema(v['value'], dynamic=dynamic and not v.get('constructor'))
                  for k, v in declaration['options'].items()}
    result = object_schema(properties, [k for k, v in declaration['options'].items() if v['value'].get('required')])
    # Cross-field comparisons need the planner. Retain them as machine-readable metadata.
    for key in ('checks', 'requires', 'coverage', 'execution', 'nativeIdentity', 'role', 'publication', 'commands'):
        if declaration.get(key):
            result['x-schemaxis-' + key] = copy.deepcopy(declaration[key])
    for key, binding in declaration['options'].items():
        for annotation in ('constructor', 'convert', 'compiler', 'path', 'cardinalityBasis', 'tupleSize', 'tupleElementTypes'):
            if annotation in binding:
                properties[key]['x-schemaxis-' + annotation] = copy.deepcopy(binding[annotation])
    return result


def runtime_schema(provider):
    from .functions import FUNCTIONS
    path = {'type': 'array', 'items': {'anyOf': [{'type': 'string'}, {'type': 'integer'}]}}
    variants = [object_schema({'$axis': {'type': 'string'}, 'path': path}, ['$axis']),
                object_schema({'$observe': NAME, 'path': path}, ['$observe']),
                object_schema({'$time': {'const': True}}, ['$time'])]
    counts = {'vector': 3, 'midpoint': 1, 'boundsMin': 1, 'boundsMax': 1,
              'add': 2, 'subtract': 2, 'multiply': 2, 'divide': 2, 'min': 2, 'max': 2}
    for name, count in counts.items():
        variants.append(object_schema({'$calc': {'const': name}, 'args': {
            'type': 'array', 'items': {'$ref': '#/$defs/runtimeValue'}, 'minItems': count, 'maxItems': count}}, ['$calc', 'args']))
    for name, entry in FUNCTIONS.describe().items():
        variants.append(object_schema({'$call': {'const': name},
            'args': arguments_schema(entry['arguments'], dynamic=True)},
            ['$call'] + (['args'] if any(v.get('required') for v in entry['arguments'].values()) else [])))
    from .adaptors.registry import metadata, binding
    hook = metadata(provider).get('runtimeSchema')
    if hook: variants.extend(binding(hook)())
    return {'anyOf': variants}


def graph_document_schema(provider, scene_builder, *, reference=NAME, source_times=False, max_scenes=None):
    from schemaxis.core.series import SERIES_ARGUMENT
    from schemaxis.core.times import TIMES_ARGUMENT
    from .adaptors.registry import metadata
    catalogue = declarations(provider)
    definitions = {'runtime': runtime_schema(provider)}
    nodes = []
    for name, declaration in sorted(catalogue.items()):
        key = 'options-' + name
        definitions[key] = option_schema(declaration, dynamic=True)
        if declaration.get('role') == 'writer':
            continue
        ports = {p: ({'type': 'array', 'items': reference if s.get('kind','data')=='data' else NAME, 'minItems': 1}
                     if s.get('multiple') else reference if s.get('kind','data')=='data' else NAME)
                 for p, s in declaration['inputs'].items()}
        ports = copy.deepcopy(ports)
        for port, spec in declaration['inputs'].items():
            if spec.get('contract'):
                ports[port]['x-schemaxis-contract'] = copy.deepcopy(spec['contract'])
        required_ports = [p for p, s in declaration['inputs'].items() if s.get('required')]
        props = {'id': NAME, 'filter': {'const': name},
                 'inputs': object_schema(ports, required_ports), 'options': {'$ref': '#/$defs/' + key}}
        props['onVisit'] = {'type':'array', 'items':({'enum':sorted(declaration['commands'])} if declaration.get('commands') else False),
                                'description':'Invoke in order before updating this node on every selected visit.'}
        required = ['id', 'filter']
        if required_ports:
            required.append('inputs')
        if definitions[key].get('required'):
            required.append('options')
        nodes.append(object_schema(props, required))
    scene = scene_builder(catalogue, definitions)
    axis = object_schema({'name': NAME, 'values': {'type': 'array', 'minItems': 1},
                          'series': argument_schema(SERIES_ARGUMENT)}, ['name'])
    axis['oneOf'] = [{'required': ['values'], 'not': {'required': ['series']}},
                     {'required': ['series'], 'not': {'required': ['values']}}]
    times = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 1, 'default': [0.0]}
    if source_times:
        times = {'anyOf': [times, object_schema({'source': NAME, 'select': argument_schema(TIMES_ARGUMENT)}, ['source', 'select'])]}
    scenes = {'type': 'array', 'items': scene, 'minItems': 1}
    if max_scenes is not None:
        scenes['maxItems'] = max_scenes
    result = object_schema({'version': {'const': metadata(provider)['version']},
        'nodes': {'type': 'array', 'items': {'oneOf': nodes}, 'minItems': 1}, 'scenes': scenes,
        'axes': {'type': 'array', 'items': axis}, 'times': times,
        **{key: {'$ref': '#/$defs/json'} for key in ('definitions', 'dimensions', 'views', 'settings')},
        'maxStates': {'type': 'integer', 'minimum': 1, 'default': 10000},
        'maxPublications': {'type': 'integer', 'minimum': 1, 'default': 10000}}, ['version', 'nodes', 'scenes'])
    definitions['json'] = json_value_schema()
    definitions['runtimeValue'] = {'anyOf': [{'type': ['null', 'boolean', 'number', 'string']},
        {'type': 'array', 'items': {'$ref': '#/$defs/runtimeValue'}}, {'$ref': '#/$defs/runtime'}]}
    axis['properties']['values']['items'] = {'$ref': '#/$defs/json'}
    return {'$schema': DRAFT, 'title': 'Schemaxis ' + provider + ' expanded input',
        'description': 'Structural schema after document composition, inline objects and analytics expansion. '
                       'Run Schemaxis plan/run for reference, dependency, cross-option, expression-result and native validation.',
        '$defs': definitions, **result}


def json_value_schema():
    """Explicit recursive JSON data, used only for parser-owned free data."""
    return {'anyOf': [{'type': ['null', 'boolean', 'number', 'string']},
        {'type': 'array', 'items': {'$ref': '#/$defs/json'}},
        {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/json'}}]}


def document_schema(provider):
    from .adaptors.registry import metadata, binding
    item = metadata(provider)
    return binding(item['routes'][item['version']]['schema'])()


def export_schema(provider=None, operation=None, section=None, *, authored=False, version=None, all_versions=False):
    from .adaptors.registry import metadata, binding, ADAPTORS
    item = metadata(provider)
    provider = item['id']
    if authored or version or all_versions or section in ('workflow', 'execution', 'operation-execution', 'composition', 'analytic'):
        from .schema_authoring import export
        return export(provider, operation=operation, section=section, authored=authored, version=version, all_versions=all_versions)
    if operation is not None:
        catalogue = declarations(provider)
        if operation not in catalogue:
            fail('UNKNOWN_FILTER', 'filter is not declared', operation, available=sorted(catalogue))
        function = binding(item['optionSchema']) if item.get('optionSchema') else option_schema
        return {'$schema': DRAFT, 'title': provider + '.' + operation + ' literal options', **function(catalogue[operation])}
    if section:
        from .camera import CAMERA
        from schemaxis.core.series import SERIES_ARGUMENT
        common = {'camera': lambda: arguments_schema(CAMERA), 'series': lambda: argument_schema(SERIES_ARGUMENT)}
        paths = {k: v for m in ADAPTORS.values() for k, v in m.get('sections', {}).items()}
        if section in common: result = common[section]()
        elif section in paths: result = binding(paths[section])()
        else: fail('UNKNOWN_SECTION', 'schema section is unavailable', section)
        return {'$schema': DRAFT, 'title': 'Schemaxis ' + section + ' literal settings', **result}
    return document_schema(provider)


def expand_input(document):
    """Prepare registered authoring conveniences without loading native apps."""
    from .adaptors.registry import resolve, plan
    from schemaxis.documents import resolve_document
    from .context import compile_objects
    from .analytics import compile_analytics
    from .pipeline import markers
    if document.get('version') == 'schemaxis.workflow/1':
        from .workflow import validate, study_required, dependencies
        from .adaptor_runtime import InputProgram, pending, workflow_inputs, META
        if study_required(document) or pending(document):
            program = InputProgram(document, workflow=True)
            return {'version': 'schemaxis.study/1', 'documentVersion': document['version'],
                    'visits': [{**visit, 'deferredReferences': [ref for ref in dependencies(visit['document']) if pending(ref)]}
                               for visit in program.visits()]}
        document = workflow_inputs(document)
        operations = validate(document)
        return {**{k: copy.deepcopy(v) for k, v in document.items() if k not in (*META, 'axes', 'maxStates')},
                'operations': [{**operation, 'document': expand_input(operation['document'])} for operation in operations]}
    _, route = resolve(document)
    from .adaptor_runtime import InputProgram, requires_common
    if requires_common(document, route):
        program = InputProgram(document, route)
        visits = list(program.visits())
        if program.groups:
            return {'version': 'schemaxis.study/1', 'documentVersion': document['version'], 'visits': visits}
        document = visits[0]['document']
    mode = route.get('expand', 'graph' if route.get('graph') else 'identity')
    if mode == 'identity': return copy.deepcopy(document)
    if mode == 'plannedNodes':
        from .workflow import dependencies
        # A producer's verified artifact can determine consumer validity and
        # defaults. Retain its authored document until that input is available;
        # a fabricated path must never enter an adaptor's literal planner.
        if any(dependencies(document)):
            return copy.deepcopy(document)
        return {**copy.deepcopy(document), 'nodes': plan(document)['nodes']}
    result, _ = resolve_document(copy.deepcopy(document))
    if mode == 'composition': return result
    result = compile_objects(result)
    if any('$analytic' in marker for marker in markers(result)):
        result, _ = compile_analytics(result)
    return result
