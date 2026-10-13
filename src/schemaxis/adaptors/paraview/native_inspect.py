"""Read time metadata after applying reader options, before scheduling data."""
from pathlib import Path
from schemaxis.adaptors.paraview.filters import catalogue, validate_options
from schemaxis.pipeline import DefinitionGraph
from schemaxis.adaptors.paraview.native import ParaViewBackend
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from schemaxis.core.faults import SchemaxisError


def inspect_time_source(document, source, directory):
    master = DefinitionGraph(document, catalogue())
    node = master.nodes[source]
    declaration = master.declarations[node['filter']]
    options = validate_options(declaration, node['options'], source)
    backend = ParaViewBackend()
    constructor = {k: v for k, v in options.items() if declaration['options'][k].get('constructor')}
    proxy = backend.create(source, declaration, {}, constructor)
    try:
        backend.configure(proxy, declaration, options)
        proxy.UpdatePipelineInformation()
        if 'TimestepValues' not in proxy.ListProperties():
            fail('UNAVAILABLE_TIMES', 'source does not advertise discrete timestep metadata', source)
        result = {
            'source': source, 'operation': node['filter'], 'times': list(proxy.TimestepValues),
            'limits': 'metadata inspection; not a mesh or solver correctness certificate',
        }
        if 'file' in options: result['file'] = options['file']
        for native, key in [('CellArrays','cellArrays'), ('MeshRegions','regions')]:
            if native in proxy.ListProperties(): result[key] = list(getattr(proxy,native).Available)
        atomic_json(Path(directory) / 'inspection.json', result)
    except SchemaxisError as error:
        atomic_json(Path(directory) / 'inspection.json', {'source':source, 'fault':error.fault.to_dict()})
    finally:
        backend.delete(proxy)
