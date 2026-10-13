"""Forward captured upstream documentation without importing ParaView."""
import json
from pathlib import Path

from schemaxis.core.faults import SchemaxisError, Fault
from .slice_options import SLICE_OPTIONS, SLICE_COVERAGE


def option_help(option):
    snapshot = json.loads((Path(__file__).parent / 'native/slice-5.13.3.json').read_text(encoding='utf-8'))
    properties = snapshot['proxies'][snapshot['root']]['properties']
    native_name = SLICE_OPTIONS.get(option, {}).get('pythonName', option)
    if native_name not in properties:
        matches = [name for name, prop in properties.items()
                   if option in (prop['nativeName'], prop['label'])]
        native_name = matches[0] if len(matches) == 1 else native_name
    if native_name not in properties:
        raise SchemaxisError(Fault('UNKNOWN_NATIVE_PROPERTY', f'unknown Slice option: {option}',
                            '$.option', 'discovery', observed={'available': sorted(properties)},
                            recovery='use an Schemaxis option name, native Python name, internal name or display label'))
    record = properties[native_name]
    return {'application': snapshot['application'], 'version': snapshot['version'],
            'source': snapshot['source'], 'documentation': record['documentation'],
            'pythonName': native_name, 'nativeName': record['nativeName'], 'label': record['label'],
            'adaptor': SLICE_COVERAGE[native_name], 'domains': record['domains'],
            'upstreamNotice': 'native/ParaView-Copyright.txt'}
