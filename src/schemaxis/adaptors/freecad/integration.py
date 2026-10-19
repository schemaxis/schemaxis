"""FreeCAD framework policies; no native application imports on the host."""
from pathlib import Path
from schemaxis.artifacts import file_digest


def resources(document, spec, identity):
    from .adaptor import plan
    from schemaxis.parallel import provisional
    plan(provisional(document))
    return {}


def reusableInputs(document):
    """Current bytes of every STEP input; importSTEP planning reads and hashes the authored path now."""
    from .adaptor import plan
    prepared = plan(document)
    paths = [node['options']['file'] for node in prepared['nodes'] if node['filter'] == 'readSTEP']
    result = {str(Path(path).absolute()): file_digest(path) for path in paths}
    for node in prepared['nodes']:
        if node['filter'] == 'importSTEP':
            path, digest = node['source']['path'], node['source']['sha256']
            if result.get(path, digest) != digest:
                from schemaxis.errors import fail
                fail('INPUT_CHANGED', 'STEP input changed while collecting provenance', path)
            result[path] = digest
    return result


def retainedInputs(directory, document):
    """Complete {original path: sha256} authenticated from retained copies of a verified run.

    The originals are never read. Planning is replayed from the retained bytes bound to
    the capture record and must equal the saved plan. Scalar design studies keep
    candidate captures in their own attempts, so they report None (unavailable).
    """
    import json
    from schemaxis.errors import fail
    from schemaxis.run_paths import owned_path
    from .adaptor import plan
    from .saved_checks import records, verify_sources
    from .step_source import CapturedSources
    if 'designStudy' in document:
        return None
    directory = Path(directory)
    captured = records(directory)
    prepared = plan(document, source=CapturedSources(directory, captured))
    if json.loads(owned_path(directory, 'plan.json').read_text()) != prepared:
        fail('VERIFICATION_FAILED', 'Retained input provenance does not belong to this document', str(directory))
    return verify_sources(directory, prepared, captured)


def inspect(document, node, directory, *, locations, timeout, visit):
    from .inspection import inspect as native_inspect
    return native_inspect(document, node, directory, executable=locations.get('freecad'), timeout=timeout, visit=visit)


def expandedSchema(schema):
    from schemaxis.schema import arguments_schema, object_schema, NAME
    from .adaptor import DECLARATIONS, input_schema
    from . import parameters as parameter_policy
    nodes = []
    for name, declaration in DECLARATIONS.items():
        options = arguments_schema({k: v['value'] for k, v in declaration['options'].items()})
        ports = input_schema(declaration['inputs'])
        required = ['id', 'filter'] + (['inputs'] if any(v.get('required') for v in declaration['inputs'].values()) else []) + (['options'] if options.get('required') else [])
        nodes.append(object_schema({'id': NAME, 'filter': {'const': name}, 'options': options, 'inputs': ports,
            **({'drive':parameter_policy.drive_schema(name)} if name in parameter_policy.TARGETS else {})}, required))
    schema['properties']['nodes']['items'] = {'oneOf': nodes}
    schema['properties']['output'] = NAME
