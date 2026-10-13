"""FreeCAD framework policies; no native application imports on the host."""
from pathlib import Path
from schemaxis.artifacts import file_digest


def resources(document, spec, identity):
    from .adaptor import plan
    from schemaxis.parallel import provisional
    plan(provisional(document))
    return {}


def reusableInputs(document):
    from .adaptor import plan
    paths = [node['options']['file'] for node in plan(document)['nodes'] if node['filter'] == 'readSTEP']
    return {str(Path(path).absolute()): file_digest(path) for path in paths}


def inspect(document, node, directory, *, locations, timeout, visit):
    from .inspection import inspect as native_inspect
    return native_inspect(document, node, directory, executable=locations.get('freecad'), timeout=timeout, visit=visit)


def expandedSchema(schema):
    from schemaxis.schema import arguments_schema, object_schema, NAME
    from .adaptor import DECLARATIONS, input_schema
    nodes = []
    for name, declaration in DECLARATIONS.items():
        options = arguments_schema({k: v['value'] for k, v in declaration['options'].items()})
        ports = input_schema(declaration['inputs'])
        required = ['id', 'filter'] + (['inputs'] if declaration['inputs'] else []) + (['options'] if options.get('required') else [])
        nodes.append(object_schema({'id': NAME, 'filter': {'const': name}, 'options': options, 'inputs': ports}, required))
    schema['properties']['nodes']['items'] = {'oneOf': nodes}
    schema['properties']['output'] = NAME
