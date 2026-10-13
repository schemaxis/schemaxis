"""Standalone authored/umbrella schemas, derived from literal declarations.

Schema checks structure; reference resolution and graph/native semantics remain
the planner's responsibility. All references are internal to the exported file.
"""
import copy

from .errors import fail
from .schema import DRAFT, NAME, object_schema, argument_schema, arguments_schema, json_value_schema

from .adaptors.registry import routes, metadata, binding, isolated

VERSIONS = {version: route.get('schemaName', provider) for version, (provider, route) in routes().items()}
VERSIONS['schemaxis.workflow/1'] = 'workflow'
COMPOSE = set(routes())
WORKFLOW_VERSIONS = tuple(version for version, (_, route) in routes().items() if route.get('workflow'))


def ref(name): return {'$ref': '#/$defs/' + name}


def alternatives(*items): return {'anyOf': list(items)}


def array(items, **limits): return {'type': 'array', 'items': items, **limits}


def tuple_schema(*items):
    return {'type': 'array', 'prefixItems': list(items), 'items': False, 'minItems': len(items), 'maxItems': len(items)}


def _rebase(schema, prefix):
    if isinstance(schema, list): return [_rebase(v, prefix) for v in schema]
    if not isinstance(schema, dict): return schema
    return {k: (prefix + v[1:] if k == '$ref' and isinstance(v, str) and v.startswith('#/') else _rebase(v, prefix)) for k, v in schema.items()}


def _copy_annotations(schema):
    # Each schema child is rebuilt by the caller. Copying its whole subtree here
    # would copy every descendant again at every level of a large catalogue.
    children = {'properties', '$defs', 'patternProperties', 'items', 'additionalProperties',
                'contains', 'oneOf', 'anyOf', 'allOf', 'prefixItems'}
    return {key: value if key in children else copy.deepcopy(value) for key, value in schema.items()}


def discriminated(schema):
    """Avoid evaluating irrelevant operation options after discriminator failure."""
    if not isinstance(schema, dict): return schema
    result = _copy_annotations(schema)
    for key in ('properties', '$defs', 'patternProperties'):
        if key in result: result[key] = {name: discriminated(value) for name, value in result[key].items()}
    for key in ('items', 'additionalProperties', 'contains'):
        if isinstance(result.get(key), dict): result[key] = discriminated(result[key])
    for key in ('oneOf', 'anyOf', 'allOf', 'prefixItems'):
        if key not in result: continue
        variants = []
        for variant in result[key]:
            variant = discriminated(variant)
            if key in ('oneOf', 'anyOf') and isinstance(variant, dict):
                for field in ('filter', '$call', '$value', 'op', 'type', 'operation'):
                    declaration = variant.get('properties', {}).get(field)
                    if not declaration or 'const' not in _literal(declaration): continue
                    test = {'const': _literal(declaration)['const']}
                    if test != declaration: test = alternatives(test, {'type': 'object'})
                    variant = {'if': {'type': 'object', 'properties': {field: test}, 'required': [field]}, 'then': variant, 'else': False}
                    break
            variants.append(variant)
        result[key] = variants
    return result


def composition_definitions():
    from .functions import FUNCTIONS
    defs = {'json': json_value_schema()}
    defs['documentReference'] = object_schema({'$document': {'type': 'string', 'pattern': r'^(?:/|\./|\.\./)(?:[^~]|~[01])*$'},
        'operation': NAME, 'scope': {'const': 'workflow'}}, ['$document'])
    defs.update({key: _lift(value, compose=True, wrap=False) for key, value in analytic_definitions().items()})
    defs['valueReference'] = object_schema({'$value': NAME, 'path': {'type': 'string', 'pattern': r'^(?:/(?:[^~]|~[01])*)?$'},
        'visit': {'type': 'integer', 'minimum': 0}, 'artifact': {'type': 'integer', 'minimum': 0}}, ['$value', 'path'])
    defs['axisReference'] = object_schema({'$axis': NAME,
        'path': array(alternatives({'type': 'string'}, {'type': 'integer', 'minimum': 0}))}, ['$axis'])
    # References and pure operations can appear recursively in their arguments.
    for kind in ('number', 'string', 'array', 'object'):
        literal = {'type': kind}
        if kind == 'array': literal['items'] = ref('authorData')
        if kind == 'object':
            literal['additionalProperties'] = ref('authorData')
            literal['not'] = {'anyOf': [{'required': [k]} for k in ('$document', '$expr', '$value')]}
        defs['author' + kind.title()] = alternatives(literal, ref('composition'), ref('analytic'))
    literal_object = {'type': 'object', 'additionalProperties': ref('authorData'),
                      'not': {'anyOf': [{'required': [k]} for k in ('$document', '$expr', '$value')]}}
    defs['authorData'] = alternatives({'type': ['null', 'boolean', 'number', 'string']},
        array(ref('authorData')), literal_object, ref('composition'))
    named = {'type': 'object', 'properties': {'name': alternatives({'type': 'string', 'minLength': 1}, ref('composition'))},
             'required': ['name'], 'additionalProperties': ref('authorData')}
    named_array = alternatives(array(named), ref('composition'))
    variants = []
    for operation in ('add', 'subtract', 'multiply', 'divide'):
        variants.append(object_schema({'op': {'const': operation}, 'args': tuple_schema(ref('authorNumber'), ref('authorNumber'))}, ['op', 'args']))
    for operation in ('merge', 'overlay', 'omit', 'concat', 'get', 'namedMerge', 'namedGet'):
        pairs = {
            'merge': (ref('authorObject'), ref('authorObject')),
            'overlay': (ref('authorObject'), ref('authorObject')),
            'omit': (ref('authorObject'), alternatives(ref('authorObject'), array(ref('authorString')), ref('composition'))),
            'get': (alternatives(ref('authorObject'), ref('authorArray')), alternatives(ref('authorString'), {'type': 'integer', 'minimum': 0}, ref('composition'))),
            'namedMerge': (named_array, named_array), 'namedGet': (named_array, ref('authorString')),
        }
        args = alternatives(tuple_schema(ref('authorString'), ref('authorString')), tuple_schema(ref('authorArray'), ref('authorArray'))) if operation == 'concat' else tuple_schema(*pairs[operation])
        props = {'op': {'const': operation}, 'args': args}
        if operation in ('merge', 'namedMerge'): props['conflict'] = {'enum': ['left', 'right', 'error']}
        variants.append(object_schema(props, ['op', 'args']))
    defs['expression'] = _lift({'oneOf': variants}, compose=True)
    calls = []
    for name, entry in FUNCTIONS.describe().items():
        if 'objectKind' in entry['result'] or any('objectKind' in s for s in entry['arguments'].values()): continue
        arguments = _lift(arguments_schema(entry['arguments']), compose=True, analytic=True)
        calls.append(object_schema({'$value': {'const': name}, 'args': arguments}, ['$value', 'args']))
    defs['composition'] = alternatives(ref('documentReference'),
        object_schema({'$expr': ref('expression')}, ['$expr']), {'oneOf': calls}, ref('valueReference'), ref('axisReference'))
    return defs


def analytic_definitions():
    scalar = alternatives({'type': 'number'}, array(ref('numericTree'), minItems=1))
    variants = []
    for kind in ('values', 'linear', 'orbit'):
        props = {'type': {'const': kind}}
        required = ['type']
        if kind == 'values':
            props['values'] = array(ref('json'), minItems=1)
            required.append('values')
        else:
            endpoint = {'type': 'number'} if kind == 'orbit' else ref('numericTree')
            props.update(start=endpoint, end=endpoint, count={'type': 'integer', 'minimum': 1})
            required += ['start', 'end', 'count']
        if kind == 'orbit': props['elevation'] = {'type': 'number', 'exclusiveMinimum': -90, 'exclusiveMaximum': 90}
        else: props['sync'] = {'type': 'string', 'minLength': 1}
        variants.append(object_schema(props, required))
    return {'numericTree': scalar, 'analytic': object_schema({'$analytic': {'oneOf': variants}}, ['$analytic'])}


def _lift(schema, *, compose=False, artifact=False, analytic=False, wrap=True):
    """Lift schema-valued positions only, leaving annotations/defaults untouched."""
    if not isinstance(schema, dict): return schema
    result = _copy_annotations(schema)
    for key in ('properties', '$defs', 'patternProperties'):
        if key in result:
            result[key] = {name: _lift(value, compose=compose, artifact=artifact, analytic=analytic) for name, value in result[key].items()}
    for key in ('items', 'additionalProperties', 'contains'):
        if isinstance(result.get(key), dict): result[key] = _lift(result[key], compose=compose, artifact=artifact, analytic=analytic)
    for key in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
        if key in result: result[key] = [_lift(v, compose=compose, artifact=artifact, analytic=analytic, wrap=key == 'prefixItems') for v in result[key]]
    if compose and 'oneOf' in result and any('properties' in v for v in result['oneOf'] if isinstance(v, dict)):
        # A composed discriminator cannot statically select exactly one literal
        # operation. Keep its possible literal types without false ambiguity.
        result['anyOf'] = result.pop('oneOf')
    choices = [result]
    if wrap and compose: choices.append(ref('composition'))
    if wrap and artifact and (result.get('type') == 'string' or '$ref' in result or 'anyOf' in result): choices.append(ref('artifact'))
    if wrap and analytic: choices.append(ref('analytic'))
    return alternatives(*choices) if len(choices) > 1 else result


def execution_schema(operation=False):
    positive = {'type': 'integer', 'minimum': 1}
    if operation:
        result = object_schema({'threads': positive, 'ranks': positive, 'memoryMB': positive,
            'gpus': {'type': 'integer', 'minimum': 0}, 'timeChunkSize': positive,
            'mpiexec': ref('json') })
        result['allOf'] = [{'if': {'properties': {'ranks': {'minimum': 2}}, 'required': ['ranks']},
            'then': {'required': ['mpiexec'], 'properties': {'mpiexec': {'type': 'string', 'pattern': '^/'}}}}]
        return result
    return object_schema({'maxWorkers': positive, 'cpus': positive, 'memoryMB': positive,
                          'gpus': {'type': 'integer', 'minimum': 0, 'maximum': 1}})


def _expanded(version):
    from .schema import export_schema
    kind = VERSIONS[version]
    if kind == 'workflow': return workflow_schema(authored=False)
    _, route = routes()[version]
    schema = binding(route['schema'])()
    schema = copy.deepcopy(schema)
    defs = schema.setdefault('$defs', {})
    defs.setdefault('json', json_value_schema())
    # Provider schema functions describe literal feature nodes. Preserve the
    # parser's ignored metadata explicitly as recursive JSON, not empty schemas.
    for key in ('definitions', 'dimensions', 'settings'):
        if key in schema['properties']:
            schema['properties'][key] = ref('json')
    hook = route.get('hooks', {}).get('expandedSchema')
    if hook: binding(hook)(schema)
    return schema


def _axis_schema():
    # Shape enforced by adaptor_runtime.Expansion._axes: a literal object with a name and
    # either values or series; the oneOf matches schema.py's graph-document axis.
    axis = object_schema({'name': NAME, 'values': array(ref('authorData'), minItems=1), 'series': ref('authorData')}, ['name'])
    axis['oneOf'] = [{'required': ['values'], 'not': {'required': ['series']}},
                     {'required': ['series'], 'not': {'required': ['values']}}]
    return axis


def version_schema(version, *, authored=False, artifact=False, annotate=None):
    if version not in VERSIONS: fail('UNSUPPORTED_VERSION', 'schema version is not supported', version, versions=list(VERSIONS))
    if version == 'schemaxis.workflow/1': return workflow_schema(authored=authored)
    result = _expanded(version)
    if annotate:
        result = annotate(result)
    compose = authored and version in COMPOSE
    if compose:
        for key in ('definitions', 'dimensions', 'settings'):
            result['properties'][key] = ref('json')
    original_defs = result.pop('$defs', {})
    if compose or artifact:
        general_analytic = compose and not routes()[version][1].get('graph')
        result = _lift(result, compose=compose, artifact=artifact, analytic=general_analytic, wrap=False)
        # CLI dispatch always precedes composition and requires a literal version.
        result['properties']['version'] = {'const': version}
        result['$defs'] = {key: _lift(value, compose=compose, artifact=artifact, analytic=general_analytic) for key, value in original_defs.items()}
    else: result['$defs'] = original_defs
    if compose:
        result['$defs'].update(composition_definitions())
        result['properties']['maxStates'] = {'type': 'integer', 'minimum': 1, 'maximum': 10000}
        if not routes()[version][1].get('graph'):
            result['properties']['axes'] = array(_axis_schema())
        if routes()[version][1].get('graph'):
            _author_graph(result, version)
    if artifact: result['$defs']['artifact'] = object_schema({'$artifact': NAME, 'index': {'type': 'integer', 'minimum': 0}}, ['$artifact', 'index'])
    result['$schema'] = DRAFT
    result['title'] = version + (' authored input' if authored else ' expanded input')
    result['description'] = ('Structural input contract. Reference targets, computed result types, graph dependencies, '
        'kind compatibility, resource availability and native correctness require Schemaxis planning/execution. '
        'Top-level version is a literal dispatch discriminator.')
    return discriminated(result)


def _literal(schema):
    # Lift always places the original literal branch first.
    return schema['anyOf'][0] if 'anyOf' in schema and any(v.get('$ref') == '#/$defs/composition' for v in schema['anyOf'] if isinstance(v, dict)) else schema


def _author_graph(schema, version):
    """Inline objects on input ports; analytics only in compiler-supported scopes."""
    defs = schema['$defs']
    analytic = analytic_definitions()
    defs.update({key: _lift(value, compose=True) for key, value in analytic.items()})
    node_union = _literal(_literal(schema['properties']['nodes'])['items'])
    inline_nodes = []
    for wrapped in node_union.get('oneOf', node_union.get('anyOf', [])):
        node = _literal(wrapped)
        if 'inputs' in node['properties']:
            inputs = _literal(node['properties']['inputs'])
            for port, value in inputs['properties'].items():
                literal = _literal(value)
                target = literal['items'] if literal.get('type') == 'array' else value
                inline = alternatives(_lift(object_schema({'$object': target}, ['$object']), compose=True),
                    _lift(object_schema({'$create': ref('inlineNode')}, ['$create']), compose=True))
                if literal.get('type') == 'array': literal['items'] = alternatives(literal['items'], inline)
                else: inputs['properties'][port] = alternatives(value, inline)
        inline = copy.deepcopy(node)
        inline['required'] = [key for key in inline.get('required', []) if key != 'id']
        inline_nodes.append(inline)
    defs['inlineNode'] = {'anyOf': inline_nodes}
    def option_runtime(value):
        if isinstance(value, list): return [option_runtime(v) for v in value]
        if not isinstance(value, dict): return value
        result = {k: option_runtime(v) for k, v in value.items()}
        if result.get('$ref') == '#/$defs/runtime': result['$ref'] = '#/$defs/optionRuntime'
        if result.get('$ref') == '#/$defs/runtimeValue': result['$ref'] = '#/$defs/optionRuntimeValue'
        props = result.get('properties', {})
        if 'args' in props: props['args'] = _lift(props['args'], analytic=True)
        return result
    defs['optionRuntime'] = option_runtime(defs['runtime'])
    defs['optionRuntimeValue'] = alternatives(option_runtime(defs['runtimeValue']), ref('analytic'))
    for name in list(defs):
        if name.startswith('options-'):
            options = _literal(defs[name])
            # Member-local analytics may nest in arrays/objects, never replace
            # the entire options dictionary or a constructor option.
            for key, value in options.get('properties', {}).items():
                literal = _literal(value)
                options['properties'][key] = option_runtime(_lift(value, analytic=True))
    scenes = _literal(schema['properties']['scenes'])
    scene = _literal(scenes['items'])
    sequence = copy.deepcopy(analytic['analytic'])
    for variant in sequence['properties']['$analytic']['oneOf']:
        variant['properties'].pop('sync', None)
    defs['sequenceAnalytic'] = _lift(sequence, compose=True)
    if 'appearances' in scene['properties']:
        scene['properties']['appearances'] = alternatives(scene['properties']['appearances'], ref('sequenceAnalytic'))
    images = _literal(scene['properties']['images'])
    image = _literal(images['items'])
    camera_list = _literal(image['properties']['cameras'])
    if 'items' in camera_list:
        camera_list['items'] = _lift(camera_list['items'], analytic=True)
    image['properties']['cameras'] = alternatives(image['properties']['cameras'], ref('sequenceAnalytic'))


def _routed(version, build):
    """``build()`` for one registered version; a failing plugin route is excluded (``None``).

    Versions are snapshotted at import, so a plugin excluded since then is skipped.
    """
    if version == 'schemaxis.workflow/1':
        return build()
    found = routes().get(version)
    return None if found is None else isolated(found[0], build)[0]


def workflow_schema(*, authored=True, annotate=None):
    """Workflow envelope; ``annotate(version)`` may return a hook for each embedded document."""
    defs = {'json': json_value_schema()}
    refs = []
    for version in WORKFLOW_VERSIONS:
        key = 'pipeline' + str(len(refs))
        schema = _routed(version, lambda: _rebase(version_schema(version, authored=authored, artifact=True,
                         annotate=annotate(version) if annotate else None), '#/$defs/' + key))
        if schema is None:
            continue
        defs[key] = schema
        refs.append(ref(key))
    operation = object_schema({'id': NAME, 'document': {'oneOf': refs}, 'execution': execution_schema(True)}, ['id', 'document'])
    properties = {'version': {'const': 'schemaxis.workflow/1'}, 'execution': execution_schema(),
                  'operations': array(operation, minItems=1)}
    if authored:
        defs.update(composition_definitions())
        properties.update({key: ref('authorData') for key in ('dimensions', 'definitions', 'settings')})
        properties['maxStates'] = {'type': 'integer', 'minimum': 1, 'maximum': 10000}
        properties['axes'] = array(_axis_schema())
    return {'$schema': DRAFT, 'title': 'Schemaxis workflow input', '$defs': defs,
            **object_schema(properties, ['version', 'operations'])}


def umbrella_schema(*, authored=True):
    defs = {}
    for version in VERSIONS:
        key = 'document' + str(len(defs))
        schema = _routed(version, lambda: _rebase(version_schema(version, authored=authored), '#/$defs/' + key))
        if schema is not None:
            defs[key] = schema
    return {'$schema': DRAFT, 'title': 'Schemaxis all authored document versions' if authored else 'Schemaxis all expanded document versions',
            'description': 'Registered input versions; all references resolve within this schema file. Semantic validation remains mandatory.',
            '$defs': defs, 'oneOf': [ref(key) for key in defs]}


def export(provider, *, operation=None, section=None, authored=False, version=None, all_versions=False):
    from .schema import export_schema
    if all_versions: return umbrella_schema(authored=authored)
    if operation is not None:
        result = export_schema(provider, operation=operation)
        if authored:
            result = _lift(result, compose=True)
            result.update({'$schema': DRAFT, '$defs': composition_definitions()})
        return result
    if section in ('execution', 'operation-execution'):
        return {'$schema': DRAFT, '$defs': {'json': json_value_schema()}, **execution_schema(section == 'operation-execution')}
    if section == 'workflow': return workflow_schema(authored=authored)
    if section in ('composition', 'analytic'):
        defs = composition_definitions()
        defs.update({key: _lift(value, compose=True) if authored else value
                     for key, value in analytic_definitions().items()})
        return {'$schema': DRAFT, '$defs': defs, **ref(section)}
    if section and section not in {r.get('schemaName') for _, r in routes().values() if r.get('graphEditing', True) is False}:
        result = export_schema(provider, section=section)
        if authored:
            result = _lift(result, compose=True)
            result.update({'$schema': DRAFT, '$defs': composition_definitions()})
        return result
    if version is None:
        from .adaptors.registry import ADAPTORS
        version = next((v for v, kind in VERSIONS.items() if kind == section), None) if section else ADAPTORS[provider]['version']
    return version_schema(version, authored=authored)
