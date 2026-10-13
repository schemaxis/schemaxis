"""Host-only structural schemas for Studio's saved design envelopes.

Reuse the authored workflow contract, allowing the empty designer canvas.
Port ownership, pointer resolution, parameter bindings and loop identity still
require workflow_design.validate; schema success never promises execution.
"""
from .schema import DRAFT, NAME, object_schema as obj
from .schema_authoring import array, workflow_schema
from .workflow_design import DATA_KINDS, VERSION, VERSION_2

TEXT = {'type': 'string', 'minLength': 1}
POINTER = {'type': 'string', 'pattern': r'^(?:/(?:[^~]|~[01])*)?$'}
INDEX = {'type': 'integer', 'minimum': 0}


def mapping(item, names=None):
    result = {'type': 'object', 'additionalProperties': item}
    if names:
        result['propertyNames'] = names
    return result


def controller_schema():
    variants = []
    for algorithm in ('fixed-point', 'constant-relaxation'):
        fields = {'algorithm': {'const': algorithm},
                  'maxIterations': {'type': 'integer', 'minimum': 1, 'maximum': 1000},
                  'absoluteTolerance': {'type': 'number', 'exclusiveMinimum': 0},
                  'relativeTolerance': {'type': 'number', 'minimum': 0}}
        if algorithm == 'constant-relaxation':
            fields['relaxation'] = {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1}
        variants.append(obj(fields, fields))
    return {'oneOf': variants}


def parameter_schema():
    # Kind-specific constraints and literal defaults are checked by binding.
    constraints = obj({'minimum': {'type': 'number'}, 'maximum': {'type': 'number'},
                       'length': INDEX, 'minLength': INDEX, 'maxLength': INDEX,
                       'enum': array({}, minItems=1)})
    return obj({'label': TEXT, 'help': TEXT, 'units': TEXT, 'default': {},
                'kind': {'enum': ['number', 'integer', 'boolean', 'string', 'enum', 'vector']},
                'constraints': constraints,
                'target': obj({'scope': {'const': 'workflow'}, 'pointer': POINTER}, ['scope', 'pointer'])},
               ['label', 'kind', 'target'])


def ports_schema():
    data = obj({'kind': {'enum': list(DATA_KINDS)}, 'units': TEXT,
                'formats': array({'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.+-]*$'},
                                 minItems=1, maxItems=64, uniqueItems=True),
                'layout': {'enum': ['interleaved', 'planar']},
                'streaming': {'type': 'boolean'}, 'contiguous': {'type': 'boolean'}})
    common = {'kind': {'enum': ['artifact', 'value']}, 'data': data,
              'label': TEXT, 'generated': {'const': True}}
    port_name = {**NAME, 'maxLength': 64}
    inputs = mapping(obj({**common, 'target': POINTER}, ['kind', 'target']), port_name)
    output = obj({**common, 'artifact': INDEX, 'valuePath': POINTER}, ['kind', 'artifact'])
    output['allOf'] = [{'if': {'properties': {'kind': {'const': 'value'}}, 'required': ['kind']},
                        'then': {'required': ['valuePath']}, 'else': {'not': {'required': ['valuePath']}}}]
    return mapping(obj({'inputs': inputs, 'outputs': mapping(output, port_name)}), NAME)


def design_schema(version, annotate=None):
    """Return a standalone schema; all adaptor references remain internal."""
    if version not in (VERSION, VERSION_2):
        raise ValueError('unsupported design version')
    workflow = workflow_schema(authored=True, annotate=annotate)
    definitions = workflow.pop('$defs')
    workflow.pop('$schema')
    workflow['properties']['operations']['minItems'] = 0
    workflow['properties']['operations']['maxItems'] = 256
    properties = {'version': {'const': version}, 'workflow': workflow,
                  'controllers': mapping(controller_schema())}
    required = ['version', 'workflow', 'connections', 'controllers']
    if version == VERSION:
        connection = obj({'id': NAME, 'source': NAME, 'target': NAME, 'targetPointer': POINTER,
                          'kind': {'enum': ['artifact', 'value']}, 'artifactIndex': INDEX, 'valuePath': POINTER},
                         ['id', 'source', 'target', 'targetPointer', 'kind', 'artifactIndex'])
    else:
        end = obj({'operation': NAME, 'port': NAME}, ['operation', 'port'])
        connection = obj({'id': NAME, 'from': end, 'to': end}, ['id', 'from', 'to'])
        coordinate = {'type': 'number', 'minimum': -1e7, 'maximum': 1e7}
        point = {'x': coordinate, 'y': coordinate}
        properties.update({
            'ports': ports_schema(), 'parameters': mapping(parameter_schema()),
            'outputs': mapping(obj({'operation': NAME, 'artifact': INDEX, 'pointer': POINTER,
                                    'kind': TEXT, 'units': TEXT}, ['operation', 'artifact', 'kind'])),
            'naming': obj({'pattern': {**TEXT, 'maxLength': 256},
                           'indexWidth': {'type': 'integer', 'minimum': 1, 'maximum': 12}}),
            'layout': obj({'nodes': mapping(obj(point, ['x', 'y']), NAME),
                           'viewport': obj({**point, 'zoom': {'type': 'number', 'minimum': .01,
                                                              'maximum': 100}}, ['x', 'y', 'zoom'])}),
        })
        required.append('ports')
    properties['connections'] = array(connection, maxItems=2048)
    return {'$schema': DRAFT, 'title': 'Schemaxis workflow design', '$defs': definitions,
            'description': 'Saved design structure. Validate on the host for graph and binding semantics.',
            'x-schemaxis-inlineDocuments': ['/workflow'], **obj(properties, required)}
