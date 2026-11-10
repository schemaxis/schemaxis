"""Pinned single-file STEP checkpoints for the readSTEP source."""
import copy

from schemaxis.errors import fail

VERSION = 'schemaxis.gmsh/1'


def accept_resource(document, pointer, resource):
    """Admit file selection only; the typed importer still checks its bytes and solid count."""
    parts = pointer.split('/')
    node = None
    if document.get('version') == VERSION and parts == ['', 'nodes', '0', 'options', 'file']:
        nodes = document.get('nodes')
        node = nodes[0] if isinstance(nodes, list) and nodes else None
    if not isinstance(node, dict) or node.get('filter') != 'readSTEP' or not isinstance(node.get('options'), dict):
        fail('UNSUPPORTED_RESOURCE', 'Choose options.file on the readSTEP source', pointer)
    member = resource.get('member')
    if (resource.get('kind') != 'file' or not isinstance(member, str) or not member
            or resource.get('files') != [member] or not member.lower().endswith(('.step', '.stp'))):
        fail('UNSUPPORTED_RESOURCE', 'readSTEP requires a complete single .step/.stp file snapshot', pointer)
    return {'reader': 'readSTEP', 'artifactKind': 'cad', 'format': 'STEP',
            'scope': 'one pinned original STEP file; single-solid, size and unit admission remain mandatory',
            'units': 'STEP length units normalised to millimetres by the importer',
            'losses': 'solid geometry only; no recovery of source feature history or labels'}


def captured_schema(schema, reference):
    """Add workflow references to the readSTEP file field."""
    def literal(value):
        while 'anyOf' in value and any(item.get('$ref') in
                ('#/$defs/composition', '#/$defs/artifact', '#/$defs/analytic')
                for item in value['anyOf']):
            value = value['anyOf'][0]
        return value
    nodes = literal(schema['properties']['nodes'])
    choices = literal(nodes['items'])
    for wrapped in choices.get('oneOf', choices.get('anyOf', [])):
        node = literal(wrapped)
        if literal(node['properties']['filter']).get('const') == 'readSTEP':
            options = literal(node['properties']['options'])['properties']
            options['file'] = {'anyOf': [options['file'], copy.deepcopy(reference)]}
