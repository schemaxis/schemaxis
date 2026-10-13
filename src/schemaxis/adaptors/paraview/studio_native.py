"""Reader setup in an isolated native worker; never imported by discovery."""
import copy
import re
from pathlib import Path
from schemaxis.errors import fail
from .filters import catalogue, validate_options
from .native import ParaViewBackend


def prepare_input(document, identity):
    node = copy.deepcopy(next(item for item in document['nodes'] if item['id'] == identity))
    if node['filter'] != 'foam':
        fail('UNSUPPORTED_INSPECTION', 'This operation has no automatic reader setup', identity)
    options = node.setdefault('options', {})
    case = Path(options['file']).expanduser().resolve().parent
    decomposed = any(path.is_dir() and re.fullmatch(r'processors?\d+(?:_\d+-\d+)?', path.name)
                     for path in case.glob('processor*'))
    options.setdefault('caseType', 'Decomposed Case' if decomposed else 'Reconstructed Case')
    declaration = catalogue()['foam']
    effective = validate_options(declaration, options, identity)
    backend = ParaViewBackend()
    proxy = backend.create(identity, declaration, {},
                           {key: value for key, value in effective.items() if declaration['options'][key].get('constructor')})
    try:
        backend.configure(proxy, declaration, effective)
        proxy.UpdatePipelineInformation()
        times = list(proxy.TimestepValues)
        if not times:
            fail('UNAVAILABLE_TIMES', 'No readable times were found. Check the case layout and Skip zero setting.', identity)
        regions = list(proxy.MeshRegions.Available)
        arrays = list(proxy.CellArrays.Available)
        # These become explicit, reviewable authored values, not altered runtime defaults.
        if regions:
            options.setdefault('regions', regions)
        if arrays:
            options.setdefault('cellArrays', arrays)
        result = {'node': identity, 'value': node, 'availableTimes': times,
                  'regions': regions, 'cellArrays': arrays,
                  'summary': f"{options['caseType']}; {len(options.get('regions', []))} mesh regions"}
        if 'times' not in document:
            result['times'] = [times[0]]
            result['summary'] += f"; time {times[0]}"
        return result
    finally:
        backend.delete(proxy)
