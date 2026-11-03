# Copyright (C) 2026 David L F Gaden
"""Static native catalogue; no ParaView imports during discovery or planning."""
import copy
from functools import lru_cache
import json
from importlib.resources import files


@lru_cache(maxsize=1)
def _package():
    return json.loads(files('schemaxis.adaptors.paraview').joinpath('paraview_catalogue.json').read_text())


def generated_declarations():
    from schemaxis.errors import fail
    from schemaxis.core.declarations import validate_specifications
    result = copy.deepcopy(_package()['declarations'])
    directory = files('schemaxis.adaptors.paraview').joinpath('paraview_extensions')
    if directory.is_dir():
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            if not path.name.endswith('.json'): continue
            package = json.loads(path.read_text())
            if package.get('format') != 'schemaxis.paraview-catalogue/1':
                fail('INVALID_EXTENSION', 'extension catalogue format is unsupported', path.name)
            if package.get('version') != _package()['version']:
                fail('EXTENSION_VERSION_MISMATCH', 'recapture extension against the pinned native version', path.name)
            for name, declaration in package['declarations'].items():
                if name in result:
                    fail('DUPLICATE_FILTER', 'extension cannot replace an existing operation', name)
                validate_specifications({k:v['value'] for k,v in declaration['options'].items()}, name)
                result[name] = declaration
    return result


def coverage():
    package = _package()
    inventory = package['inventory']
    return {'version': package['version'], 'groups': package['groups'],
            'captureSHA256': package.get('captureSHA256'),
            'counts': {state: sum(v['status'] == state for v in inventory.values())
                       for state in ('declared', 'unsupported')},
            'qualification': 'generated declarations are not exhaustive native qualification',
            'inventory': copy.deepcopy(inventory)}


def enrich_curated(declarations):
    by_native = {d['native']: d for d in _package()['declarations'].values()}
    for declaration in declarations.values():
        native = by_native.get(declaration['native'])
        for port in declaration['inputs'].values():
            matching = next((p for p in native['inputs'].values() if p['native'] == port['native']), None) if native else None
            # A curated port may narrow the native contract it inherits (for example to
            # exclude a data type its fixed property assignments cannot configure).
            narrowing = port.get('contract', {})
            port['contract'] = copy.deepcopy(matching['contract'] if matching else {
                'nativeTypes': [], 'compatibility': 'unknown',
                'traits': {'contiguity': 'unknown', 'indexing': 'unknown', 'iteration': 'unknown'},
                'cost': {'rating': 'unknown', 'basis': 'no benchmark', 'conversion': 'none inserted'}})
            if narrowing:
                base = port['contract']
                if not set(narrowing.get('nativeTypes', base['nativeTypes'])) <= set(base['nativeTypes']):
                    from schemaxis.errors import fail
                    fail('INVALID_DATA_CONTRACT', 'a curated input contract may only narrow the native data types',
                         declaration['id'], native=base['nativeTypes'], curated=narrowing['nativeTypes'])
                merged = {**base['requirements'], **narrowing.get('requirements', {})}
                base.update(copy.deepcopy(narrowing))
                base['requirements'] = merged
        declaration.setdefault('execution', {'mode': 'serial', 'performance': 'unknown'})
    return declarations
